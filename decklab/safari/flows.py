"""E11-S29 regression scenarios against real iOS/iPadOS Safari in Simulator.

The runner supplies a fresh disposable fixture and Simulator for each matrix
entry. A case returns its measurements for the report; failed preconditions are
failures, never substituted with a DOM double or a JavaScript gesture.
"""
from __future__ import annotations

import json
import time
from urllib.parse import quote, urlsplit

from .native_share import open_add_home_screen

from .interaction import (anchor_transform, bounds, choose_native_profile, css, focus_native_field, fully_visible, mobile, native,
                          native_element, native_rect, no_page_errors,
                          native_home_screen_ready,
                          launch_home_screen_icon,
                          read_input_trace, require, start_input_trace, tap_native_rect,
                          tap_native_button,
                          tap_native_visible_part,
                          text, touch, visit, wait, wait_native_add_dismissed, web)


def receipt_open(driver, fixture):
    visit(driver, fixture, f"/receipt?order={quote(fixture.order_id)}")
    wait(lambda: css(driver, ".rcpt-grid .card-tile-open"), message="Receipt fixture has no card tiles")
    opened = tap_native_visible_part(driver, fixture, ".rcpt-grid .card-tile-open")
    wait(lambda: text(driver, ".rcpt-sheet-count"), message="Receipt inspection did not open")
    wait(lambda: driver.execute("const i=document.querySelector('.rcpt-sheet-pic img'); return i && i.complete && i.naturalWidth>0;"),
         message="Receipt card image did not load")
    return opened


def receipt_layout(driver, fixture):
    opened = receipt_open(driver, fixture)
    selectors = {"heading": "dialog.sheet[open] .sheet-head", "close": "dialog.sheet[open] .sheet-head .sheet-close",
                 "navigation": ".rcpt-sheet-nav", "position": ".rcpt-sheet-count",
                 "swipe_hint": ".rcpt-sheet-hint"}
    measurements = {name: bounds(driver, selector) for name, selector in selectors.items()}
    for name, value in measurements.items():
        fully_visible(value, f"Receipt {name} in initial viewport")
    body = bounds(driver, "dialog.sheet[open] .sheet-body")
    require(body["scrollTop"] == 0, f"Receipt inspection initially scrolled: {body}")
    require("swipe" in text(driver, ".rcpt-sheet-hint").lower(), "Receipt guidance no longer mentions swiping")
    top = bounds(driver, ".rcpt-sheet-top")
    picture = bounds(driver, ".rcpt-sheet-pic")
    width = driver.execute("return innerWidth;")
    expected = min(320, top["rect"]["width"]) if width < 600 else min(244, 0.62 * width)
    require(abs(picture["rect"]["width"] - expected) <= 2,
            f"Receipt picture width {picture['rect']['width']}px; intended {expected}px")
    require(abs(picture["rect"]["height"] / picture["rect"]["width"] - 680 / 488) < 0.02,
            f"Receipt picture aspect ratio changed: {picture}")
    overflow = driver.execute("return {page:document.documentElement.scrollWidth-innerWidth, body:document.body.scrollWidth-innerWidth};")
    for name, value in overflow.items():
        require(value <= 1, f"Horizontal overflow in {name}: {value}px")
    for name, value in (("sheet body", body), ("picture area", top)):
        require(value["scrollWidth"] <= value["clientWidth"] + 1, f"Horizontal overflow in {name}: {value}")
    no_page_errors(driver)
    return {**measurements, "picture": picture, "expected_image_width": expected, "overflow": overflow,
            "native_open": opened}


def position(driver, selector):
    value = text(driver, selector)
    require(value and "/" in value, f"Card position is missing: {selector}: {value}")
    index, total = (int(item.strip()) for item in value.split("/"))
    return index, total


def exactly_one(driver, fixture, selector, before, direction):
    expected = before[0] + direction
    wait(lambda: position(driver, selector)[0] == expected, message=f"Native swipe did not reach card {expected}")
    # A second pointer/click handler must not turn one finger into two advances.
    time.sleep(0.5)
    after = position(driver, selector)
    require(after == (expected, before[1]), f"One native swipe changed more than one card: {before} -> {after}")
    require(driver.execute("return location.hash;").startswith(f"#/receipt?order={quote(fixture.order_id)}"),
            "Native swipe navigated away from the receipt")
    return after


