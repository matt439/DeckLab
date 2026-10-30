# Running Deck Lab's Safari tests from Windows through the Mac

This is the practical workflow used for E11-S29, verified on **2026-10-15**.
The Windows PC holds the main checkout. SSH runs commands on the MacBook, where
Xcode runs native Safari on disposable iPhone and iPad Simulators. Results can
then be copied back to Windows. The household database is not needed.

Use [README.md](README.md) for installing the test dependencies on another Mac,
and [EVIDENCE.md](EVIDENCE.md) for the accepted six-configuration run.

## The short routine on the prepared machines

1. Keep the Mac plugged in, awake, logged in and with its lid open. Connect both
   computers to the home network. Leave one test run to finish before starting
   another. Close classic Simulator windows; Xcode 27's Device Hub can stay open.
2. If the code changed on Windows, commit it and follow **Transfer changes** below.
   The Mac runs its own checkout, not the Windows working directory.
3. In **Windows PowerShell**, check SSH and prerequisites:

   ```powershell
   ssh -o BatchMode=yes -o ConnectTimeout=10 <mac-user>@<mac-address> 'echo connected'
   ssh <mac-user>@<mac-address> "/Users/<mac-user>/DeckLabSafari/run-safari --check --runtime 27.0 --ipad-model 'iPad Air 11-inch (M2)'"
   ```

4. Start the full run from **Windows PowerShell**:

   ```powershell
   ssh -t -o ServerAliveInterval=30 -o ServerAliveCountMax=6 <mac-user>@<mac-address> "caffeinate -i /Users/<mac-user>/DeckLabSafari/run-safari --runtime 27.0 --ipad-model 'iPad Air 11-inch (M2)'"
   $LASTEXITCODE
   ```

   Keep the terminal open. `caffeinate -i` prevents idle sleep while this command
   runs; keep the lid open. The accepted full run took about **32 minutes**.
   The SSH keepalive settings help detect a lost connection; they do not resume
   an interrupted run. `-t` gives the remote command a terminal for Ctrl+C.
5. Read the report and copy the complete results directory back using the steps
   below. A successful `--check` is only a readiness check, not a Safari test run.

The same run can be started directly in **Terminal on the Mac**:

```sh
caffeinate -i ~/DeckLabSafari/run-safari --runtime 27.0 --ipad-model 'iPad Air 11-inch (M2)'
echo $?
```

## Machine details and paths

These are the working values from the completed setup, not permanent network
addresses. If the router changes the Mac's IP, substitute its new address in
the commands throughout this guide.

| Item | Working value |
| --- | --- |
| Windows checkout | `C:\VSProjects\TradingCardCollection` |
| Mac SSH account and address | `<mac-user>@<mac-address>` |
| Mac checkout | `/Users/<mac-user>/DeckLabSafari/source-1b39515` |
| Mac launcher | `/Users/<mac-user>/DeckLabSafari/run-safari` |
| Private tools | `/Users/<mac-user>/DeckLabSafari/toolchain/` |
| Mac results | `source-1b39515/decklab/data/safari/<run-id>/` |
| Copied Windows results | `decklab\data\safari\macbook\<run-id>\` |

`source-1b39515` is the checkout's original directory name. It stays the same
when newer commits are transferred; it does not pin the checkout to that commit.
The launcher always runs that directory's current revision.

The prepared toolchain is Python 3.14.8, Node 24.14.0 / npm 11.9.0, Appium 3.4.2
and XCUITest 10.43.0; the lockfile moved to Appium 3.8.0 and XCUITest 10.43.1 on
2026-10-26 and to XCUITest 12.22.7 on 2026-10-30 (security fixes), so rerun `setup.sh`
as below before the next run.
The accepted run used Xcode 27.0 and iOS 27.0. These are
recorded versions, not instructions to upgrade whenever a newer release appears.

## Connect to the Mac for the first time

This is already done on the current PC and Mac. Use these steps if connecting
from a replacement PC or repairing SSH access.

### Enable Remote Login on the Mac

On the Mac, open **System Settings > General > Sharing > Remote Login**.
Turn it on and allow the `<mac-user>` account. Remote Login enables SSH; Xcode's device
testing options do not enable it. Apple's [Remote Login instructions](https://support.apple.com/en-au/guide/mac-help/mchlp1066/mac)
describe the account selection and connection command.

Find the Mac's address under **System Settings > Wi-Fi > Details > TCP/IP**.
In Windows PowerShell, test the address and SSH port:

```powershell
Test-NetConnection <mac-address> -Port 22
ssh <mac-user>@<mac-address>
```

The first SSH connection asks you to trust the Mac's host key. Check its
fingerprint against this command run locally in **Mac Terminal**, then accept
it on Windows:

```sh
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

