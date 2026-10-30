# Safari Simulator regressions (E11-S29)

Run this suite on Matt's MacBook to check the actual Deck Lab web assets in
Safari on iPhone and iPad Simulators. It uses Appium's XCUITest driver so tests
can operate Safari's native controls, the software keyboard and touch gestures.
The Python client uses the standard library; Appium and XCUITest are the only
additional test packages.

For the prepared Windows PC and MacBook, use the [connection and run workflow](MAC-WORKFLOW.md):
SSH setup, transferring committed changes, running the suite and copying results.

**Validated on the Mac on 2026-10-15:** all 60 checks passed across the six
configurations on Xcode 27.0 / iOS 27.0. The [acceptance evidence](EVIDENCE.md)
records the clean source revision, exact models, runtime, results and verified
cleanup. E11-S29 is built. E2-S22 retains the remaining physical hardware and
touch-usability checks separately.

## First setup on the Mac

1. Clone this repository and open Terminal in its root. Install Python 3.11 or
   later and Git if needed. This suite does not need PostgreSQL, a Deck Lab
   production config, the collection, Scryfall downloads or Forge.
2. Install the full **Xcode 26 or later** application, open it once, accept its licence and
   finish first-launch components. Xcode 26.0 requires macOS 15.6 or later; later
   Xcode versions have their own requirements in [Apple's compatibility
   table](https://developer.apple.com/xcode/system-requirements/). The standalone
   Command Line Tools package alone does not include iOS Simulator runtimes.
   Select the installation you intend to use:

   ```sh
   sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
   sudo xcodebuild -runFirstLaunch
   xcodebuild -version
   ```

3. In Xcode's Settings, Components, install a compatible **iOS 26 or later** Simulator runtime.
   Depending on the Xcode version, this pane is named Platforms. iPhone 17 Pro
   requires the iOS 26 generation of simulator device definitions/runtime; do not
   substitute a resized older iPhone. Follow [Apple's runtime installation
   instructions](https://developer.apple.com/documentation/xcode/downloading-and-installing-additional-xcode-components).
   The accepted run uses iOS 27.0. List what this Mac can actually run:

   ```sh
   xcrun simctl list runtimes --json
   xcrun simctl list devicetypes --json
   xcrun simctl list devices available --json
   ```

   Ensure the device types include iPhone 15 Pro, iPhone 17 Pro and the intended
   11-inch iPad Air. The default prefers **iPad Air 11-inch (M2)**, otherwise the
   first compatible 11-inch Air model by name. The runner records the model it
   selects. Use `--ipad-model` to require a particular exact 11-inch iPad name.
   M2 hardware can be an Air or a fourth-generation Pro; the suite default does
   not identify the physical iPad used for E2-S22. To match it, select that device's
   exact type from this Mac's list.
   There is no need to create personal Simulator devices: the runner selects from
   Xcode's device type definitions and creates its own clean devices.
4. Install **Node 24.14.0**, including **npm 11.9.0**, from [Node's release
   archive](https://nodejs.org/en/download/archive/v24.14.0). If `nvm` is already
   installed, `nvm install` and `nvm use` from `decklab/safari` read `.nvmrc`.
   Then, from the repository root:

   ```sh
   bash decklab/safari/setup.sh
   python3 -m decklab.safari --check
   ```

`setup.sh` installs the exact dependency graph in `package-lock.json` locally
under `decklab/safari/node_modules`, runs XCUITest's doctor and prints available
runtimes and device types. It refuses to install anything on Windows or Linux.
The pins are **Appium 3.8.0** and **XCUITest 12.22.7**. Both require the Appium 3
Node/npm range satisfied by the Node/npm versions above; driver 10 and later requires
Appium 3, and iOS 27 is fully supported from driver 11.1.2 ([driver requirements](https://appium.github.io/appium-xcuitest-driver/12.22/getting-started/system-requirements/),
[Appium requirements](https://appium.io/docs/en/3.4/guides/migrating-2-to-3/)).
`package.json`'s `overrides` (2026-10-26) lift vulnerable transitive packages to patched
versions in the same major, clearing GitHub's Dependabot alerts outside the driver. They don't
reach the copies inside `appium-xcuitest-driver`: driver 10 shipped its own
`npm-shrinkwrap.json`, and driver 12 bundles its dependencies instead. The move to 12.22.7
(2026-10-30) cleared the last alert (`qs` in driver 10's shrinkwrap), and
`npm audit --package-lock-only` in `decklab/safari` found nothing left. Driver 11's and 12's
breaking changes (removed capabilities, driver methods and the CommonJS entry) touch nothing
the suite uses. Keep an override's version no older than a version a package pins exactly
(`npm view <package>@<version> dependencies`).
Do not update packages globally to repair a local run. Repeat `setup.sh` after a
pull changes the lockfile. Changing Xcode or a runtime also needs a new report.

Matt's Mac was prepared on 2026-10-15 under `~/DeckLabSafari`, with the checkout
in `source-1b39515` and a `run-safari` wrapper that selects its private Python
3.14.8 and Node 24.14.0 installations without changing system Python or shell
profiles. On that Mac, the equivalent commands are:

```sh
~/DeckLabSafari/run-safari --check
~/DeckLabSafari/run-safari
```

The wrapper runs the checkout's current revision. Its preflight report records
the interpreter path and version as well as Xcode, Appium and the selected
runtime. Simulator runtime installation is separate from the tooling setup.

## Run after pulling changes

From the repository root:

```sh
python3 -m decklab.safari
```

The default matrix is iPhone 15 Pro, iPhone 17 Pro and an 11-inch iPad, each in
portrait and landscape. Runs are sequential. The runner creates fresh disposable
Simulators, starts its own loopback fixture server and local Appium server, and
removes only the Simulators it created when finished. Existing personal Simulator
data is not erased. Leave this Terminal running until cleanup completes.

The runner boots each device with `simctl` and uses Appium's `isHeadless` mode,
so it does not try to open the classic `Simulator.app` removed in Xcode 27.
Safari, gestures, the software keyboard and native sheets still run inside iOS;
screenshots capture that device. Close any classic Simulator UI before starting
the suite: preflight refuses it because Appium's headless startup can close
classic Simulator windows. Xcode 27's Device Hub does not need to be closed.
Fresh devices allow up to 60 seconds for Safari's Web Inspector to connect;
Appium's five-second default was too short during the first Mac validation.

Useful options:

```sh
# Check tools and list the selected matrix without starting Safari sessions.
python3 -m decklab.safari --check

# Require a particular installed runtime and exact iPad model name.
python3 -m decklab.safari --runtime 27.0 --ipad-model 'iPad Air 11-inch (M2)'

# Keep the report in a chosen new results directory.
python3 -m decklab.safari --output /tmp/decklab-safari-results
```

Copy the exact iPad name from `simctl list devicetypes`; the example spelling must
exist on this Mac. An unavailable model/runtime remains an explicit unavailable
matrix row. It never becomes a pass or another model's result. `--runtime` makes
repeat runs comparable when several runtimes are installed.

Exit codes: **0** means all six configurations passed (or all six are ready for
`--check`); **1** means a test assertion or Simulator session failed; **2** means
prerequisites, an unavailable configuration or server startup prevented complete
coverage; **130** means interrupted. An otherwise passing partial matrix exits 2.

Ctrl+C, or SIGINT sent to the CLI process, writes the interrupted report and
cleans up its own resources. This also works when a noninteractive shell passed
an ignored SIGINT disposition to the process. Let cleanup finish before starting
another run.

## What the run exercises

- Receipt inspection: navigation and hint within the initial visible viewport,
  image dimensions and horizontal overflow; native swipes from the image and its
  margin advance exactly once, while vertical scrolling keeps the same card.
- Editor (Quick edit on phones, full editor on the iPad): show the real simulated
  software keyboard, reach Save, persist the edit and verify History's actor.
- Card viewer swipes; Safari's native Share and Add to Home Screen flow; opening
  the installed standalone page and checking visible bounds and safe areas.
- Page version changes: detect a stale page and use its update action to load the
  new version.

Layout assertions measure rendered bounds against the visible viewport. Native
UI steps switch to XCUITest's native context and touch input; they do not dispatch
JavaScript swipe events or replace the Share sheet with a web imitation. Safari
automation uses `browserName=safari`, `appium:automationName=XCUITest` and the
explicit Simulator UDID. Keyboard capabilities disable the hardware keyboard and
force the software keyboard ([capabilities](https://appium.github.io/appium-xcuitest-driver/12.22/reference/capabilities/)).
See the [gesture guide](https://appium.github.io/appium-xcuitest-driver/12.22/guides/gestures/)
and [native command reference](https://appium.github.io/appium-xcuitest-driver/12.22/reference/execute-methods/)
when a new Xcode release changes controls or coordinates.

Visits refresh the selected visible Safari tab and verify a new document loaded.
Page controls are scoped to the native WebView. Share waits for stable native
layout before acting, and Home Screen launch clicks the installed native icon
so UIKit handles scene rotation. The independent version case starts a fresh
Safari process, then waits for the real 30-second version poll and taps Reload;
its report records that setup. Home Screen launch and safe areas are separate
cases.

## Isolation and results

The fixture server serves the checkout's web assets and the actual Deck Lab
HTTP/API handlers over synthetic data. Its FileInventory backend adds fixture-only
in-memory deck history, so editor persistence and attribution use the real API
without PostgreSQL. Its mutable state lives only for the test run. It does not
run the production server startup, load `decklab/config.json`, open the household database, reach the household
server on port 8642, or import family data. Its control endpoints apply only to
its own disposable fixture state. Appium binds to loopback and uses the local
pinned packages with `APPIUM_HOME` removed, following [Appium's project dependency
discovery](https://appium.io/docs/en/3.4/guides/managing-exts/).

By default, evidence is written beneath `decklab/data/safari/<UTC-time>-<id>/`:

- `report.json` and `report.md`: source revision and dirty state, host/Xcode and
  package versions, exact model and runtime, orientation, assertions, errors and
  unavailable configurations.
- `appium.log`: driver, Safari remote-debugging and WebDriverAgent diagnostics.
- Per-configuration folders: command and fixture logs and failure screenshots, page source
  and available contexts when they can be collected.

Read both the run summary and any unavailable rows before recording coverage.
Commit source changes before collecting acceptance evidence so the recorded
revision identifies what was exercised. Retain the complete run directory when
reporting a failure. Do not label `--check` or the Windows unit tests as Safari
coverage.

## Harness tests

The runner, fixture and interaction tests also run without starting Simulators:

```sh
python3 -m unittest discover -s decklab/tests -t . -p 'test_safari_*.py'
```

The 100-test harness subset passes on the prepared Mac. The focused Windows
validation passes 246 tests, including the editor, receipt, device-layout and web
contracts. The native acceptance results are recorded separately in
[EVIDENCE.md](EVIDENCE.md).

## Setup failures

| Symptom | Next step |
| --- | --- |
| Not macOS | Run on the MacBook; Windows can check the runner's unit tests only. |
| Xcode licence/first-launch error | Open the selected full Xcode once, finish setup, then repeat `xcodebuild -version`. |
| Wrong Node/npm or missing Appium | Select Node 24.14.0/npm 11.9.0 and rerun `bash decklab/safari/setup.sh`. |
| Driver missing despite a global installation | Use this repository's setup; Appium starts inside `decklab/safari` with its own pinned driver. |
| No compatible model/runtime | Install the iOS runtime in Xcode, verify `simctl` output and the optional exact model/runtime arguments. |
| WDA build or Safari webview connection fails | Inspect `appium.log`, run local `appium driver doctor xcuitest` as shown below, and record the Xcode/runtime versions. |
| Native Share or Home Screen label changed | Inspect the saved native source and screenshot; update the selector and rerun the complete matrix. A failed native step is still a failure. |

For driver diagnostics from the repository root:

```sh
cd decklab/safari
env -u APPIUM_HOME ./node_modules/.bin/appium driver doctor xcuitest
```

Simulator runs do not need a real iPhone's provisioning profile, Developer Mode
or a paid developer account. Physical-device automation has separate [device
preparation](https://appium.github.io/appium-xcuitest-driver/12.22/getting-started/device-setup/)
requirements and is outside this runner.