def receipt_gesture_area(driver, fixture):
    """Prepare only gesture cases; initial viewport assertions never scroll."""
    transform = anchor_transform(driver, fixture, "dialog.sheet[open] .sheet-head .sheet-close")
    before = position(driver, ".rcpt-sheet-count")
    route = driver.execute("return location.hash;")
    preparation = []
    for attempt in range(4):
        image = bounds(driver, ".rcpt-sheet-pic")["visible"]
        body = bounds(driver, "dialog.sheet[open] .sheet-body")["visible"]
        available = body["bottom"] - body["top"]
        wanted = min(90, available - 16)
        require(wanted >= 30, f"Receipt body has no usable native swipe area: {body}")
        if image["bottom"] - image["top"] >= wanted:
            return transform, preparation
        require(attempt < 3, f"Receipt photo was not revealed after three native sheet scrolls: image={image}, body={body}")
        x = (body["left"] + body["right"]) / 2
        gesture = touch(driver, transform, (x, body["bottom"] - 8), (x, body["top"] + 8))
        web(driver, fixture.base_url, standalone=False)
        time.sleep(0.2)
        require(position(driver, ".rcpt-sheet-count") == before, "Preparing the native receipt swipe area changed the card")
        require(driver.execute("return location.hash;") == route, "Preparing the native receipt swipe area navigated away")
        preparation.append({"native_gesture": gesture, "position_unchanged": before})


def receipt_swipe(driver, fixture, margin=False):
    receipt_open(driver, fixture)
    transform, preparation = receipt_gesture_area(driver, fixture)
    before = position(driver, ".rcpt-sheet-count")
    require(before[0] == 1 and before[1] >= 3, f"Fixture needs at least three receipt cards: {before}")
    top, image = bounds(driver, ".rcpt-sheet-top"), bounds(driver, ".rcpt-sheet-pic")
    visible = image["visible"]
    y = (visible["top"] + visible["bottom"]) / 2
    if margin:
        gap = top["visible"]["right"] - image["rect"]["right"]
        require(gap >= 4, f"Receipt has no surrounding margin to exercise: {top}, {image}")
        x = image["rect"]["right"] + gap / 2
    else:
        x = min(image["rect"]["right"] - 15, image["rect"]["left"] + image["rect"]["width"] * 0.75)
    end = max(top["visible"]["left"] + 12, x - 135)
    require(x - end > 65 and visible["bottom"] - visible["top"] >= 30, "No visible native swipe path")
    gesture = touch(driver, transform, (x, y), (end, y))
    web(driver, fixture.base_url, standalone=False)
    after = exactly_one(driver, fixture, ".rcpt-sheet-count", before, 1)
    require(not driver.execute("return !!document.querySelector('dialog.viewer[open]');"),
            "Receipt swipe also opened the card viewer")
    reverse_transform, reverse_preparation = receipt_gesture_area(driver, fixture)
    image = bounds(driver, ".rcpt-sheet-pic")["visible"]
    left, right = image["left"] + 20, image["right"] - 20
    y = (image["top"] + image["bottom"]) / 2
    backward = touch(driver, reverse_transform, (left, y), (right, y))
    web(driver, fixture.base_url, standalone=False)
    restored = exactly_one(driver, fixture, ".rcpt-sheet-count", after, -1)
    no_page_errors(driver)
    return {"started_on": "margin" if margin else "image", "before": before, "after": after,
            "restored": restored, "native_gestures": [gesture, backward],
            "coordinate_transforms": [transform, reverse_transform],
            "native_preparation": [*preparation, *reverse_preparation]}


