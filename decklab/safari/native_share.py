"""Safari's native Share actions, including iPad's compact UIKit popover.

Share reports some child frames in local coordinates. UIKit clicks account for
that transform. Vertical swipes use the observed global remote-container frame
and its empty gutter, away from the nested horizontal shortcut lists.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import xml.etree.ElementTree as ElementTree

from .interaction import native, raw_swipe, require, wait


COLLECTION = "activityCollectionView"
ADD_HOME = "Add to Home Screen"
NATIVE_COLLECTION = ("//XCUIElementTypeCollectionView[@name='activityCollectionView' "
                     "and not(ancestor::XCUIElementTypeWebView)]")


def share_state(source):
    root = ElementTree.fromstring(source)
    parents = {child: parent for parent in root.iter() for child in parent}

    def outside_web(element):
        while element is not None:
            if element.tag == "XCUIElementTypeWebView":
                return False
            element = parents.get(element)
        return True

    candidates = [element for element in root.iter()
                  if element.tag == "XCUIElementTypeCollectionView" and element.get("name") == COLLECTION
                  and outside_web(element)]
    # UIKit can report the container AX-invisible while its rendered action
    # cells are visible and enabled. Require those actual descendants instead.
    active = [(collection, [element for element in collection.iter()
                           if element.tag == "XCUIElementTypeCell" and element.get("name") == "actionGroupCell"
                           and element.get("visible") == "true" and element.get("enabled") == "true"
                           and outside_web(element)])
              for collection in candidates]
    active = [(collection, rows) for collection, rows in active if rows]
    rows = list(dict.fromkeys(row for _, children in active for row in children))
    actions = [{"label": row.get("label", ""), "enabled": row.get("enabled") == "true",
                "reported_bounds": {key: float(row.get(key, "0")) for key in ("x", "y", "width", "height")}}
               for row in rows]
    targets = list(dict.fromkeys(element for collection, _ in active for element in collection.iter()
                                if element.get("name") == "actionGroupCell" and element.get("label") == ADD_HOME
                                and outside_web(element)))
    target = None
    if len(targets) == 1:
        row = targets[0]
        target = {"visible": row.get("visible") == "true", "enabled": row.get("enabled") == "true",
                  "reported_bounds": {key: float(row.get(key, "0")) for key in ("x", "y", "width", "height")}}
    layout = []
    for collection, _ in active:
        local = {key: float(collection.get(key, "0")) for key in ("x", "y", "width", "height")}
        remotes, element = [], parents.get(collection)
        while element is not None:
            if element.get("name") == "ShareSheet.RemoteContainerView":
                remotes.append(element)
            element = parents.get(element)
        remote = ({key: float(remotes[0].get(key, "0")) for key in ("x", "y", "width", "height")}
                  if len(remotes) == 1 else None)
        consistent = (len(remotes) <= 1 and local["width"] > 0 and local["height"] > 0
                      and all(math.isfinite(value) for value in local.values()))
        if remote is not None:
            consistent = (consistent and all(math.isfinite(value) for value in remote.values())
                          and abs(local["width"] - remote["width"]) <= 1
                          and abs(local["height"] - remote["height"]) <= 1)
        layout.append({"collection": local, "remote_container": remote, "consistent": consistent})
    return {"ready": bool(active and actions and all(item["consistent"] for item in layout)), "actions": actions,
            "labels": [row["label"] for row in actions],
            "collection_count": len(active),
            "collection_ax_visibility": [collection.get("visible") for collection, _ in active],
            "target": target, "target_count": len(targets), "layout": layout}


def _snapshot(driver):
    source = str(driver.command("GET", "/source"))
    return share_state(source), source


def _ready(driver, timeout=30, changed_from=None):
    last, previous_signature = {}, None

    def observed():
        nonlocal last, previous_signature
        last, source = _snapshot(driver)
        if not last["ready"] or (changed_from is not None and last["labels"] == changed_from):
            previous_signature = None
            return None
        signature = json.dumps({key: last[key] for key in ("layout", "actions", "target")}, sort_keys=True)
        stable = signature == previous_signature
        previous_signature = signature
        if stable:
            last["stable_samples"] = 2
            return last, source
        return None

    try:
        return wait(observed, timeout, "Safari Share did not settle its native activity layout and actions")
    except AssertionError as error:
        raise AssertionError(f"{error}; observed_native_share={last}") from error


def _capture(driver, fixture, name, source):
    directory = getattr(fixture, "artifacts_dir", None)
    if not directory:
        return []
    directory = Path(directory)
    screenshot, tree = directory / f"{name}.png", directory / f"{name}.source.txt"
    screenshot.write_bytes(driver.screenshot())
    tree.write_text(source, encoding="utf-8")
    return [screenshot.name, tree.name]


def _action(driver, label):
    # UIKit cells remain the target. Tapping their reported x/y would miss an
    # iPad popover whose descendants still report a local (0,0) origin.
    quoted = json.dumps(label)
    xpath = NATIVE_COLLECTION + f"//XCUIElementTypeCell[@name='actionGroupCell' and @visible='true' and @enabled='true' and @label={quoted}]"
    element = driver.find("xpath", xpath)
    require(driver.command("GET", f"/element/{element}/enabled") is True,
            f"Native Share action {label!r} is disabled")
    return element


def share_scroll_geometry(source, window):
    """Map the native collection's empty left gutter into its owned frame."""
    root = ElementTree.fromstring(source)
    parents = {child: parent for parent in root.iter() for child in parent}
    candidates = [element for element in root.iter()
                  if element.tag == "XCUIElementTypeCollectionView" and element.get("name") == COLLECTION]
    owned = []
    for collection in candidates:
        ancestors, element = [], parents.get(collection)
        while element is not None:
            ancestors.append(element)
            element = parents.get(element)
        remote = [element for element in ancestors if element.get("name") == "ShareSheet.RemoteContainerView"]
        if len(remote) == 1 and not any(element.tag == "XCUIElementTypeWebView" for element in ancestors):
            owned.append((collection, remote[0]))
    require(len(owned) == 1, "Native Share scroll needs one collection owned by its observed remote container")
    collection, remote = owned[0]

    def rect(element):
        value = {key: float(element.get(key, "0")) for key in ("x", "y", "width", "height")}
        require(all(math.isfinite(number) for number in value.values()), f"Non-finite native Share bounds: {value}")
        return value

    local, frame = rect(collection), rect(remote)
    require(remote.get("visible") == "true" and local["width"] > 0 and local["height"] > 0
            and abs(local["width"] - frame["width"]) <= 1 and abs(local["height"] - frame["height"]) <= 1,
            f"Native Share collection/remote dimensions do not match: collection={local}, remote={frame}")
    require(frame["x"] >= window["x"] - 1 and frame["y"] >= window["y"] - 1
            and frame["x"] + frame["width"] <= window["x"] + window["width"] + 1
            and frame["y"] + frame["height"] <= window["y"] + window["height"] + 1,
            f"Native Share remote frame is outside the window: frame={frame}, window={window}")
    # Include hidden actions too: Add to Home Screen's 20pt inset is narrower
    # than the 37pt inset of the visible horizontal shortcuts in landscape.
    children = [element for element in collection.iter()
                if element.get("name") == "actionGroupCell" or element.tag == "XCUIElementTypeScrollView"]
    boxes = [(element, rect(element)) for element in children]
    insets = [box["x"] - local["x"] for _, box in boxes
              if box["width"] > 0 and box["height"] > 0 and box["x"] > local["x"]]
    require(insets and min(insets) >= 4, f"Native Share has no measurable empty left gutter: collection={local}")
    inset = min(insets)
    local_x = local["x"] + inset / 2
    x = frame["x"] + inset / 2
    top = max(frame["y"], window["y"]) + 16
    bottom = min(frame["y"] + frame["height"], window["y"] + window["height"]) - 16
    require(bottom - top > 60, f"Native Share gutter is too short for a vertical swipe: frame={frame}")
    targets = [element for element in collection.iter()
               if element.get("name") == "actionGroupCell" and element.get("label") == ADD_HOME]
    require(len(targets) == 1, "Adaptive native Share scrolling needs the observed Add to Home Screen row")
    target = rect(targets[0])
    require(targets[0].get("enabled") == "true" and target["height"] > 0 and target["width"] > 0,
            f"Native Share target is disabled or has no usable bounds: {target}")
    direction = "up" if target["y"] + target["height"] / 2 > local["y"] + local["height"] / 2 else "down"
    # A full-height swipe overshoots Add into the fixed heading in landscape.
    # Re-observe after each short, slow step and reverse when it is above us.
    distance = min(90, (bottom - top) * 0.22)
    middle = (top + bottom) / 2
    start, end = middle + distance / 2, middle - distance / 2
    if direction == "down":
        start, end = end, start
    horizontal = [box for element, box in boxes if element.tag == "XCUIElementTypeScrollView"
                  and box["width"] > box["height"] and box["height"] > 0]
    for box in horizontal:
        scroll_top = frame["y"] + box["y"] - local["y"]
        scroll_bottom = scroll_top + box["height"]
        overlaps_y = max(start, end) > scroll_top and min(start, end) < scroll_bottom
        require(not (overlaps_y and box["x"] <= local_x <= box["x"] + box["width"]),
                f"Native Share gutter would cross a horizontal shortcut list: gutter_x={local_x}, list={box}")
    return {"start": (x, start), "end": (x, end), "direction": direction, "duration_ms": 650,
            "target": target, "collection": local, "remote_container": frame,
            "left_inset": inset, "horizontal_lists": horizontal}


