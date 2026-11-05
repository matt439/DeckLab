"""Native Simulator interactions and measured DOM bounds for the Safari suite.

JavaScript here observes the real page; it never dispatches input events or calls
application handlers. Touch input goes through XCUITest/W3C pointer actions.
"""
from __future__ import annotations

import json
import math
import re
import time
import xml.etree.ElementTree as ElementTree
from urllib.parse import urlsplit


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def wait(predicate, timeout=20, message="condition did not become true"):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except Exception as error:
            last_error = error
        time.sleep(0.25)
    suffix = f"; last error: {last_error}" if last_error else ""
    raise AssertionError(message + suffix)


def mobile(driver, command_name, **arguments):
    return driver.execute(f"mobile: {command_name}", [arguments] if arguments else [])


def native(driver):
    driver.switch_context("NATIVE_APP")


def web(driver, base_url, standalone=None, timeout=25, expected_url=None):
    """Select the requested page and remember it across native gesture switches.

    Safari can keep several same-origin tabs. A visit must match the entire URL;
    later native-to-web switches return to that selection, not the oldest tab.
    """
    origin = f"{urlsplit(base_url).scheme}://{urlsplit(base_url).netloc}"
    remembered = getattr(driver, "_decklab_web_contexts", None)
    if not isinstance(remembered, dict):
        remembered = driver._decklab_web_contexts = {}
    key = (origin, standalone)

    try:
        active = driver.command("GET", "/context")
    except Exception:
        active = None

    def matches(value):
        return (value["origin"] == origin
                and value["visibilityState"] == "visible"
                and (standalone is None or value["standalone"] == standalone)
                and (expected_url is None or value["href"] == expected_url))

    observe = ("return {origin:location.origin, href:location.href, standalone:navigator.standalone === true, "
               "visibilityState:document.visibilityState};")
    # Enumerating contexts can prune an already connected Home Screen webview.
    # Observe the live page first, with no enumeration or redundant switch.
    # Matching URLs in background tabs can retain obsolete viewport geometry.
    if active and active != "NATIVE_APP":
        try:
            if matches(driver.execute(observe)):
                remembered[key] = active
                return active
        except Exception:
            pass

    cached = remembered.get(key)
    if cached and cached != active:
        try:
            driver.switch_context(cached)
            if matches(driver.execute(observe)):
                return cached
        except Exception:
            pass

    def choose():
        names = [context.get("id") if isinstance(context, dict) else context
                 for context in driver.contexts()]
        # Prefer the current web tab, then our last selection. Context ids are
        # opaque and their enumeration order does not identify the active page.
        ordered = list(dict.fromkeys([active, remembered.get(key), *names]))
        for name in ordered:
            if not name or name == "NATIVE_APP":
                continue
            try:
                driver.switch_context(name)
                value = driver.execute(observe)
                if matches(value):
                    remembered[key] = name
                    return name
            except Exception:
                continue
        return None

    return wait(choose, timeout, f"No inspectable {'standalone' if standalone else 'Safari'} context for {origin}")


def visit(driver, fixture, route):
    native(driver)
    mobile(driver, "activateApp", bundleId="com.apple.mobilesafari")
    # Appium's native-context URL command uses simctl to open Safari. This also
    # recovers from a preceding case that failed while a native sheet was open.
    url = f"{fixture.base_url}/?profile={fixture.profile_id}#{route}"
    driver.command("POST", "/url", {"url": url})
    web(driver, fixture.base_url, standalone=False, expected_url=url)
    # Same-URL/hash navigation can retain the existing document and its modal.
    # Refresh the exact selected tab, then prove a new document actually loaded.
    driver.command("POST", "/url", {"url": url})
    previous_document = driver.execute("return performance.timeOrigin;")
    require(isinstance(previous_document, (int, float)) and not isinstance(previous_document, bool)
            and math.isfinite(previous_document) and previous_document > 0,
            f"Cannot observe the document before refreshing {route}: {previous_document!r}")
    driver.command("POST", "/refresh", {})
    wait(lambda: driver.execute("return performance.timeOrigin !== arguments[0] && location.href === arguments[1] "
                                "&& document.readyState === 'complete' && !!document.querySelector('#main h1');",
                                [previous_document, url]),
         message=f"A fresh document did not load at {url} after WebDriver refresh (previous timeOrigin={previous_document})")


def css(driver, selector):
    return driver.find("css selector", selector)


def click(driver, selector):
    element = wait(lambda: css(driver, selector), message=f"Missing control: {selector}")
    driver.click(element)


def text(driver, selector):
    return driver.execute("const e=document.querySelector(arguments[0]); return e && e.textContent.trim();", [selector])


