#!/usr/bin/env bash
# Run explicitly on the MacBook after installing the prerequisites in README.md.
set -euo pipefail

if [[ "$(uname -s)" != Darwin ]]; then
  printf '%s\n' 'Safari Simulator setup requires macOS; nothing was installed.' >&2
  exit 2
fi
cd "$(dirname "$0")"

for tool in git python3 node npm xcodebuild xcrun; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'Missing %s. Follow decklab/safari/README.md, then retry.\n' "$tool" >&2
    exit 2
  fi
done
if [[ "$(node --version)" != v24.14.0 || "$(npm --version)" != 11.9.0 ]]; then
  printf '%s\n' 'Use Node 24.14.0 with npm 11.9.0 (see .nvmrc and README.md).' >&2
  exit 2
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "Python 3.11 or later is required.")'
xcodebuild -version
xcrun --find simctl >/dev/null

# Both dependencies and their transitives come from the committed lockfile.
# Do not use a global Appium installation or another APPIUM_HOME's drivers.
npm ci --include=dev --no-audit --no-fund
env -u APPIUM_HOME ./node_modules/.bin/appium driver doctor xcuitest
xcrun simctl list runtimes
xcrun simctl list devicetypes
printf '\n%s\n' 'Setup finished. From the repository root, run: python3 -m decklab.safari --check'
