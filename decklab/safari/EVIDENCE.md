# Safari Simulator acceptance evidence (2026-11-05)

E11-S29 passes **60/60 scenario checks** again in one complete six-configuration run
against the P1 redesign (E11-S30), with exit code **0**, no unavailable
configurations, no setup errors and no retries. This is Simulator coverage;
E2-S22's physical-device acceptance remains partial.

- Tested clean source: `368580ae6e23af09786020f027b6861dd6725bdd`.
- Run: `20261105T070328Z-55ca9d`, 07:03:28 to 07:50:29 UTC (47 minutes).
- Host: arm64 macOS 27.0.1 (26A434), Xcode 27.2 (27B52).
- Runtime: iOS 27.0 (24A434), `com.apple.CoreSimulator.SimRuntime.iOS-27-0`.
- Tooling: Python 3.14.8, Node 24.14.0 / npm 11.9.0, Appium 3.8.0,
  XCUITest 12.22.7.

| Actual Simulator model | Orientation | Viewport (CSS px) | Checks | Result |
| --- | --- | --- | --- | --- |
| iPhone 15 Pro | Portrait | 393 x 695 | 10/10 | Passed |
| iPhone 15 Pro | Landscape | 852 x 283 | 10/10 | Passed |
| iPhone 17 Pro | Portrait | 402 x 714 | 10/10 | Passed |
| iPhone 17 Pro | Landscape | 874 x 292 | 10/10 | Passed |
| iPad Air 11-inch (M2) | Portrait | 820 x 1048 | 10/10 | Passed |
| iPad Air 11-inch (M2) | Landscape | 1180 x 688 | 10/10 | Passed |

The [committed JSON summary](evidence/2026-11-05-simulator.json) records every
case's result and time, the measured viewports, the versions, the Home Screen
profile taps (one in every configuration) and the cleanup check.

### What it took to get here

The first runs on 2026-11-05 scored 0/60, then 23/60, 38/60 and 58/60. In order:

1. **The fixture couldn't serve a page on macOS.** Since 2026-10-27 the profile
   config refuses a linked folder above `config.json`, and macOS's temp folder is
   under `/var`, a link to `/private/var`: every `?profile=` page answered 500.
   The fixture now resolves its root (`a6ceacf`).
2. **Xcode updated itself mid-run** (27.0 to 27.2), killing the remaining sessions;
   its first-launch setup then had to be run on the Mac (MAC-WORKFLOW.md).
3. **One real product fault:** on an iPad in landscape, Safari panning the view
   left the editor's Save bar under the keyboard. The lift is now measured from
   the bar itself (`711c660`, `decklab/tests/test_editor_keyboard_pan_ui.py`).
4. **The harness had drifted from the redesign** (`2f57d62`, `74911a4`,
   `368580a`): Receive delivery opens a card with its Inspect button (a tile tap
   ticks it now); native scrolls are slow resting drags kept between the fixed
   bars, mapped through the shell's avatar; a field counts as revealed only when
   nothing covers it; a failed editor case discards its draft; the page's
   scroll lock while a sheet is open no longer counts as a clip; and the Home
   Screen chooser's button is scrolled into view before its tap.
5. **A Simulator that loses its session** (iPhone 15 Pro landscape rebooted once)
   now reruns that configuration once on a fresh device, shown in the report
   (`13879a1`). This run needed no retry.

Receive delivery's phone layout (no card tile before the first scroll, with the
tab bar kept under its action bar) was reviewed and kept as it is (Matt,
2026-11-05).

Every configuration used its own disposable Simulator and synthetic HTTP fixture.
No household server, database or private family data was used. Checks after the
run found no remaining test Simulators, no owned Appium, xcodebuild or runner
processes, no open listeners and a clean source checkout on the Mac. Unit tests:
the Safari harness (134 run, 133 passed, 1 skipped) and the editor keyboard
modules (85 passed) on Windows; the Safari harness on the Mac (134 run, 129
passed, 5 skipped).