def bounds(driver, selector):
    """Intersect Safari client rectangles with the visible viewport and clipping ancestors.

    iOS WebKit reports these client rectangles relative to the visual viewport.
    Its offsetTop/Left describe layout-to-visual panning, not this rectangle's origin.
    Keep that pan as diagnostics instead of adding it a second time to the clip.
    """
    return driver.execute("""
      const e=document.querySelector(arguments[0]); if(!e) return null;
      const r=e.getBoundingClientRect(), v=visualViewport;
      const viewport={left:0,top:0,
        width:v ? v.width : innerWidth,height:v ? v.height : innerHeight};
      const pan={left:v ? v.offsetLeft : 0,top:v ? v.offsetTop : 0};
      viewport.right=viewport.left+viewport.width; viewport.bottom=viewport.top+viewport.height;
      const rect={left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height};
      let visible={left:Math.max(r.left,viewport.left),top:Math.max(r.top,viewport.top),
        right:Math.min(r.right,viewport.right),bottom:Math.min(r.bottom,viewport.bottom)};
      let shown=true;
      for(let a=e;a;a=a.parentElement) {
        const s=getComputedStyle(a); if(s.display==='none'||s.visibility==='hidden'||+s.opacity===0) shown=false;
        if(a!==e) {
          const q=a.getBoundingClientRect();
          if(/hidden|clip|auto|scroll/.test(s.overflowX)) { visible.left=Math.max(visible.left,q.left+a.clientLeft); visible.right=Math.min(visible.right,q.left+a.clientLeft+a.clientWidth); }
          if(/hidden|clip|auto|scroll/.test(s.overflowY)) { visible.top=Math.max(visible.top,q.top+a.clientTop); visible.bottom=Math.min(visible.bottom,q.top+a.clientTop+a.clientHeight); }
        }
      }
      return {rect,visible,viewport,pan,shown,clientWidth:e.clientWidth,scrollWidth:e.scrollWidth,
        scrollTop:e.scrollTop,disabled:e.disabled===true};
    """, [selector])


def fully_visible(value, name):
    require(value is not None, f"{name} is absent")
    rect, visible = value["rect"], value["visible"]
    require(value["shown"] and rect["width"] > 0 and rect["height"] > 0, f"{name} has no visible size: {value}")
    require(visible["left"] <= rect["left"] + 1 and visible["top"] <= rect["top"] + 1
            and visible["right"] >= rect["right"] - 1 and visible["bottom"] >= rect["bottom"] - 1,
            f"{name} is clipped or outside the visible viewport: {value}")


def no_page_errors(driver):
    errors = text(driver, "#page-errors")
    require(not errors, f"Deck Lab displayed an application error: {errors}")


def native_element(driver, label, element_type="XCUIElementTypeButton", timeout=15, prefix=False,
                   require_visible=True, webview_only=False):
    """Find one native element by its exact accessible name.

    element_type is one XCUIElementType name, None for any type, or a tuple of
    accepted types: WebKit on iOS 27 exposes an aria-haspopup button as
    XCUIElementTypeOther, so a caller that knows its control is such a button
    opts into (Button, Other) rather than every flow dropping the type filter.
    """
    native(driver)
    quoted = json.dumps(label)
    match = f"name {'BEGINSWITH' if prefix else '=='} {quoted} OR label {'BEGINSWITH' if prefix else '=='} {quoted}"
    types = (element_type,) if isinstance(element_type, str) else tuple(element_type or ())
    require(all(isinstance(name, str) and name.startswith("XCUIElementType") for name in types),
            f"Unrecognized native element type filter: {element_type!r}")
    if len(types) == 1:
        kind = f"type == {json.dumps(types[0])} AND "
    elif types:
        kind = f"type IN {{{', '.join(json.dumps(name) for name in types)}}} AND "
    else:
        kind = ""
    visibility = "visible == 1 AND " if require_visible else ""
    predicate = f"{kind}{visibility}({match})"
    using, selector = "-ios predicate string", predicate
    if webview_only:
        # Native class chains scope descendants without matching Safari chrome
        # with the same label (for example a tab's Close button).
        scoped = (f"{visibility}({match})" if len(types) == 1 else predicate).replace("`", "``")
        using = "-ios class chain"
        selector = f"**/XCUIElementTypeWebView/**/{types[0] if len(types) == 1 else '*'}[`{scoped}`]"
    return wait(lambda: driver.find(using, selector), timeout, f"Native {label!r} control unavailable")


def native_rect(driver, element):
    return driver.command("GET", f"/element/{element}/rect")