def receipt_vertical(driver, fixture):
    receipt_open(driver, fixture)
    transform, preparation = receipt_gesture_area(driver, fixture)
    before = position(driver, ".rcpt-sheet-count")
    heading = text(driver, "dialog.sheet[open] .sheet-head h2")
    image = bounds(driver, ".rcpt-sheet-pic")
    visible = image["visible"]
    x = (visible["left"] + visible["right"]) / 2
    bottom, top = visible["bottom"] - 6, visible["top"] + 6
    require(bottom - top >= 25, f"No visible vertical swipe path: {image}")
    scroll_before = driver.execute("return document.querySelector('dialog.sheet[open] .sheet-body').scrollTop;")
    gesture = touch(driver, transform, (x, bottom), (x, top))
    web(driver, fixture.base_url, standalone=False)

    def scrolled():
        value = driver.execute("const e=document.querySelector('dialog.sheet[open] .sheet-body'); return e && e.scrollTop;")
        return value if value is not None and value > scroll_before + 1 else None

    scroll = wait(scrolled, message="Native vertical gesture did not actually scroll the receipt further")
    require(position(driver, ".rcpt-sheet-count") == before, "Vertical scrolling changed the inspected card")
    require(text(driver, "dialog.sheet[open] .sheet-head h2") == heading, "Vertical scrolling changed the card heading")
    require(driver.execute("return location.hash;").startswith(f"#/receipt?order={quote(fixture.order_id)}"),
            "Vertical gesture navigated Safari back")
    no_page_errors(driver)
    return {"position_unchanged": before, "sheet_scroll_before": scroll_before, "sheet_scroll_top": scroll, "native_gesture": gesture,
            "coordinate_transform": transform, "native_preparation": preparation}


def viewer_swipes(driver, fixture):
    receipt_open(driver, fixture)
    receipt_transform, preparation = receipt_gesture_area(driver, fixture)
    picture = bounds(driver, ".rcpt-sheet-pic")["visible"]
    open_gesture = touch(driver, receipt_transform,
                         ((picture["left"] + picture["right"]) / 2, (picture["top"] + picture["bottom"]) / 2))
    web(driver, fixture.base_url, standalone=False)
    wait(lambda: position(driver, ".viewer-count"), message="Card viewer did not open")
    transform = anchor_transform(driver, fixture, ".viewer-close")
    before = position(driver, ".viewer-count")
    require(before[0] == 1 and before[1] >= 3, f"Viewer fixture has insufficient cards: {before}")
    stage = bounds(driver, ".viewer-stage")["visible"]
    y = (stage["top"] + stage["bottom"]) / 2
    start, end = stage["right"] - 35, stage["left"] + 35
    require(start - end > 80, f"Viewer has no visible native swipe path: {stage}")
    forward = touch(driver, transform, (start, y), (end, y))
    web(driver, fixture.base_url, standalone=False)
    middle = exactly_one(driver, fixture, ".viewer-count", before, 1)
    reverse_transform = anchor_transform(driver, fixture, ".viewer-close")
    backward = touch(driver, reverse_transform, (end, y), (start, y))
    web(driver, fixture.base_url, standalone=False)
    after = exactly_one(driver, fixture, ".viewer-count", middle, -1)
    no_page_errors(driver)
    return {"before": before, "forward": middle, "backward": after, "native_gestures": [forward, backward],
            "coordinate_transforms": [transform, reverse_transform],
            "native_preparation": preparation, "native_open_tap": open_gesture}


def keyboard_save_history(driver, fixture):
    try:
        return _keyboard_save_history(driver, fixture)
    except AssertionError as error:
        try:
            web(driver, fixture.base_url, standalone=False)
            trace = read_input_trace(driver)
            native(driver)
            trace["native_keyboard_shown"] = mobile(driver, "isKeyboardShown")
            web(driver, fixture.base_url, standalone=False)
        except Exception as diagnostic_error:
            trace = {"diagnostic_error": str(diagnostic_error)}
        raise AssertionError(f"{error}; observed_input={json.dumps(trace)}") from error


