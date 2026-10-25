# Safari Simulator acceptance evidence (2026-10-15)

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