`exit` leaves the SSH session and returns to PowerShell. A Windows SSH client
is sufficient; the Windows PC does not need an SSH server.

### Authorize the PC's public key

In **Windows PowerShell**, check for an existing public key:

```powershell
Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub"
```

If there is no key pair, create one with the following command and follow its
prompts. Reuse an existing key rather than overwriting it. A passphrase-protected
key needs to be unlocked for unattended connections; ordinary interactive SSH
can prompt for the passphrase.

```powershell
ssh-keygen -t ed25519 -C "decklab-pc"
```

Copy the entire single line from `id_ed25519.pub`. In **Mac Terminal**, replace
`PASTE_PUBLIC_KEY_HERE` below with that line, keeping the surrounding quotes:

```sh
mkdir -p ~/.ssh
chmod 700 ~/.ssh
printf '%s\n' 'PASTE_PUBLIC_KEY_HERE' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

The `.pub` file is the public key. Keep the matching file without `.pub` on the
PC. Microsoft's [OpenSSH key guide](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement)
explains the key pair and `ssh-keygen`.

Back in **Windows PowerShell**, verify key authentication without a password
prompt:

```powershell
ssh -o BatchMode=yes -o ConnectTimeout=10 <mac-user>@<mac-address> 'echo connected'
```

`macbook.local` did not resolve during setup, so the working connection uses the
IP address. The Mac currently reports `User1s-MacBook-Air` as its local hostname;
`User1s-MacBook-Air.local` is an alternative only if it resolves from the PC.

## Transfer changes from Windows without pushing to GitHub

Use a Git bundle to transfer committed source directly over SSH. This preserves
the Mac's ignored `node_modules`, private tools and earlier results. It does not
copy Windows configuration, caches or household data.

Run these blocks in **Windows PowerShell**, stopping if a command fails.

### Check both checkouts

```powershell
Set-Location C:\VSProjects\TradingCardCollection
if (git status --porcelain) { throw 'Commit or resolve local changes first.' }
$pcRevision = git rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'Cannot read the Windows revision.' }
$macRevision = @'
set -e
cd /Users/<mac-user>/DeckLabSafari/source-1b39515
test -z "$(git status --porcelain)"
git rev-parse HEAD
'@ | ssh -o BatchMode=yes <mac-user>@<mac-address> "tr -d '\r' | /bin/zsh -l -s"
if ($LASTEXITCODE -ne 0) { throw 'Mac checkout is unavailable or has local changes.' }
$macRevision = $macRevision.Trim()
if ($macRevision -notmatch '^[0-9a-f]{40}$') { throw 'Unexpected Mac revision.' }
$pcRevision
$macRevision
```

If the hashes match, skip the transfer. Otherwise confirm that the Mac's commit
is an ancestor of the Windows commit:

```powershell
git merge-base --is-ancestor $macRevision HEAD
if ($LASTEXITCODE -ne 0) { throw 'Histories need review before transferring.' }
```

A missing commit or divergent history needs investigation. Do not reset the
Mac or discard changes to make the command succeed.

### Create and copy the bundle

```powershell
$bundlePath = Join-Path $env:TEMP 'decklab-safari-update.bundle'
git bundle create $bundlePath "$macRevision..HEAD"
if ($LASTEXITCODE -ne 0) { throw 'Bundle creation failed.' }
scp $bundlePath <mac-user>@<mac-address>:/Users/<mac-user>/DeckLabSafari/incoming.bundle
if ($LASTEXITCODE -ne 0) { throw 'Bundle transfer failed.' }
```

### Apply it on the Mac

Open an SSH shell from **Windows PowerShell**:

```powershell
ssh <mac-user>@<mac-address>
```

Run this block in the resulting **Mac shell**. Do this while no test run or other
source update is active:

```sh
(
  set -e
  cd /Users/<mac-user>/DeckLabSafari/source-1b39515
  test -z "$(git status --porcelain)"
  git bundle verify /Users/<mac-user>/DeckLabSafari/incoming.bundle
  git fetch /Users/<mac-user>/DeckLabSafari/incoming.bundle HEAD:refs/remotes/windows-transfer/latest
  git merge --ff-only refs/remotes/windows-transfer/latest
  git status --short
  git rev-parse HEAD
)
```

The printed hash must match `$pcRevision` from Windows, and `git status --short`
must be empty. `--ff-only` refuses an update that would require a merge. If any
step fails, stop and inspect it rather than continuing with an older checkout.
Type `exit` to return to Windows PowerShell.

If the dependency lockfile changed, reinstall the local packages in **Mac
Terminal or the SSH shell** before running preflight:

```sh
(
  set -e
  export PATH="$HOME/DeckLabSafari/toolchain/cpython-3.14.8/python/bin:$HOME/DeckLabSafari/toolchain/node-v24.14.0-darwin-arm64/bin:$PATH"
  cd ~/DeckLabSafari/source-1b39515
  bash decklab/safari/setup.sh
)
```

Ordinary SSH shells may select macOS's older Python or a different Node. The
`run-safari` launcher sets these tool paths automatically for normal runs. See
[first setup](README.md#first-setup-on-the-mac) if rebuilding the machine or
creating a new checkout; the private tool directories are not in Git bundles.

## Read and copy the results

The runner prints its results directory. In **Mac Terminal or an SSH shell**,
list recent directories and open the chosen report:

```sh
cd ~/DeckLabSafari/source-1b39515
ls -dt decklab/data/safari/*/
cat decklab/data/safari/REPLACE_WITH_RUN_ID/report.md
```

Replace `REPLACE_WITH_RUN_ID` with the printed directory name, such as
`20261015T051426Z-59b4e5`. Check `report.json` as well: it records the source
revision, dirty state, exact model/runtime, assertions, errors and cleanup notes.
For acceptance, expect **six passed rows and 60 passed assertions**, clean source,
no unavailable configurations, no setup errors and no cleanup notes.

| Exit code | Meaning |
| --- | --- |
| `0` | Full run passed, or all six configurations are ready for `--check`. |
| `1` | A test, session or cleanup failed. |
| `2` | Missing prerequisites, unavailable configuration, startup failure or incomplete coverage. |
| `130` | Interrupted; inspect the report and let cleanup finish. |

In **Windows PowerShell**, copy the entire chosen run:

```powershell
Set-Location C:\VSProjects\TradingCardCollection
$runId = '20261015T051426Z-59b4e5' # Replace with the new run's actual ID.
$resultsRoot = Join-Path (Get-Location) 'decklab\data\safari\macbook'
New-Item -ItemType Directory -Force -Path $resultsRoot | Out-Null
scp -r "<mac-user>@<mac-address>:/Users/<mac-user>/DeckLabSafari/source-1b39515/decklab/data/safari/$runId" $resultsRoot
if ($LASTEXITCODE -ne 0) { throw 'Results copy failed.' }
Get-Content (Join-Path $resultsRoot "$runId\report.md")
Get-FileHash -Algorithm SHA256 (Join-Path $resultsRoot "$runId\report.json")
```

Keep `appium.log` and the per-configuration directories with the reports.
They contain fixture/command logs, measurements and available failure screenshots
and native source. Results are gitignored. Record reviewed acceptance in a small
committed summary with the tested commit and raw report hash, as in
[the completed evidence](EVIDENCE.md); retain the complete raw directory too.

`cleanup-verification.json` in the accepted run was an additional independent
check, not an automatically generated file in every run. Normal reports include
the runner's own cleanup notes and test device UUIDs.

## Stop a run and troubleshoot

Press **Ctrl+C once in the attached run terminal**, then wait for its report and
cleanup. Do not close SSH as a substitute for cancellation. If the connection is
lost, reconnect and inspect the exact run process before starting another suite.
For a known runner PID, `kill -INT <PID>` on the Mac requests the same graceful
interruption. Avoid force-killing the process or deleting all Simulator devices.

| Symptom | What to check |
| --- | --- |
| Hostname does not resolve | Use the current IP address; `macbook.local` failed in the original setup. |
| Connection refused on port 22 | Enable Remote Login and allow `<mac-user>`. |
| Connection times out | Check current IP, home-network connection and whether the Mac is awake. |
| `Permission denied (publickey)` | Confirm the username, public key in that account's `authorized_keys`, permissions and any key passphrase. |
| Wrong Python/Node or missing Appium | Use `~/DeckLabSafari/run-safari`; rerun local setup if the lockfile changed. |
| No compatible runtime/model | Finish the Simulator runtime download in Xcode; check `xcrun simctl list runtimes` and `xcrun simctl list devicetypes`. |
| No Simulator window | Expected in headless mode. Native iOS still runs; inspect the report and screenshots. |
| `--output` directory already exists | Choose a new directory or omit `--output` for a unique automatic name. |
| Share, Home Screen or keyboard step fails | Read the failed assertion, screenshot/native source and `appium.log`; fix the cause and rerun the full matrix. |
| PosterBoard or MobileCal quit unexpectedly | Earlier logs identified guest Simulator processes; MobileCal hit a background startup timeout. Dismissing an alert does not establish a pass. Check this run's report/logs; preserve a recurring crash's diagnostic report. |

For multiline Mac scripts piped from **Windows PowerShell**, use a single-quoted
here-string so PowerShell does not expand shell `$` expressions, and strip CRLF:

```powershell
@'
set -e
cd /Users/<mac-user>/DeckLabSafari/source-1b39515
git status --short
git rev-parse HEAD
'@ | ssh -o BatchMode=yes <mac-user>@<mac-address> "tr -d '\r' | /bin/zsh -l -s"
```

Keep such piped scripts ASCII or transfer a UTF-8 script file explicitly; Windows
PowerShell's pipe encoding damaged non-ASCII punctuation during the original
work. Windows PowerShell 5.1 also strips embedded double quotes when passing
command strings to `ssh.exe`; this guide uses single quotes around the remote
iPad model and sends scripts containing shell substitutions through standard
input. Keep that quoting when copying commands. For interactive tests, use the
attached `ssh -t` command above.

## What this proves

The suite checks native Simulator Safari in portrait and landscape on iPhone
15 Pro, iPhone 17 Pro and the selected 11-inch iPad model, including gestures,
software-keyboard Save, History, native Share/Home Screen and stale-page reload.
It serves synthetic data locally on the Mac and does not use the household
server, production config, PostgreSQL, private family data, downloads or Forge.

The iPad Air 11-inch (M2) is the selected Simulator model; it does not establish
the exact model of the physical household iPad. E2-S22 still owns physical
hardware and touch-usability observations. Testing on a real iPhone requires
separate device preparation and is outside this runner.