def _keyboard_save_history(driver, fixture):
    visit(driver, fixture, f"/edit?id={quote(fixture.deck_id)}")
    quick = driver.execute("return document.body.classList.contains('is-quick-edit');")
    selector = '.qty-input[aria-label="Copies of Forest"]'
    wait(lambda: css(driver, selector), message="Fixture editor has no Forest quantity")
    initial = int(driver.execute("return document.querySelector(arguments[0]).value;", [selector]))
    target = initial + 1
    require(target <= 99, "Fixture Forest quantity cannot be incremented")
    start_input_trace(driver)
    focus = focus_native_field(driver, fixture, selector)
    native(driver)
    wait(lambda: mobile(driver, "isKeyboardShown"), message="Simulator software keyboard did not open")
    keyboard = wait(lambda: driver.find("class name", "XCUIElementTypeKeyboard"), message="Native software keyboard not inspectable")
    keyboard_box = native_rect(driver, keyboard)
    # The page selects the old count on focus. Type through the native keyboard;
    # setting .value or sending a DOM input event would miss the actual regression.
    for digit in str(target):
        key = native_element(driver, digit, element_type="XCUIElementTypeKey")
        driver.click(key)
    web(driver, fixture.base_url, standalone=False)
    wait(lambda: driver.execute("return document.querySelector(arguments[0]).value === arguments[1];", [selector, str(target)]),
         message="Native keyboard did not replace the Forest quantity")
    wait(lambda: driver.execute("const s=document.querySelector('.bar-save'); return s && !s.disabled && !s.dataset.busy && ![...document.querySelectorAll('.bar-checking')].some(e=>!e.hidden);"),
         message="Save did not become enabled after quantity validation")
    save = bounds(driver, ".bar-save")
    fully_visible(save, "Save with the software keyboard visible")
    require(not save["disabled"], f"Save is disabled before its native tap: {save}")
    before_tap = read_input_trace(driver)
    native(driver)
    require(mobile(driver, "isKeyboardShown"), "Keyboard disappeared before the Save check")
    button = native_element(driver, "Save", prefix=True, webview_only=True)
    save_box = native_rect(driver, button)
    enabled = driver.command("GET", f"/element/{button}/enabled")
    require(enabled is True, f"Native Save is disabled: native={save_box}, observed={before_tap}")
    require(save_box["height"] > 0 and save_box["y"] + save_box["height"] <= keyboard_box["y"] + 1,
            f"Native Save is covered by the software keyboard: save={save_box}, keyboard={keyboard_box}")
    artifacts_dir = getattr(fixture, "artifacts_dir", None)
    if artifacts_dir:
        before_tap["screenshot"] = "keyboard-before-save.png"
        (artifacts_dir / before_tap["screenshot"]).write_bytes(driver.screenshot())
    # One genuine finger tap at the verified keyboard-open position. XCTest's
    # element.tap may scroll/activate first, which can hide the keyboard itself.
    gesture = tap_native_rect(driver, save_box)
    web(driver, fixture.base_url, standalone=False)
    wait(lambda: driver.execute("const s=document.querySelector('.bar-save'); return s && !s.disabled && !s.dataset.busy && !!s.querySelector('.dot[hidden]');"),
         message=f"Single native keyboard-open Save tap did not finish; native_tap={gesture}; "
                 f"native_save={save_box}; keyboard={keyboard_box}; before={json.dumps(before_tap)}")
    trace = read_input_trace(driver)
    # Reload the editor to prove a server save rather than local draft state.
    visit(driver, fixture, f"/edit?id={quote(fixture.deck_id)}")
    wait(lambda: css(driver, selector), message="Saved editor did not reopen")
    saved = driver.execute("return document.querySelector(arguments[0]).value;", [selector])
    require(saved == str(target), f"Saved Forest count did not persist: expected {target}, saw {saved}")
    visit(driver, fixture, f"/history?id={quote(fixture.deck_id)}")
    latest = wait(lambda: text(driver, ".history-revs > li:first-child .history-meta"), message="History has no saved revision")
    expected_author = getattr(fixture, "profile_name", "Matt")
    require(expected_author in latest, f"Latest History entry is not attributed to {expected_author}: {latest}")
    changes = text(driver, ".history-revs > li:first-child")
    require("+1 Forest" in changes, f"Latest History entry does not describe the saved +1 Forest edit: {changes}")
    no_page_errors(driver)
    return {"editor_mode": "quick" if quick else "full",
            "count_before": initial, "count_saved": target, "software_keyboard": keyboard_box,
            "native_save": save_box, "save_visible_bounds": save, "history": changes,
            "quantity_focus": focus, "native_tap": gesture, "before_tap": before_tap, "input_trace": trace}