Complete raw reports, logs and screenshots are on the Mac under
`~/DeckLabSafari/decklab/decklab/data/safari/20261105T070328Z-55ca9d/` and copied
to the PC under `decklab/data/safari/macbook/20261105T070328Z-55ca9d/` (gitignored).

Raw `report.json` SHA-256:
`e687804049e419d6cb0a558afec8a58cf11785eda29ff70951322a8e23117920`.

## Earlier acceptance (2026-10-15)

E11-S29 passes **60/60 scenario checks** in one complete six-configuration run,
with exit code **0**, no unavailable configurations and no setup or cleanup errors.
This is Simulator coverage; E2-S22's physical-device acceptance remains partial.

- Tested clean source: `62c0dbd8fd21670db2e91645670088da669a0c27`.
- Run: `20261015T051426Z-59b4e5`, 05:14:26 to 05:46:29 UTC (32 minutes).
- Host: arm64 macOS 26.6.2 (25G83), Xcode 27.0 (27A266a).
- Runtime: iOS 27.0 (24A434), `com.apple.CoreSimulator.SimRuntime.iOS-27-0`.
- Tooling: Python 3.14.8, Node 24.14.0 / npm 11.9.0, Appium 3.4.2,
  XCUITest 10.43.0.

| Actual Simulator model | Orientation | Checks | Result |
| --- | --- | --- | --- |
| iPhone 15 Pro | Portrait | 10/10 | Passed |
| iPhone 15 Pro | Landscape | 10/10 | Passed |
| iPhone 17 Pro | Portrait | 10/10 | Passed |
| iPhone 17 Pro | Landscape | 10/10 | Passed |
| iPad Air 11-inch (M2) | Portrait | 10/10 | Passed |
| iPad Air 11-inch (M2) | Landscape | 10/10 | Passed |

The [committed JSON summary](evidence/2026-10-15-simulator.json) records every
case result, measured viewports, software-keyboard/Save bounds, standalone safe
areas, versions and cleanup verification. The iPad model is the selected
Simulator definition; the physical M2 iPad's exact model remains unconfirmed.

Each configuration exercises native orientation; initial receipt heading, Close,
navigation, hint, image size and overflow; image/margin swipes and vertical
scrolling; viewer swipes; keyboard-open Save, persistence and History attribution;
Safari Share/Add to Home Screen, actual icon launch and standalone safe areas;
and the real stale-version poll followed by native Reload and route preservation.
Phones use Quick edit; the iPad uses the full editor. The independent version
case starts a fresh Safari process, as recorded in each result. Home Screen
launch and safe areas are separate cases.

Every configuration used its own disposable Simulator and synthetic HTTP fixture.
No household server, database or private family data was used. Independent
post-run checks confirmed all six test devices deleted, all six fixture listeners
and the owned Appium listener closed, and no owned Appium/xcodebuild processes.
The source remained clean throughout the run. The 246 focused Windows tests pass;
the 100-test Safari harness subset also passes on the Mac.

Complete raw reports, logs and successful keyboard/Share screenshots are retained
on the Mac under `decklab/data/safari/20261015T051426Z-59b4e5/` and copied to the PC
under `decklab/data/safari/macbook/20261015T051426Z-59b4e5/`. These directories are
gitignored. Local copies: [readable report](../data/safari/macbook/20261015T051426Z-59b4e5/report.md),
[raw JSON](../data/safari/macbook/20261015T051426Z-59b4e5/report.json) and
[cleanup verification](../data/safari/macbook/20261015T051426Z-59b4e5/cleanup-verification.json).

Raw `report.json` SHA-256:
`f76eae2dd62c9cf4d9c4c6dd112582540cc729ce0173f1cd78fedc3a69783d91`.

During earlier setup/debug runs, macOS reported guest PosterBoard and MobileCal
process crashes. Their logs identify `launchd_sim` / `SimulatorTrampoline`;
MobileCal hit a background startup watchdog. Those diagnostics are separate from
this accepted Safari run, which completed all checks.