def measured_transform(measured, native_box, native_window, label, native_webview=None):
    """Map the current responsive page using one matching accessible control.

    Safari's calibration page can use a different layout viewport (980px), so
    its cached ratio cannot safely be applied to Deck Lab's responsive page.
    Use the complete viewport's width for scale: rounding a small native button
    must not be magnified across a wide iPad. A tall native height may be clipped.
    """
    require(measured is not None, f"Coordinate anchor {label!r} is absent")
    rect, visible = measured["rect"], measured["visible"]
    evidence = {"label": label, "dom": measured, "native": native_box, "native_window": native_window}
    require(measured["shown"] and rect["width"] > 0 and rect["height"] > 0,
            f"Coordinate anchor has no visible size: {evidence}")
    require(visible["left"] <= rect["left"] + 1 and visible["right"] >= rect["right"] - 1
            and visible["bottom"] > visible["top"] and visible["top"] <= rect["top"] + 1,
            f"Coordinate anchor is horizontally clipped or its top is not visible: {evidence}")
    require(all(math.isfinite(native_box[key]) for key in ("x", "y", "width", "height"))
            and native_box["width"] > 0 and native_box["height"] > 0,
            f"Native coordinate anchor has no usable bounds: {evidence}")
    require(native_box["x"] >= native_window["x"] - 1
            and native_box["x"] + native_box["width"] <= native_window["x"] + native_window["width"] + 1,
            f"Native coordinate anchor is horizontally clipped: {evidence}")
    viewport = measured.get("viewport")
    scale = (native_webview["width"] / viewport["width"] if native_webview is not None and viewport
             else native_box["width"] / rect["width"])
    require(math.isfinite(scale) and 0.5 <= scale <= 2,
            f"Implausible native/CSS coordinate scale {scale}: {evidence}")
    offset_x = native_box["x"] - rect["left"] * scale
    if native_webview is not None and viewport is not None:
        offset_x = native_webview["x"] - viewport["left"] * scale
        require(abs(native_box["width"] - rect["width"] * scale) <= 1
                and abs(native_box["x"] - (offset_x + rect["left"] * scale)) <= 1,
                f"Coordinate anchor disagrees with its native WebView scale or position: {evidence}; "
                f"native_webview={native_webview}; scale={scale}")
    transform = {"offsetX": offset_x,
                 "offsetY": native_box["y"] - rect["top"] * scale,
                 "pixelRatioX": scale, "pixelRatioY": scale, "anchor": evidence}
    if native_webview is not None and viewport is not None:
        mapped = {"left": transform["offsetX"] + viewport["left"] * scale,
                  "top": transform["offsetY"] + viewport["top"] * scale,
                  "right": transform["offsetX"] + (viewport["left"] + viewport["width"]) * scale,
                  "bottom": transform["offsetY"] + (viewport["top"] + viewport["height"]) * scale}
        evidence.update(native_webview=native_webview, mapped_viewport=mapped)
        left, right = native_webview["x"], native_webview["x"] + native_webview["width"]
        top = max(native_webview["y"], native_window["y"])
        bottom = min(native_webview["y"] + native_webview["height"], native_window["y"] + native_window["height"])
        require(all(math.isfinite(value) for value in mapped.values())
                and abs(mapped["left"] - left) <= 2 and abs(mapped["right"] - right) <= 2
                and mapped["top"] >= top - 2 and mapped["bottom"] <= bottom + 2,
                f"Coordinate anchor does not map the visible viewport into its native WebView: {evidence}")
    return transform


def anchor_transform(driver, fixture, selector):
    measured = bounds(driver, selector)
    require(measured is not None, f"Coordinate anchor {selector} is absent")
    label = driver.execute("return document.querySelector(arguments[0]).getAttribute('aria-label');", [selector])
    require(label, f"Coordinate anchor {selector} needs an exact accessible label")
    element = native_element(driver, label, webview_only=True)
    native_box = native_rect(driver, element)
    native_window = driver.command("GET", "/window/rect")
    view = driver.find("-ios predicate string", "type == 'XCUIElementTypeWebView' AND visible == 1")
    transform = measured_transform(measured, native_box, native_window, label, native_rect(driver, view))
    web(driver, fixture.base_url, standalone=False)
    after = bounds(driver, selector)
    require(after and all(abs(after["rect"][key] - measured["rect"][key]) <= 2
                          for key in ("left", "top", "width", "height")),
            f"Coordinate anchor moved while measuring: before={measured}, after={after}")
    return transform


def touch(driver, transform, start, end=None, duration=350, hold_ms=0):
    """Send a real finger in native point coordinates; no synthetic DOM events.

    hold_ms rests the finger at the end of a drag before lifting it, so iOS sees
    a drag that stopped rather than a flick, and adds no momentum.
    """
    def point(css_point):
        x = transform["offsetX"] + css_point[0] * transform["pixelRatioX"]
        y = transform["offsetY"] + css_point[1] * transform["pixelRatioY"]
        require(math.isfinite(x) and math.isfinite(y), f"Native gesture has non-finite coordinates: {(x, y)}")
        return {"x": round(x), "y": round(y)}

    start_native = point(start)
    end_native = point(end) if end is not None else start_native
    native(driver)
    window = driver.command("GET", "/window/rect")
    require(all(math.isfinite(window[key]) for key in ("x", "y", "width", "height"))
            and window["width"] > 0 and window["height"] > 0, f"Native gesture has invalid window bounds: {window}")
    for name, endpoint in (("start", start_native), ("end", end_native)):
        require(window["x"] <= endpoint["x"] < window["x"] + window["width"]
                and window["y"] <= endpoint["y"] < window["y"] + window["height"],
                f"Native gesture {name} is outside the native window: {endpoint}; window={window}; transform={transform}")
    actions = [{"type": "pointerMove", "duration": 0, "origin": "viewport", **start_native},
               {"type": "pointerDown", "button": 0}, {"type": "pause", "duration": 60}]
    if end is not None:
        actions.append({"type": "pointerMove", "duration": duration, "origin": "viewport", **end_native})
        if hold_ms:
            actions.append({"type": "pause", "duration": hold_ms})
    actions.append({"type": "pointerUp", "button": 0})
    try:
        driver.command("POST", "/actions", {"actions": [{"type": "pointer", "id": "finger",
                       "parameters": {"pointerType": "touch"}, "actions": actions}]})
    finally:
        driver.command("DELETE", "/actions")
    return {"start": start_native, "end": end_native}