def browser_button(driver, names, timeout=4):
    native(driver)
    tests = " or ".join(f"@name='{name}' or @label='{name}'" for name in names)
    xpath = f"//XCUIElementTypeButton[({tests}) and not(ancestor::XCUIElementTypeWebView)]"
    return wait(lambda: driver.find("xpath", xpath), timeout, f"Safari browser button unavailable: {names}")


def share_home_screen(driver, fixture):
    visit(driver, fixture, "/library")
    # New Safari layouts put Share in More; both paths use actual native UI.
    try:
        share = browser_button(driver, ("Share", "ShareButton"))
    except AssertionError:
        more = browser_button(driver, ("More", "MoreButton", "More Actions", "Page Menu"))
        driver.click(more)
        share = native_element(driver, "Share", prefix=True)
    share_box = native_rect(driver, share)
    tap_native_rect(driver, share_box)
    share_actions = open_add_home_screen(driver, fixture)
    ready = native_home_screen_ready(driver)
    tap_native_rect(driver, ready["native_add"])
    wait_native_add_dismissed(driver)
    # iOS can return to SpringBoard as soon as the icon is installed. Bring
    # Safari forward to inspect its page errors before the real icon launch.
    native(driver)
    mobile(driver, "activateApp", bundleId="com.apple.mobilesafari")
    web(driver, fixture.base_url, standalone=False)
    no_page_errors(driver)
    native(driver)
    mobile(driver, "pressButton", name="home")
    launch = launch_home_screen_icon(driver, ready["icon_name"])
    web(driver, fixture.base_url, standalone=True, timeout=35)
    wait(lambda: driver.execute("return document.readyState === 'complete' && !!document.querySelector('#main h1');"),
         message="Home Screen app did not load Deck Lab")
    require(driver.execute("return navigator.standalone === true;"), "Home Screen icon opened ordinary Safari")
    # manifest.start_url is '/', so the app can legitimately open the chooser
    # instead of the Safari URL. Select the fixture profile through its real UI.
    profile_choice = None
    if driver.execute("return !!document.querySelector('.who-button');"):
        profile_choice = choose_native_profile(driver, fixture)
    wait(lambda: driver.execute("return document.body.classList.contains('has-shell');"),
         message="Home Screen app did not enter the fixture profile")
    no_page_errors(driver)
    return {"share_sheet_native_scrolls": len(share_actions["element_swipes"]), "standalone": True,
            "native_share": share_actions,
            "home_screen_name": ready["icon_name"], "native_add": ready["native_add"], "native_launch": launch,
            "native_profile_choice": profile_choice}


def standalone_safe_areas(driver, fixture):
    web(driver, fixture.base_url, standalone=True, timeout=10)
    wait(lambda: css(driver, ".topbar-inner .avatar-button"), message="Standalone app has no signed-in shell")
    insets = driver.execute("""
      const p=document.createElement('div'); p.style.cssText='position:fixed;visibility:hidden;pointer-events:none;padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)';
      document.body.append(p); const s=getComputedStyle(p), out={};
      for(const side of ['top','right','bottom','left']) out[side]=parseFloat(s.getPropertyValue('padding-'+side))||0;
      p.remove(); return out;
    """)
    controls = driver.execute("""
      return [...document.querySelectorAll('.topbar-inner .brand,.topbar-inner .avatar-button,.topbar-inner .nav-item,.tabbar .tab')]
        .filter(e=>{const r=e.getBoundingClientRect(); return r.width>0&&r.height>0;})
        .map(e=>{const r=e.getBoundingClientRect(); return {label:e.getAttribute('aria-label')||e.textContent.trim(),left:r.left,top:r.top,right:r.right,bottom:r.bottom};});
    """)
    viewport = bounds(driver, ".topbar-inner")["viewport"]
    expected_orientation = getattr(fixture, "expected_orientation", None)
    if expected_orientation:
        require((viewport["width"] > viewport["height"]) == (expected_orientation == "LANDSCAPE"),
                f"Standalone viewport does not match {expected_orientation}: {viewport}")
    require(len(controls) >= 2, "Standalone shell has too few visible controls")
    for control in controls:
        require(control["left"] >= viewport["left"] + insets["left"] - 1
                and control["right"] <= viewport["right"] - insets["right"] + 1
                and control["top"] >= viewport["top"] + insets["top"] - 1
                and control["bottom"] <= viewport["bottom"] - insets["bottom"] + 1,
                f"Standalone control overlaps a safe area or viewport edge: {control}; insets={insets}, viewport={viewport}")
    overflow = driver.execute("return document.documentElement.scrollWidth-innerWidth;")
    require(overflow <= 1, f"Standalone horizontal overflow: {overflow}px")
    no_page_errors(driver)
    return {"standalone": True, "safe_area_insets": insets, "viewport": viewport, "controls": controls}