def open_add_home_screen(driver, fixture):
    """Wait for Share, expand once if needed, then select the real native action."""
    native(driver)
    state, source = _ready(driver)
    evidence = {"initial": state, "expanded": False, "element_swipes": [],
                "artifacts": _capture(driver, fixture, "share-open", source)}
    if ADD_HOME not in state["labels"] and "View More" in state["labels"]:
        before = state["labels"]
        driver.click(_action(driver, "View More"))

        state, source = _ready(driver, timeout=20, changed_from=before)
        evidence["expanded"] = True
        evidence["after_expand"] = state
        evidence["artifacts"].extend(_capture(driver, fixture, "share-expanded", source))

    for attempt in range(6):
        require(state["ready"], f"Native Share was dismissed before Add to Home Screen: {state}")
        if ADD_HOME in state["labels"]:
            driver.click(_action(driver, ADD_HOME))
            evidence["selected"] = ADD_HOME
            evidence["before_selection"] = state
            return evidence
        require(attempt < 5, f"Native Share has no Add to Home Screen after five native swipes: {state}")
        require(state["collection_count"] == 1, f"Native Share collection is ambiguous: {state}")
        geometry = share_scroll_geometry(source, driver.command("GET", "/window/rect"))
        gesture = raw_swipe(driver, geometry["start"], geometry["end"], duration=650)
        state, source = _ready(driver, timeout=10)
        evidence["element_swipes"].append({"container": COLLECTION, "direction": geometry["direction"], "after": state,
                                            "geometry": geometry, "native_gesture": gesture})
        evidence["artifacts"].extend(_capture(driver, fixture, f"share-scroll-{attempt + 1}", source))