def raw_swipe(driver, start, end, duration=350, hold_ms=0):
    return touch(driver, {"offsetX": 0, "offsetY": 0, "pixelRatioX": 1, "pixelRatioY": 1}, start, end,
                 duration=duration, hold_ms=hold_ms)


def tap_native_rect(driver, rect):
    """One raw native tap, without XCTest's element scroll/activation behavior."""
    return touch(driver, {"offsetX": 0, "offsetY": 0, "pixelRatioX": 1, "pixelRatioY": 1},
                 (rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2))


# A scroll is a slow drag that rests before lifting (no momentum), sized to
# bring the target's top to about SCROLL_AIM_FRACTION of the viewport and never
# more than SCROLL_MAX_FRACTION of the WebView in one gesture. iOS ignores the
# first few points of a drag (touch slop), so each drag is that much longer.
SCROLL_AIM_FRACTION = 0.22
SCROLL_MAX_FRACTION = 0.45
SCROLL_MIN_POINTS = 48
SCROLL_SLOP_POINTS = 12
SCROLL_DURATION_MS = 900
SCROLL_HOLD_MS = 250


def scroll_clear_band(driver, x):
    """Observe the fixed or sticky bars at the top and bottom of the viewport in one column.

    A drag must start and end on scrolling content: a finger put down on a fixed
    bottom bar (an action bar, the editor's bar, the tab bar) does not scroll
    the page. The bars are found by what is actually drawn there, not by class.
    """
    value = driver.execute("""
      const x=arguments[0], v=visualViewport, H=v ? v.height : innerHeight;
      const pinned=(node)=>{ for(let a=node;a && a.nodeType===1;a=a.parentElement) {
        const p=getComputedStyle(a).position; if(p==='fixed'||p==='sticky') return a; } return null; };
      let top=0, bottom=H; const overlays=[];
      const look=(ys, edge)=>{ for(const y of ys) {
        const f=pinned(document.elementFromPoint(x,y)); if(!f) continue;
        const r=f.getBoundingClientRect();
        if(edge==='top' ? r.bottom>H*0.5 : r.top<H*0.5) continue;
        if(edge==='top') top=Math.max(top,r.bottom); else bottom=Math.min(bottom,r.top);
        overlays.push({edge,y,tag:f.tagName,class:f.getAttribute('class'),top:r.top,bottom:r.bottom});
      } };
      look([1,H*0.05,H*0.1,H*0.15],'top');
      look([H-1,H*0.95,H*0.9,H*0.85,H*0.8,H*0.75],'bottom');
      return {top,bottom,height:H,overlays};
    """, [x])
    if not isinstance(value, dict) or not all(isinstance(value.get(key), (int, float)) for key in ("top", "bottom")):
        return None
    return value


def scroll_upwards(measured):
    """Which way to move the content to reveal a target that is not hittable.

    bounds() ignores overlays, so a target inside the viewport may still be
    covered: a target in the lower half is then under the bottom bars (move the
    content up) and one in the upper half under the top bar (move it down).
    """
    rect, visible, viewport = measured["rect"], measured["visible"], measured.get("viewport") or {}
    if rect["top"] < visible["top"] - 1:
        return False
    if rect["bottom"] > visible["bottom"] + 1:
        return True
    height = viewport.get("height") or visible["bottom"]
    return (rect["top"] + rect["bottom"]) / 2 > height / 2