def stale_reload(driver, fixture):
    # This independent lifecycle case starts with fresh native browser state.
    # The installed Home Screen app and its context remain available.
    native(driver)
    mobile(driver, "terminateApp", bundleId="com.apple.mobilesafari")
    remembered = getattr(driver, "_decklab_web_contexts", None)
    if isinstance(remembered, dict):
        parsed = urlsplit(fixture.base_url)
        remembered.pop((f"{parsed.scheme}://{parsed.netloc}", False), None)
    visit(driver, fixture, "/library")
    old = driver.execute("return document.querySelector('meta[name=decklab-web-revision]').content;")
    expected = fixture.advance_version()
    require(expected and expected != old, f"Fixture did not publish a new page revision: {old} -> {expected}")
    # Wait for the page's real 30-second poll. Calling showFooter/renderVersionStatus
    # would skip the stale-page lifecycle this case is intended to protect.
    wait(lambda: driver.execute("return [...document.querySelectorAll('#build-warning button')].some(e=>e.textContent.trim()==='Reload page');"),
         timeout=50, message="Stale page did not offer Reload page after its version poll")
    require(driver.execute("return document.querySelector('meta[name=decklab-web-revision]').content;") == old,
            "Page unexpectedly reloaded without the user's action")
    warning = text(driver, "#build-warning")
    require("out of date" in warning, f"Stale warning did not explain the update: {warning}")
    route = driver.execute("return location.hash;")
    gesture = tap_native_button(driver, fixture, "#build-warning button")
    wait(lambda: driver.execute("return document.querySelector('meta[name=decklab-web-revision]').content;") == expected,
         message="Reload page did not load the newly published page revision")
    wait(lambda: not driver.execute("return [...document.querySelectorAll('#build-warning button')].some(e=>e.textContent.trim()==='Reload page');"),
         message="Updated page still offers Reload page")
    no_page_errors(driver)
    require(driver.execute("return location.hash;") == route, "Reload page changed the route")
    return {"old_page_revision": old, "loaded_page_revision": expected, "stale_warning": warning,
            "native_reload": gesture, "route_preserved": route, "fresh_safari_process": True}


def run_flows(driver, fixture, record):
    """Execute independently reported cases; a missing native feature is a failure."""
    cases = (("receipt.initial_viewport", receipt_layout),
             ("receipt.image_swipe_exactly_one", receipt_swipe),
             ("receipt.margin_swipe_exactly_one", lambda d, f: receipt_swipe(d, f, margin=True)),
             ("receipt.vertical_scroll_keeps_card_and_route", receipt_vertical),
             ("card_viewer.native_swipes", viewer_swipes),
             ("editor.keyboard_save_persistence_history", keyboard_save_history),
             ("safari.native_share_add_home_screen", share_home_screen),
             ("standalone.visible_safe_areas", standalone_safe_areas),
             ("version.stale_detection_reload", stale_reload))
    for name, case in cases:
        record(name, lambda case=case: case(driver, fixture))