def native_scroll_towards(driver, fixture, measured, upwards, standalone=False):
    """Scroll the observed target's column through the native WebView with one slow drag.

    upwards moves the content up (the finger drags up) to reveal what is below.
    The drag is sized to the distance still to close, kept between the fixed
    bars, and rests before lifting so the page stops where it was put.
    """
    viewport, rect = measured["viewport"], measured["rect"]
    require(viewport["width"] > 0, f"Native target has no measurable viewport width: {measured}")
    centre = (rect["left"] + rect["right"]) / 2 - viewport["left"]
    band = scroll_clear_band(driver, max(1, min(viewport["width"] - 1, centre)))
    native(driver)
    view = driver.find("-ios predicate string", "type == 'XCUIElementTypeWebView' AND visible == 1")
    content, window = native_rect(driver, view), driver.command("GET", "/window/rect")
    left, right = max(content["x"], window["x"]), min(content["x"] + content["width"], window["x"] + window["width"])
    top, bottom = max(content["y"], window["y"]), min(content["y"] + content["height"], window["y"] + window["height"])
    require(right - left > 40 and bottom - top > 80, f"No native WebView scroll path: content={content}, window={window}")
    scale = content["width"] / viewport["width"]
    require(math.isfinite(scale) and 0.5 <= scale <= 2,
            f"Implausible native/CSS scale for a scroll: content={content}, viewport={viewport}")
    # Follow the target's column; a fixed fraction can scroll an iPad side panel.
    x = max(left + 12, min(right - 12, content["x"] + content["width"] * centre / viewport["width"]))
    height = viewport.get("height") or (band or {}).get("height") or (bottom - top) / scale
    clear = band or {"top": 0, "bottom": height}
    # CSS y=0 sits somewhere in the WebView's obscured insets (iOS 27's WebView is
    # full-screen; the page starts under the status bar), so bound the band for
    # any split of that slack rather than assuming CSS 0 is the WebView's top.
    slack = max(0, content["height"] - height * scale)
    clear_top = max(top, content["y"] + slack + clear["top"] * scale) + 12
    clear_bottom = min(bottom, content["y"] + clear["bottom"] * scale) - 12
    require(clear_bottom - clear_top >= 60,
            f"No scrolling content between the fixed bars for a native drag: band={band}, content={content}, window={window}")
    aim = max(height * SCROLL_AIM_FRACTION, clear["top"] + 8)
    needed = (rect["top"] - aim) if upwards else (aim - rect["top"])
    distance = max(SCROLL_MIN_POINTS, needed * scale) + SCROLL_SLOP_POINTS
    distance = min(distance, (bottom - top) * SCROLL_MAX_FRACTION, clear_bottom - clear_top)
    middle = (clear_top + clear_bottom) / 2
    y1, y2 = middle + distance / 2, middle - distance / 2
    if not upwards:
        y1, y2 = y2, y1
    gesture = dict(raw_swipe(driver, (x, y1), (x, y2), duration=SCROLL_DURATION_MS, hold_ms=SCROLL_HOLD_MS) or {})
    gesture["plan"] = {"upwards": upwards, "clear_band": band, "aim_css_top": aim, "needed_css": needed,
                       "distance_points": distance, "duration_ms": SCROLL_DURATION_MS, "hold_ms": SCROLL_HOLD_MS}
    web(driver, fixture.base_url, standalone=standalone)
    time.sleep(0.2)
    return gesture


def visible_button_hit_point(driver, selector, visible):
    """Observe a bounded set of points; fixed overlays can cover valid bounds."""
    return driver.execute("""
      const button=document.querySelector(arguments[0]), v=arguments[1];
      const samples=[]; let point=null;
      for(const fy of [0.5,0.15,0.85]) for(const fx of [0.5,0.2,0.8]) {
        const x=v.left+(v.right-v.left)*fx, y=v.top+(v.bottom-v.top)*fy;
        const hit=document.elementFromPoint(x,y);
        const onTarget=!!button && !!hit && (hit===button || button.contains(hit));
        samples.push({x,y,on_target:onTarget,hit:hit ? {tag:hit.tagName,
          label:hit.getAttribute('aria-label'),class:hit.getAttribute('class')} : null});
        if(onTarget && !point) point={x,y};
      }
      return {point,samples};
    """, [selector, visible])


def tap_native_visible_part(driver, fixture, selector, standalone=False, element_type="XCUIElementTypeButton"):
    """Reveal a real native button and tap its visible area exactly once.

    element_type narrows the native lookup (see native_element); a caller whose
    control is an aria-haspopup button passes (Button, Other).
    """
    preparation = []
    for attempt in range(9):
        measured = bounds(driver, selector)
        require(measured is not None and measured["shown"] and not measured["disabled"],
                f"Native target is absent, hidden or disabled: {selector}; {measured}")
        rect, visible = measured["rect"], measured["visible"]
        require(rect["width"] > 0 and rect["height"] > 0
                and visible["left"] <= rect["left"] + 1 and visible["right"] >= rect["right"] - 1,
                f"Native target has zero size or horizontal clipping: {selector}; {measured}")
        hit_test = None
        if visible["top"] <= rect["top"] + 1 and visible["bottom"] - visible["top"] >= min(32, rect["height"]):
            hit_test = visible_button_hit_point(driver, selector, visible)
            if hit_test["point"] is not None:
                break
        require(attempt < 8, f"Native target did not become tappable after eight scrolls: {selector}; {measured}")
        gesture = native_scroll_towards(driver, fixture, measured, upwards=scroll_upwards(measured),
                                        standalone=standalone)
        preparation.append({"before": measured, "hit_test": hit_test, "native_gesture": gesture})
    label = driver.execute("""
      const b=document.querySelector(arguments[0]);
      return (b.getAttribute('aria-label')||b.textContent).replace(/\\s+/g,' ').trim();
    """, [selector])
    require(label, f"Native target has no observed accessible label: {selector}")
    button = native_element(driver, label, element_type=element_type, require_visible=False, webview_only=True)
    require(driver.command("GET", f"/element/{button}/enabled") is True, f"Native target {label!r} is disabled")
    rect = native_rect(driver, button)
    window = driver.command("GET", "/window/rect")
    view = driver.find("-ios predicate string", "type == 'XCUIElementTypeWebView' AND visible == 1")
    transform = measured_transform(measured, rect, window, label, native_rect(driver, view))
    point = hit_test["point"]
    gesture = touch(driver, transform, (point["x"], point["y"]))
    web(driver, fixture.base_url, standalone=standalone)
    return {"observed_label": label, "dom": measured, "native": rect,
            "coordinate_transform": transform, "hit_test": hit_test,
            "native_tap": gesture, "native_preparation": preparation}


def _same_place(before, after):
    return all(abs(after["rect"][key] - before["rect"][key]) <= 2 for key in ("left", "top", "width", "height"))


def focus_native_field(driver, fixture, selector):
    """Reveal an actual native text field, then focus it with one raw finger.

    Revealed means hittable: inside the visible viewport, and what is drawn at
    the field is the field, not a fixed bar over it. The tap goes to the
    hit-tested point, mapped through the native field, with the bounds and hit
    test taken right before it; a covered field fails instead of tapping through.
    """
    label = driver.execute("return document.querySelector(arguments[0]).getAttribute('aria-label');", [selector])
    require(label, f"Native field {selector} needs an exact accessible label")
    swipes = []
    for attempt in range(9):
        measured = bounds(driver, selector)
        require(measured is not None and measured["shown"], f"Native field {label!r} is absent or hidden: {measured}")
        rect, visible = measured["rect"], measured["visible"]
        require(visible["left"] <= rect["left"] + 1 and visible["right"] >= rect["right"] - 1,
                f"Native text field is horizontally clipped: {measured}")
        hit_test = None
        try:
            fully_visible(measured, f"Native text field {label!r} before focus")
        except AssertionError:
            pass
        else:
            hit_test = visible_button_hit_point(driver, selector, visible)
            if hit_test["point"] is not None:
                break
        require(attempt < 8, f"Native text field not revealed and hittable after eight native scroll gestures: "
                             f"{measured}; hit_test={hit_test}; swipes={swipes}")
        gesture = native_scroll_towards(driver, fixture, measured, scroll_upwards(measured))
        swipes.append({"before": measured, "hit_test": hit_test, "native_gesture": gesture})
    previous = measured
    for settle in range(3):
        field = native_element(driver, label, element_type="XCUIElementTypeTextField",
                               require_visible=False, webview_only=True)
        rect = native_rect(driver, field)
        window = driver.command("GET", "/window/rect")
        view = driver.find("-ios predicate string", "type == 'XCUIElementTypeWebView' AND visible == 1")
        view_rect = native_rect(driver, view)
        require(rect["width"] > 0 and rect["height"] > 0 and rect["x"] >= window["x"]
                and rect["y"] >= window["y"] and rect["x"] + rect["width"] <= window["x"] + window["width"]
                and rect["y"] + rect["height"] <= window["y"] + window["height"],
                f"Native text field is outside the screen after revealing it: label={label}, field={rect}, window={window}")
        web(driver, fixture.base_url, standalone=False)
        measured = bounds(driver, selector)
        fully_visible(measured, f"Native text field {label!r} before focus")
        hit_test = visible_button_hit_point(driver, selector, measured["visible"])
        require(hit_test["point"] is not None,
                f"Native text field {label!r} is covered at its tap point; not tapping through the overlay: "
                f"dom={measured}; samples={hit_test.get('samples')}")
        if _same_place(previous, measured):
            break
        # Safari's toolbar can collapse during the native round trip; map the
        # tap only from a native rectangle read while the field stood still.
        require(settle < 2, f"Native text field {label!r} kept moving while measuring: before={previous}, after={measured}")
        previous = measured
    transform = measured_transform(measured, rect, window, label, view_rect)
    point = hit_test["point"]
    # Do not use web-context element.click: nativeWebTap can retain a stale
    # viewport translation after Safari auto-scrolls an off-screen input.
    gesture = touch(driver, transform, (point["x"], point["y"]))
    return {"label": label, "native": rect, "dom": measured, "hit_test": hit_test,
            "coordinate_transform": transform, "native_tap": gesture, "native_scrolls": swipes}


def choose_native_profile(driver, fixture):
    """Tap the native chooser button whose full label comes from this page."""
    name = getattr(fixture, "profile_name", "Matt")
    label = driver.execute("""
      const b=[...document.querySelectorAll('.who-button')].find(e=>e.querySelector('.who-name')?.textContent.trim()===arguments[0]);
      return b && [b.querySelector('.who-name')?.textContent,b.querySelector('.who-sub')?.textContent]
        .filter(Boolean).join(' ').replace(/\\s+/g,' ').trim();
    """, [name])
    require(label, f"Standalone chooser has no button for fixture profile {name!r}")
    button = native_element(driver, label, webview_only=True)
    rect = native_rect(driver, button)
    window = driver.command("GET", "/window/rect")
    x, y = rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2
    require(rect["width"] > 0 and rect["height"] > 0
            and window["x"] < x < window["x"] + window["width"]
            and window["y"] < y < window["y"] + window["height"],
            f"Standalone native profile button has no visible tap point: label={label}, rect={rect}, window={window}")
    gesture = tap_native_rect(driver, rect)
    web(driver, fixture.base_url, standalone=True)
    return {"observed_label": label, "native": rect, "native_tap": gesture}


def tap_native_button(driver, fixture, selector, standalone=False):
    measured = bounds(driver, selector)
    fully_visible(measured, f"Native action {selector}")
    require(not measured["disabled"], f"Native action is disabled: {selector}; {measured}")
    label = driver.execute("""
      const b=document.querySelector(arguments[0]);
      return (b.getAttribute('aria-label')||b.textContent).replace(/\\s+/g,' ').trim();
    """, [selector])
    require(label, f"Native action has no observed accessible label: {selector}")
    button = native_element(driver, label, webview_only=True)
    require(driver.command("GET", f"/element/{button}/enabled") is True,
            f"Native action {label!r} is not enabled")
    rect = native_rect(driver, button)
    gesture = tap_native_rect(driver, rect)
    web(driver, fixture.base_url, standalone=standalone)
    return {"observed_label": label, "dom": measured, "native": rect, "native_tap": gesture}


def native_home_screen_ready(driver, timeout=45):
    """Wait for Safari's real Add sheet metadata and enabled Add control."""
    native(driver)
    observed = {}
    predicate = "type == 'XCUIElementTypeTextField' AND visible == 1"

    def ready():
        button = driver.find("-ios predicate string", "type == 'XCUIElementTypeButton' AND visible == 1 AND (name == 'Add' OR label == 'Add')")
        observed["add_enabled"] = driver.command("GET", f"/element/{button}/enabled")
        fields = driver.command("POST", "/elements", {"using": "-ios predicate string", "value": predicate})
        names = []
        for field in fields:
            element = field.get("element-6066-11e4-a52e-4f735466cecf", field.get("ELEMENT"))
            value = driver.command("GET", f"/element/{element}/attribute/value")
            if isinstance(value, str) and value.strip():
                names.append(value.strip())
        observed["visible_text_fields"] = names
        if observed["add_enabled"] is True and len(names) == 1:
            return {"button": button, "icon_name": names[0], "native_add": native_rect(driver, button)}
        return None

    try:
        return wait(ready, timeout, "Add to Home Screen did not load its name and enable Add")
    except AssertionError as error:
        raise AssertionError(f"{error}; native_add_state={observed}") from error


def wait_native_add_dismissed(driver):
    native(driver)
    predicate = "type == 'XCUIElementTypeButton' AND visible == 1 AND (name == 'Add' OR label == 'Add')"
    wait(lambda: not driver.command("POST", "/elements", {"using": "-ios predicate string", "value": predicate}),
         message="Native Add to Home Screen sheet did not dismiss after tapping enabled Add")


def home_screen_state(source):
    """Read actual SpringBoard pages and icon bounds from its native tree."""
    root = ElementTree.fromstring(source)
    apps = [element for element in root.iter()
            if element.tag == "XCUIElementTypeApplication" and element.get("bundleId") == "com.apple.springboard"]
    require(len(apps) == 1, "Native Home Screen navigation requires the observed SpringBoard application")
    app = apps[0]
    pages = [element for element in app.iter()
             if element.tag == "XCUIElementTypePageIndicator" and element.get("visible") == "true"]
    require(len(pages) <= 1, "Home Screen has ambiguous native page indicators")
    current, total = 1, 1
    if pages:
        value = pages[0].get("value", "")
        match = re.fullmatch(r"Page (\d+) of (\d+)", value)
        require(match is not None, f"Unrecognized native Home Screen page indicator: {value!r}")
        current, total = map(int, match.groups())
    require(1 <= current <= total <= 10, f"Native Home Screen page count is outside this bounded test: {current}/{total}")
    icons = []
    for element in app.iter():
        if (element.tag != "XCUIElementTypeIcon" or element.get("visible") != "true"
                or element.get("accessible") != "true" or not element.get("name")):
            continue
        rect = {key: float(element.get(key, "0")) for key in ("x", "y", "width", "height")}
        if rect["width"] > 0 and rect["height"] > 0:
            icons.append({"name": element.get("name"), "label": element.get("label"), "rect": rect})
    return {"page": current, "total": total, "icons": icons}


def launch_home_screen_icon(driver, name):
    """Search only observed Home Screen pages with genuine native swipes."""
    native(driver)

    def snapshot():
        return home_screen_state(driver.command("GET", "/source"))

    state = wait(snapshot, timeout=10, message="Native SpringBoard Home Screen did not become ready")
    window = driver.command("GET", "/window/rect")
    visited, swipes, seen = [], [], set()
    # From any starting page, visit earlier pages then later ones. Crossing an
    # already inspected page is allowed; every finger move is one observed page.
    route = [*range(state["page"] - 1, 0, -1), *range(2, state["total"] + 1)]
    for next_page in [None, *route]:
        if next_page is not None:
            previous = state["page"]
            require(abs(previous - next_page) == 1, f"Home Screen traversal cannot skip a page: {previous}->{next_page}")
            start_fraction, end_fraction = (0.75, 0.25) if next_page > previous else (0.25, 0.75)
            gesture = raw_swipe(driver,
                (window["x"] + window["width"] * start_fraction, window["y"] + window["height"] * 0.55),
                (window["x"] + window["width"] * end_fraction, window["y"] + window["height"] * 0.55))

            def arrived():
                observed = snapshot()
                return observed if observed["page"] == next_page else None

            state = wait(arrived, timeout=10,
                         message=f"Native Home Screen swipe did not move page {previous} to {next_page}")
            swipes.append({"from": previous, "to": next_page, "native_gesture": gesture})
        visited.append({"page": state["page"], "total": state["total"],
                        "visible_icons": [icon["name"] for icon in state["icons"]]})
        seen.add(state["page"])
        matches = [icon for icon in state["icons"] if name in (icon["name"], icon["label"])]
        require(len(matches) <= 1, f"Several visible native Home Screen icons match {name!r}: {matches}")
        if matches:
            icon = native_element(driver, name, element_type="XCUIElementTypeIcon", timeout=5)
            rect = native_rect(driver, icon)
            require(rect["width"] > 0 and rect["height"] > 0, f"Installed native icon has no visible bounds: {rect}")
            # SpringBoard can expose portrait child-window AX rectangles while
            # the iPad scene is landscape. Let XCTest hit the exact native icon;
            # retain its rectangle as diagnostics rather than touch coordinates.
            driver.click(icon)
            return {"name": name, "pages_seen": visited, "native_swipes": swipes,
                    "icon_rect": rect, "native_icon_click": {"element": icon, "observed_name": name}}
        if len(seen) == state["total"]:
            break
    raise AssertionError(f"Installed native Home Screen icon {name!r} absent on all observed pages: {visited}")


def start_input_trace(driver):
    """Observe genuine input/viewport events; do not alter their propagation."""
    driver.execute("""
      if(window.__decklabSafariTrace) return;
      const trace=window.__decklabSafariTrace=[];
      const observe=(event)=>{
        const target=event.target, button=target.closest && target.closest('button');
        const save=document.querySelector('.bar-save'), r=save && save.getBoundingClientRect(), v=visualViewport;
        trace.push({event:event.type,trusted:event.isTrusted,time:performance.now(),
          target:target.tagName||'visualViewport',label:target.getAttribute && target.getAttribute('aria-label'),
          button:button && (button.getAttribute('aria-label')||button.textContent.trim()),
          clientX:event.clientX,clientY:event.clientY,
          active:document.activeElement && document.activeElement.getAttribute('aria-label'),
          save:save && {disabled:save.disabled,busy:save.dataset.busy||null,top:r.top,bottom:r.bottom,
            dirty:!!save.querySelector('.dot:not([hidden])')},
          viewport:v && {height:v.height,offsetTop:v.offsetTop,scale:v.scale}});
        if(trace.length>120) trace.shift();
      };
      for(const name of ['pointerdown','pointerup','pointercancel','click','focusin','focusout','input','change'])
        document.addEventListener(name,observe,{capture:true,passive:true});
      if(visualViewport) for(const name of ['resize','scroll']) visualViewport.addEventListener(name,observe,{passive:true});
    """)


def read_input_trace(driver):
    return driver.execute("""
      const save=document.querySelector('.bar-save'), v=visualViewport;
      return {events:window.__decklabSafariTrace||[],toast:document.querySelector('#toast')?.textContent,
        pageErrors:document.querySelector('#page-errors')?.textContent,
        save:save && {disabled:save.disabled,busy:save.dataset.busy||null,
          dirty:!!save.querySelector('.dot:not([hidden])'),
          checking:!![...document.querySelectorAll('.bar-checking')].find(e=>!e.hidden)},
        active:document.activeElement?.getAttribute('aria-label'),
        viewport:v && {height:v.height,offsetTop:v.offsetTop,scale:v.scale}};
    """)
