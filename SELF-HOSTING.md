# Running your own Deck Lab

Set up Deck Lab on your own server PC, then use it from phones, tablets and browsers on your home network. Steps 1–7 are the core app; simulations, background running and outside access are optional.

## Before you start

- **Time:** allow about an hour for the core steps, plus card-data downloads/indexing and any prerequisite installation. Slow downloads can take longer.
- **RAM and disk:** 8 GB RAM and 10 GB free disk are planning allowances, not qualified minimums. The card index uses memory; images, database growth and retained backups need more disk. Forge needs substantially more: its worker guard budgets about 1.5 GB per worker and reserves 6 GB for the OS, database, app and browser.
- **Access:** use an account that can install Python/PostgreSQL and edit your own files. Keep the PostgreSQL password for step 5; it never belongs in config.json. No domain, Cloudflare account, Forge or NAS is required for the core app.

## Contents

- Required: [1. Install prerequisites](#1-what-to-install), [2. Get the code](#2-get-the-code), [3. Make the venv](#3-install-psycopg-into-a-venv), [4. Configure profiles](#4-write-decklabconfigjson), [5. Set up PostgreSQL](#5-set-up-the-database), [6. Download cards](#6-download-the-card-data), [7. Start and open](#7-start-it-and-open-it).
- Optional: [8. Simulations](#8-forge-simulations-optional), [9. Background running and backups](#9-keep-it-running-and-backed-up), [10. Outside access](#10-from-outside-your-home-optional), [11. Move to another PC](#11-moving-deck-lab-to-another-pc), [12. Sleep and wake](#12-let-the-server-sleep-optional).
- Recovery/reference: [Restore a backup](#restoring-from-a-backup), [Platform details](#platform-and-acceptance-reference), [Troubleshooting](#when-something-goes-wrong), [Full command/page reference](decklab/README.md).

## Quick start (Windows)

Use **PowerShell** for every command in this guide unless a step explicitly says otherwise. Download [Python 3.14](https://www.python.org/downloads/windows/), [Git for Windows](https://git-scm.com/install/windows) and [PostgreSQL](https://www.postgresql.org/download/windows/). In the classic Python installer tick **Add python.exe to PATH**; install-manager users should select 3.14 using [Python's Windows guide](https://docs.python.org/3.14/using/windows.html). Open a new PowerShell and check `python --version` reports 3.14 before making the venv. If it opens the Microsoft Store, check App execution aliases; with the classic installer, disable obsolete App Installer python aliases and reopen PowerShell.

Keep PostgreSQL's installer defaults for a new local install, and remember its `postgres` password for step 5. Once step 2 has cloned the code, run `python -m decklab.doctor` from that folder after each step. NEEDS SETUP findings are expected until their later steps are complete; the doctor does not install or repair anything.

## 1. What to install

- **Git**, to get the code.
- **Python 3.14.** On Windows, the python.org installer. On Linux or macOS, if your system has an older Python, [uv](https://docs.astral.sh/uv/) installs one beside it: `uv python install 3.14`. Use that Python (`uv python find 3.14` prints where it is) wherever this guide says `python`. Ubuntu 26.04 carries Python 3.14 itself (`apt policy python3.14` says so; install `python3.14-venv` too); on older Ubuntu releases, the deadsnakes PPA's `python3.14` and `python3.14-venv` packages work. Ubuntu has no `python` command: wherever this guide says `python`, type `python3` if `python3 --version` says 3.14, else `python3.14` (or uv's path).
- **PostgreSQL 16 or later.** On Windows, the installer from postgresql.org; it asks you to choose a password for the `postgres` superuser. Remember it for step 5. On Linux, your distribution's `postgresql` package, or for a move from another PC (step 11) the same major version as that PC (or newer). Ubuntu 26.04 carries PostgreSQL 18 (`postgresql-18`); when your distribution's is older than the old PC's, use the PostgreSQL project's own apt repository, [apt.postgresql.org](https://wiki.postgresql.org/wiki/Apt). `apt policy postgresql-18` shows which version a package would install. On macOS, Postgres.app or Homebrew.
- **For simulations only:** a JDK 21 or later (the full JDK, with `javac` and `jar`, such as Debian's and Ubuntu's `openjdk-21-jdk`) and, to build Forge yourself, Maven. See step 8.

On a Linux server PC, also:

- **The installer's disk choices**, for a PC that will sit without a screen or keyboard (Ubuntu Server's installer; others ask much the same):
  - Tick **Install OpenSSH server**, and do the rest over SSH.
  - Don't encrypt the disk: it asks for a passphrase at every boot, so the PC can't come back by itself after a power cut.
  - Ubuntu Server sets the disk up with LVM by default and then gives `/` only part of it (often 100 GB), leaving the rest unused until you extend it. Untick "Set up this disk as an LVM group" for one plain partition across the disk, or afterwards `sudo lvextend -r -l +100%FREE <the root volume>` (`df -h /` names it).
  - Installing beside Windows on a disk you shrank in Windows: if the installer's custom layout shows no "free space" row, check what's really there from its shell (Help, Enter shell): `parted /dev/nvme0n1 unit GiB print free` (`lsblk` names the disk). If the free space is there, Ubuntu Desktop's installer, whose "Install alongside Windows Boot Manager" finds it, is the easy way round; if it isn't, the shrink didn't happen (Windows' Disk Management should show it as Unallocated). Never format the existing EFI partition: mount it at `/boot/efi` as it is. Windows also keeps the hardware clock in local time and Linux in UTC; set `RealTimeIsUniversal` (a `DWORD` of 1 in `HKLM\SYSTEM\CurrentControlSet\Control\TimeZoneInformation`) in Windows so the two agree, and turn off Windows' Fast Startup (`powercfg /h off`).
- **`tesseract-ocr` and `util-linux`**, for photo scanning (`sudo apt install tesseract-ocr util-linux`, which brings English and the prlimit memory limiter). Linux OCR needs that limiter; without a supported bounded engine the scan sheets ask for each card's name instead. The backend accepts at most4000px a side, and the browser already reduces photos to2000px.
- **`avahi-daemon`**, so phones find the PC by name (`http://<the PC's name>.local:8642`). Windows answers those names by itself.
- **`cloudflared`**, only for step 10: from Cloudflare's own apt repository, [pkg.cloudflare.com](https://pkg.cloudflare.com/) (Debian and Ubuntu don't carry it).
- **The household's time zone.** A fresh Linux install is often on UTC, and Deck Lab dates things by the PC's clock: `timedatectl` shows the zone, and `sudo timedatectl set-timezone Australia/Sydney` (your own; `timedatectl list-timezones` lists them) sets it. Put the same name in `config.json` (step 4) as `"timezone"`.

### Linux packages

On a distribution that provides Python 3.14:

```sh
sudo apt update
sudo apt install git python3.14 python3.14-venv postgresql postgresql-client
python3.14 --version
psql --version
```

Use `python3.14` wherever this guide says `python` if that is its installed name. If your distribution does not provide it, use the Python-install choices above. If its PostgreSQL is older than 16, follow the [PostgreSQL project's apt instructions](https://www.postgresql.org/download/linux/ubuntu/):

```sh
sudo apt install postgresql-common
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh
sudo apt update
sudo apt install postgresql-18
```

### macOS packages

With Homebrew installed, use the versioned [Python](https://formulae.brew.sh/formula/python@3.14) and [PostgreSQL](https://formulae.brew.sh/formula/postgresql@18) packages:

```sh
brew install git python@3.14 postgresql@18
brew services start postgresql@18
export PATH="$(brew --prefix python@3.14)/libexec/bin:$(brew --prefix postgresql@18)/bin:$PATH"
python --version
psql --version
```

Keep the required versioned paths in your shell profile. The background Deck Lab/nightly features have separate platform limits below; starting PostgreSQL is not installing Deck Lab's scheduler.

## 2. Get the code

```
git clone https://github.com/matt439/DeckLab
cd DeckLab
```

Run every command in this guide from that folder, the repo root.

Until a release is published, use the git checkout above. When a release is available, you can download it instead: `decklab-VERSION.zip` from the repository's [Releases](https://github.com/matt439/DeckLab/releases), checked against its `decklab-VERSION.zip.sha256` (`sha256sum -c decklab-VERSION.zip.sha256` on Linux, `Get-FileHash decklab-VERSION.zip` in PowerShell), and unzip it. Optionally, with GitHub's `gh` installed, `gh attestation verify decklab-VERSION.zip --repo matt439/DeckLab` also confirms that the repository's own release workflow built that zip (a fork's releases: its own `owner/repo`); the checksum alone only shows the download wasn't damaged. Its `decklab-VERSION` folder takes the repo root's place in this guide. Deck Lab reads its version from the release's `decklab/release.json`, and Settings shows it. Each release's notes on GitHub list what changed since the previous release: the entries added to `decklab/HISTORY.md` since its tag (drafted by `scripts/release_notes.py`). A home admin's Settings also says when a newer release is out: the PC asks GitHub at most once a day (saved in `decklab/data/release-check.json`), downloads nothing, and links to the release's page; `"release_check": false` in `config.json` turns that off, and `"release_check": "owner/repo"` asks another repository (a fork's releases). A git checkout never asks. There's no update command for a release yet: `python -m decklab.update` needs a git checkout, so for now unzip the next release beside it, copy `decklab/config.json` across and run `python -m decklab.db migrate`.

On Linux, clone it there; don't copy a checkout from a Windows PC (a USB disk, a share or `rsync`). A copied folder usually arrives with every file executable, and sometimes with Windows line endings, so git shows every file changed and `python -m decklab.update` refuses to run.

## 3. Install psycopg into a `.venv`

Deck Lab uses only Python's standard library, apart from psycopg, the PostgreSQL client. It goes in a `.venv` in the repo, which Deck Lab finds by itself, so you go on running plain `python` afterwards.

Windows:

```
python -m venv .venv
.venv\Scripts\python -m pip install -r decklab/requirements.txt
```

Linux and macOS:

```
python -m venv .venv
.venv/bin/python -m pip install -r decklab/requirements.txt
```

Make the `.venv` with the same Python you'll run Deck Lab with. After upgrading Python, delete `.venv` and make it again.

## 4. Write `decklab/config.json`

Copy the example, then replace **alex/Alex** with your own lowercase profile id/display name:

```
cp decklab/config.example.json decklab/config.json
```

In PowerShell, `Copy-Item decklab/config.example.json decklab/config.json` works too. In a cmd prompt use `copy decklab\config.example.json decklab\config.json`.

```json
{
  "timezone": "Australia/Brisbane",
  "profiles": [
    {"id": "alex", "name": "Alex", "plays_as": "first", "role": "admin", "space": "home", "emails": []}
  ]
}
```

- `id` is lowercase letters, digits and hyphens, and `name` is what the page shows.
- `role` `admin` may change everything at home. Give the first profile that role.
- `space` `home` is the household's shared collection and decks.
- `plays_as` identifies one of the two supported home player slots: `first` or `second`. They normalize to the older `user`/`wife` values in saved records; existing configs still work. A profile using `either` can edit home decks marked **Played by: either** (an admin can also edit the other home decks). It does not grant both personal slots to a member. Use a separate space for someone with their own collection.
- `emails` is used only for logins from outside the home (step 10). Leave it empty.

To add a second person who shares your cards, add another profile with `"space": "home"`, `"role": "member"` and `"plays_as": "second"`. Someone with a collection of their own gets `"space"` set to their own `id` and no `plays_as`. The reference’s [People's own collections (spaces)](decklab/README.md#peoples-own-collections-spaces) explains what each can see and change.

`config.json` is gitignored, so your names and addresses never end up in a commit. The other settings all have defaults. [decklab/config.full.example.json](decklab/config.full.example.json) shows the optional blocks for a backup folder, outside access through Cloudflare and a records repo. Its `backup_dir` and `records_repo` are Windows paths; Linux refuses those, so on Linux give absolute paths such as `/mnt/nas-backups/DeckLab` and `/home/<you>/MyCardRecords`.

Choose your own IANA timezone in the example above. Outside Australia, also choose suitable `currency` and `shops` settings below. JSON paths use forward slashes (`C:/Tools/forge-decklab`) or doubled backslashes (`C:\\Tools\\forge-decklab`).

### Linux and macOS config notes

Two optional settings matter most on Linux:

- **`"timezone"`:** the household's time zone, such as `"Australia/Sydney"`. The Linux nightly timer runs at 03:30 in that zone, a receipt's arrival date and a game's date are worked out in it, and the smoke test and doctor warn when the PC's own clock keeps another zone. Without it they follow the PC's clock (and those two dates use UTC+10).
- **Folders:** on Linux and macOS, `records_repo` and the `"database"` block's `backup_dir`, `staging_dir`, `export_repo` and `pg_bin` must be absolute paths such as `/mnt/nas-backups/DeckLab`; `~` works on every system. A Windows path (`\\NAS\...`, `D:\...`, any backslash) is refused with a message naming the setting: the backup and export fail and say so, and so does the smoke test. Give `forge_dir`, `forge_java` and the tunnel's `config` as absolute paths too.

**Price-check shops:** each night Deck Lab looks the purchase queue's cards up at two Australian shops, MTGMate and Games Portal, and shows their prices in AUD. If you can't buy from them, turn the check off with `"shops": []`, or keep one with `"shops": ["mtgmate"]` (the keys are `mtgmate` and `gamesportal`). Without the setting both are checked.

**Currency:** prices are estimates in AUD unless you set `"currency"` to an ISO code the ECB publishes a USD rate for (`"EUR"`, `"GBP"`, `"CAD"`, ...). Once Deck Lab is running, an admin can choose both the currency and the price-check shops on Settings' **Prices** part instead, without editing this file or restarting; a choice made there wins, and this file's values apply to any field left to "Use config.json's".

On Linux and macOS, `chmod 600 decklab/config.json`: it holds the household's emails.

## 5. Set up the database

PostgreSQL must be running. Deck Lab connects to it on `localhost`, port 5432, over TCP with a password.

On Linux, the `postgres` superuser usually has no password at first. Give it one:

```
sudo -u postgres psql -c "\password postgres"
```

Then, from the repo root:

```
python -m decklab.db setup
```

It asks for the `postgres` password once and doesn't save it. It makes Deck Lab's three database roles, each with a random password, and saves those in your pgpass file (`%APPDATA%\postgresql\pgpass.conf` on Windows, `~/.pgpass` elsewhere), which PostgreSQL's client reads by itself. Then it makes the `decklab` database, applies the migrations, copies your profiles in, and starts an empty collection, deck library and shopping list.

Running it again is safe. After changing the profiles in `config.json`, run `python -m decklab.db sync-profiles` (or `setup` again) to copy them in. To skip the password question, add this line to the pgpass file yourself (on Linux and macOS, run `chmod 600 ~/.pgpass` afterwards):

```
localhost:5432:*:postgres:<the postgres password>
```

`python -m decklab.db status` shows what the database holds.

## 6. Download the card data

```
python -m decklab.lib.cards update
```

This downloads Scryfall's card data, about 100 MB and a few minutes. The server also does it on its first start, and again once a week.

## 7. Start it and open it

Before starting the server, check the setup:

```
python -m decklab.doctor
python -m decklab.doctor --json
```

Both forms give the same ordered findings and next setup steps. Exit status `0`
means the core checks passed, `1` means known setup work remains, and `2` means a
core check could not be verified (or the command arguments were invalid). Optional
findings (Java and Forge, photo scanning, the time zone and the backup folders) do not
block the core app. The backup folders check reads `database.backup_dir`, `staging_dir`,
`export_repo` and `pg_bin` as the backup does: a Windows or relative path on Linux, a
`backup_dir` whose folder can't be reached, or one on the staging folder's disk without
`backup_same_device_ok` is reported, since every backup would fail; nothing is written.

The command reads the local configuration and card index and attempts one app-role
database connection. It checks PostgreSQL's version, the bundled migration
checksums and inventory/deck initialization markers in a read-only transaction;
it does not inspect collection contents or establish complete schema, grant or
data integrity. Connection attempts use a two-second per-address timeout, queries
a five-second timeout and locks a two-second timeout. Name resolution is outside
that connection timeout; multi-host lists are left unverified without contact.
Oversized inputs and inaccessible files also remain explicit findings.

The report contains fixed descriptions, with no paths from your configuration,
emails, credentials, records or raw errors. No install, download, migration,
schedule, service or game runs. Java is checked only when `forge_java` selects an
explicit path; this command does not search for or execute Java. The optional
checks establish declared Java version and Forge archive-file presence only, not
archive integrity, the expected fork build, card-log readiness or successful games.
Use step 8's separate qualification when setting up simulations.

When the core checks pass, start the server:

```
python decklab/server.py
```

Open http://localhost:8642 and pick yourself on **Who are you?**. Ctrl+C stops the server.

- **Only this computer:** `python decklab/server.py --host 127.0.0.1`. Without `--host`, Deck Lab listens on every network interface, so phones and tablets on your Wi-Fi can open `http://<this computer's address>:8642`. On Windows, the first start may ask about Python's network access: allow it on private networks, or run the firewall script (reference, "Network setup (once, as administrator)").
- **Linux's firewall:** many Linux installs have none turned on, and Deck Lab answers only home-network addresses anyway ("What runs where"). With one on, let in the home network only, never everyone:
  - ufw: `sudo ufw allow from 192.168.1.0/24 to any port 8642 proto tcp`, and `sudo ufw allow from 192.168.1.0/24 to any port 5353 proto udp` for the PC's `.local` name (your own network in place of `192.168.1.0/24`).
  - firewalld: `sudo firewall-cmd --permanent --zone=<zone> --add-rich-rule='rule family=ipv4 source address=192.168.1.0/24 port port=8642 protocol=tcp accept'` and `--add-service=mdns`, then `sudo firewall-cmd --reload`.
  - Never open port 8644 (the tunnel's listener stays on this PC). `python -m decklab.lib.homenet status` reads firewalld's zone and gives the right command for yours.
- **Another port:** `--port 8650`, or `"port"` in `config.json`.

Some first steps:

- **Collection page, More, Import cards…:** a ManaBox, Moxfield, Deckbox or collection-columns CSV export.
- **Collection page, More, Add a precon…:** a published precon's cards, with its deck.
- **Decks, New deck:** write or paste a deck list. Owned versus needed works from your collection.

## 8. Forge simulations (optional)

Matchups play full games with [Forge](https://github.com/Card-Forge/forge)'s computer players. Deck Lab needs its own build of Forge, from the fork [matt439/forge](https://github.com/matt439/forge), branch `decklab`, which adds the hooks the card log and game patches use. Deck Lab works without it: only the Matchups and Lab pages need it.

You need a **Java JDK 21 or later** (a full JDK, with `javac` and `jar`: the card log is compiled on your PC), such as [Eclipse Temurin](https://adoptium.net/). Then get Deck Lab's Forge one of two ways.

### Download it (the usual way)

1. **Download the release** Deck Lab expects: [2.0.16-decklab-029c9518f](https://github.com/matt439/forge/releases/tag/2.0.16-decklab-029c9518f) (it's `RELEASE` in [decklab/lib/forge/simjar.py](decklab/lib/forge/simjar.py)). It's Forge 2.0.16 with the fork built in. Get both files: `forge-2.0.16-decklab-029c9518f.zip` and its `.zip.sha256`.
2. **Check the checksum** matches the one in the `.sha256` file and the release's notes:
   - Windows (PowerShell): `Get-FileHash forge-2.0.16-decklab-029c9518f.zip -Algorithm SHA256`
   - Linux: `sha256sum -c forge-2.0.16-decklab-029c9518f.zip.sha256`
   - macOS: `shasum -a 256 -c forge-2.0.16-decklab-029c9518f.zip.sha256`

   If it doesn't match, the download is damaged: delete it and download it again.
3. **Unzip it** somewhere of its own, such as `C:\Tools` or `~/tools`. It makes one folder, `forge-2.0.16-decklab-029c9518f`.
   - Windows: Explorer's **Extract All**, or `Expand-Archive forge-2.0.16-decklab-029c9518f.zip C:\Tools`.
   - Linux: `unzip forge-2.0.16-decklab-029c9518f.zip -d ~/tools` (a stock Ubuntu or Debian server has no `unzip`: `sudo apt install unzip`). Without it, Deck Lab's own unzipper keeps the launchers' permissions, from the repo's folder: `python -c "import os; from decklab.update import safe_extract; print(safe_extract('<the zip>', os.path.expanduser('~/tools')))"`. (Python's own `python -m zipfile -e` drops them; games still play, as Deck Lab starts Java itself.)
   - macOS: `unzip forge-2.0.16-decklab-029c9518f.zip -d ~/tools`.

   Then either rename that folder to `forge-decklab` (`~/tools/forge-decklab`, or `C:\Tools\forge-decklab` on Windows), where Deck Lab looks when `config.json` has no `forge_dir`, or keep its name and set `forge_dir` to it (below). Later releases are installed beside it as `forge-<release>` by `python -m decklab.update`, which sets `forge_dir` itself.
4. Go on with "Point Deck Lab at it" below.

### Or build it from source

Only if you want to change Forge itself, or no release fits your Deck Lab. It needs Maven as well as the JDK.

1. **Download the Forge 2.0.16 release** from [Forge's releases](https://github.com/Card-Forge/forge/releases/tag/forge-2.0.16) (the desktop archive) and unpack it into a folder of its own, such as `C:\Tools\forge` or `~/forge-2.0.16`. It should hold one `forge-gui-desktop-2.0.16-jar-with-dependencies.jar` and a `res` folder. The build copies its `res` folder and launch scripts, and never changes it.
2. **Clone the fork with its history.** The build compares the branch with the `forge-2.0.16` tag, so don't make a shallow clone:
   ```
   git clone -b decklab https://github.com/matt439/forge forge-decklab-src
   ```
   Deck Lab trusts the card log only from the fork build it was checked with: `RELEASE` in [decklab/lib/forge/simjar.py](decklab/lib/forge/simjar.py), such as `2.0.16-decklab-029c9518f`. If the branch has moved on since, check out that commit (`git checkout 029c9518f`). Any other build still plays matchups, but with plain Forge and without per-card stats.
3. **Build and install it** with `JAVA_HOME` set to the JDK and Maven on the PATH. From the fork's folder:
   ```
   python decklab/install.py --release <the release folder> --out <where to install it>
   ```
   The first build downloads Maven's dependencies and takes several minutes. The `--out` folder is made new; nothing else is changed. `install.py`'s defaults are Windows folders, so on Linux always give both `--release` and `--out`.

### Point Deck Lab at it

1. **Set `forge_dir`** in `config.json` to the folder you unzipped or installed (not needed if you renamed it to the default `forge-decklab` folder above):
   ```json
   "forge_dir": "<that folder>",
   ```
   Deck Lab looks for Java where the usual JDK installers put it (Oracle's `C:\Program Files\Java`, Temurin's `Eclipse Adoptium`, `Microsoft`, `Zulu` and `Amazon Corretto`; the newest JDK, one with `javac` before a JRE), then `JAVA_HOME`. Off Windows it looks in `JAVA_HOME`, `/usr/lib/jvm/*`, `/usr/lib64/jvm/*`, `/opt/java/*`, `/opt/jdk*`, `~/.sdkman/candidates/java/*`, `~/.jdks/*` and the PATH's `java`, and takes only Java 21 or later (by the JDK's `release` file), saying "Java 21 or later wasn't found" (and which older one it found) otherwise. Set `"forge_java"` to the JDK's `java` (`java.exe` on Windows) if it picks the wrong one.

   On Linux a distribution's JDK under `/usr/lib/jvm` is found without `forge_java`, by the background service too. Set it for a JDK installed elsewhere and found only through `JAVA_HOME` or a PATH set in a shell profile (the service sees neither), or so that `python -m decklab.doctor` can check Java (it never searches for one, so without `forge_java` its Java check says "not verified"). Give the JDK's real path, as `readlink -f $(which java)` prints it (such as `/usr/lib/jvm/java-21-openjdk-amd64/bin/java`), not `/usr/bin/java`, which is a link the doctor won't follow; `forge status`'s `java:` line prints the real path too. Without `forge_dir`, Deck Lab looks in `~/tools/forge-decklab` on Linux and macOS (`C:\Tools\forge-decklab` on Windows).
2. **Check it:** `python -m decklab.lib.forge status` says whether Forge is ready, and its `build:` line whether it's the build this Deck Lab expects (and what to download if not). Then run `python -m decklab.lib.forge cardlog-check` once: it builds the card-log jar with this PC's JDK and plays a few games several ways, to confirm the card log here. The release Deck Lab expects already has the card log on (`status` says `card log: on`); for another build, cardlog-check is what turns it on when the games match.

Deck Lab runs up to 16 Forge workers at once, each with up to 1 GB of memory. Unless `config.json` sets `"forge_workers"`, it sizes that to the PC: about one a physical core, and 1.5 GB of memory each after 6 GB left for everything else (an 8-core PC with 16 GB gets 4; a 16-core PC with 32 GB, 8). Set `"forge_workers"` to choose another number, or admins can lower it on the Settings page.

On Linux and macOS:

- Forge's games run at nice 10 (below normal on Windows), so the page stays quick while they play. Without a `nice` program they run at normal priority.
- `"forge_pin"` (pinning workers to cores) works on Windows only; elsewhere it does nothing and the log says so once.
- Forge keeps its settings in a folder of each run's own under `decklab/data/forge`, through `-Duser.home` (Forge reads `APPDATA` only on Windows). If that disk can't hold symbolic links, the settings are copied there at each start instead, and the log says so once.
- The worker budget shared by the server and the command line is in `~/.local/share/DeckLab/forge-slots` (never `$XDG_DATA_HOME`, which the service, the nightly timer and your shell needn't share), or `DECKLAB_FORGE_SLOTS`, which the service and your shell must then both have.
- Under the background service, a Forge game left over from a crashed server ends with the service. A command-line Forge run killed with `kill -9` can leave its Java processes running: `pgrep -af forge-gui-desktop` lists them, and `kill <pid>` ends one.

## 9. Keep it running and backed up

- **Windows, in the background and at logon:** run `python -m decklab.lib.homenet install --at-logon`. The restart watchdog comes with it. Then run the firewall setup from step 7 (`powershell -ExecutionPolicy Bypass -File decklab/network-setup.ps1`). The server and nightly tasks need this same Windows account signed in. Sign in manually after boot, or choose [Microsoft Autologon](https://learn.microsoft.com/en-us/sysinternals/downloads/autologon) for a trusted PC: run its GUI, enter the account details and Enable; Disable reverses it. Local administrators can recover its stored credentials, so make this a deliberate operator choice.
- **Linux, in the background:** `python -m decklab.lib.homenet install --at-logon` writes a systemd user service, `~/.config/systemd/user/decklab.service`, which runs `python decklab/server.py --background` in the repo with the Python you ran install with, enables it and starts it. `start`, `stop`, `restart`, `remove` and `status` work as on Windows; without `--at-logon` it starts only when you run `homenet start`. If the server stops with an error, systemd starts it again after 10 seconds; `homenet stop` leaves it stopped. Its log is `decklab/data/logs/server.log` (and `journalctl --user -u decklab.service` shows what systemd saw). Give `install` the same `--port` and `--host` you'd give the server.
  - The unit records the PATH (and `JAVA_HOME`, if set) of the shell you run `install` in, since a service doesn't read your shell profile, and keeps the files it writes private to you (`UMask=0077`). Run `install` again after changing the PATH or Java, or after updating from an older Deck Lab: `status` warns "Its unit isn't what install writes now" until you do.
  - After 3 failed starts within 15 minutes systemd gives up, and `status` says so; `start` and `restart` clear that first. They also refuse, before stopping anything, when the unit's Python or `server.py` has gone (say to run `install` again), and when a start doesn't answer they show the end of the server's log.
  - `systemctl --user` needs your own login session. After `sudo -u` or `su`, Deck Lab finds `/run/user/<your uid>` by itself when it's yours; otherwise log in as that user over SSH (or `sudo machinectl shell <user>@`), or `export XDG_RUNTIME_DIR=/run/user/$(id -u)`.
  - `scripts/decklab` runs `homenet` from any folder, on the Python the `.venv` was made from (`DECKLAB_PYTHON` to choose another): `decklab` starts the server, and `decklab stop`, `decklab status` and so on pass through. Link it into your PATH (`ln -s "$PWD/scripts/decklab" ~/.local/bin/decklab`). On Windows it's `scripts\decklab.cmd`.
  - A server run by hand in a terminal stops cleanly when the terminal closes, unless it was started with `nohup`.
- **Linux, at boot:** systemd runs your own services only while you're logged in. For Deck Lab to start at boot and keep running after you log out, turn on lingering once: `loginctl enable-linger` (on some systems, `sudo loginctl enable-linger $USER`). `install` and `status` remind you while it's off.
- **macOS:** use the [foreground/manual-job instructions](#macos-foreground-and-operator-managed-jobs) below. Built-in service/scheduler control is unsupported; no installed job is inferred.
- **Backups:** `python -m decklab.db backup` writes a dump to `decklab/data/backups/` and copies it to `database.backup_dir` in `config.json`, a folder on another disk or a NAS:
  ```json
  "database": {"backup_dir": "D:\\Backups\\DeckLab"}
  ```
  Without it the dumps stay in `decklab/data/backups/` only, on the same disk as the database, and `backup` says so. `backup` makes only the last folder of `backup_dir`: its parent must already be there, so a missing share fails instead of filling a new folder on the PC's own disk.
### Optional NAS and remote-export hardening

The export repository is created automatically when export first runs; you do not need to initialize it by hand. NAS mounts, a pushed private export repo and additional remote-copy controls are optional.

- **Backups to a NAS from Linux:** mount the share at boot with a line in `/etc/fstab`, such as `//nas/Backups /mnt/nas-backups cifs credentials=/etc/decklab-nas.cred,uid=<you>,gid=<you>,file_mode=0600,dir_mode=0700,_netdev,nofail,x-systemd.automount 0 0` (`file_mode` and `dir_mode` keep the dumps private to you: on a `cifs` mount a file's permissions come from the mount, not from the umask, and without them every account on the PC can read every dump, which is the whole database; the credentials file holds `username=` and `password=` lines, owned by root, `chmod 600`; `cifs-utils` must be installed; an NFS share works too). On a local disk, `backup`, `export`, `restore-check`, `restore` and `nightly` keep the files they write private to you however they're started (umask 077), from the timer, `update` or your own shell. Then set `"backup_dir": "/mnt/nas-backups/DeckLab"`. Use the NAS's IP address in the line if the PC can't resolve the NAS's Windows-style name. With `x-systemd.automount`, the share mounts on first use: after `sudo umount /mnt/nas-backups`, a manual `sudo mount /mnt/nas-backups` says "Device or resource busy" (the automount point is still there); just `ls /mnt/nas-backups` and systemd mounts it again, with any changed `/etc/fstab` line after `sudo systemctl daemon-reload`. Off Windows, backup, prune, the restore check and the smoke test refuse a `backup_dir` on the same disk as the staging folder ("is the NAS share mounted?"), so an unmounted share never takes the dumps; `"backup_same_device_ok": true` in the `"database"` block allows it when that's what you want. A `backup --dest` folder isn't checked.
- **Backups the server itself can't destroy.** Whatever can write to the backup folder can also delete from it, so a server that's broken into (it's the PC that answers the internet through step 10's tunnel) could take its backups with it. Three cheap steps limit that:
  - Give the server a NAS user of its own, with read and write on **one share holding only Deck Lab's backups** (NAS permissions are usually per shared folder, not per subfolder), and no access to anything else. Then the credentials file on the server opens nothing more. A NAS administrator's login there would open every share, and could delete snapshots and users. Check it: `sudo mount -t cifs //<nas>/<another share> /mnt/test -o credentials=/etc/decklab-nas.cred,ro` should fail with "Permission denied".
  - Have the NAS copy that share every night, an hour after the 03:30 backup, into a second share the server's user can only read (or not reach at all). Make the job only copy, never mirror: a mirror deletes from the copy what was deleted from the source, which includes Deck Lab's own pruning, and anything worse. If the NAS has snapshots, scheduled snapshots of the backup share do the same job better.
  - On GitHub, add a ruleset to the export repo's branch that blocks force pushes and deleting the branch (repo Settings, Rules; a private repo needs a paid plan for rulesets). The nightly export only adds commits, so it carries on, but the server's deploy key can't rewrite the history.
- **The nightly job:** `python -m decklab.db nightly` runs the backup, its pruning, a restore check now and then, and the data's check. It also exports the data as plain files into a git repo of their own, `../DeckLabData` beside this repo, unless `database.export_repo` says where. `python -m decklab.db schedule install` runs it every night at 03:30: on Windows as a Task Scheduler task, on Linux as a systemd user timer (`decklab-nightly.timer` and `decklab-nightly.service` in `~/.config/systemd/user`), which catches up a night the computer was off, as soon as it's on again. `schedule status` shows the next and last run, and `schedule remove` takes it away. Run `schedule install` with the Python you run Deck Lab with, after installing psycopg (step 3), and again after moving the repo or upgrading Python; `status` warns when its units are out of date. Lingering (above) lets it run while you're logged out. On Linux the run is at 03:30 in `config.json`'s `"timezone"` when it's set, runs at nice 10 with idle disk priority, and first waits up to 3 minutes for PostgreSQL to answer, for a night caught up at boot (logging that to `decklab/data/logs/db.log`). On macOS, schedule it with cron.
- **The export repo's push** runs at night with nobody to sign in. On Linux use an SSH deploy key with write access for the export repo: `ssh-keygen -t ed25519 -f ~/.ssh/decklabdata -N ""`, add the `.pub` file as a deploy key on GitHub, add a `Host github-decklabdata` entry with `HostName github.com` and `IdentityFile ~/.ssh/decklabdata` to `~/.ssh/config`, then `git -C <export_repo> remote set-url origin git@github-decklabdata:<you>/DeckLabData.git`. Check it with `git -C <export_repo> push --dry-run`. GitHub takes each deploy key for one repo only, so a private `records_repo` needs a key of its own, with its own `Host` alias: read-only is enough, since Deck Lab only reads it (it never pulls it either: `git -C <records_repo> pull` when new research should resolve there).
- **pg_dump:** Deck Lab finds it in `C:\Program Files\PostgreSQL\<version>\bin` on Windows; on Linux in the newest `/usr/lib/postgresql/<version>/bin` (Debian and Ubuntu) or `/usr/pgsql-<version>/bin` (Red Hat's and the PostgreSQL project's packages); then on the PATH. Set `database.pg_bin` to its folder if it's somewhere else.
- **Updating:** `python -m decklab.update` (see "Updating" below), or by hand: `git pull`, `python -m decklab.db migrate`, `python -m decklab.lib.homenet restart`, then the smoke test below.

To see the nightly units without installing anything (for another computer, say), `schedule preview-systemd` prints one, for the paths you give:

```
python -m decklab.db schedule preview-systemd --unit service --python /usr/bin/python3.14 --workdir /srv/DeckLab
python -m decklab.db schedule preview-systemd --unit timer --python /usr/bin/python3.14 --workdir /srv/DeckLab --at 03:30
```

To check the Linux services on your computer from end to end, `scripts/linux_services_check.sh` installs the timer and the service on port 18642, restarts the server, kills it to see systemd start it again, stops it and removes both (`PYTHON=<your python> scripts/linux_services_check.sh`).

### macOS foreground and operator-managed jobs

The built-in macOS mode is **foreground**. Run `python decklab/server.py` (or `scripts/decklab`) and stop it with Ctrl+C in that terminal. `homenet status` explains the limits; install/start/stop/restart do not pretend to manage a background job. The git updater refuses before fetching and points to the manual sequence below. Linux/Windows service commands are not macOS instructions.

For Homebrew PostgreSQL, `brew services start postgresql@18` starts the database. Its initial admin may be your macOS account rather than a role named postgres. If postgres is absent, use `createuser -s postgres` from that local admin account, then open `psql -d postgres` and enter `\password postgres`. Do not recreate an existing role. See the [Homebrew formula](https://formulae.brew.sh/formula/postgresql@18) for its installed paths. Postgres.app users should use that installation's admin/tools.

Foreground manual update, after stopping the server:

```sh
python -m decklab.db backup
git pull --ff-only
.venv/bin/python -m pip install -r decklab/requirements.txt
python -m decklab.db migrate
python -m decklab.lib.forge status
python decklab/server.py
```

The Forge check does not install or play anything. If it expects a different build, use step 8 before starting. In a second terminal run `python -m decklab.smoke`; its scheduler warning is honest unless a recent successful whole-nightly receipt is available. Migration 0023 adds those operational receipts; individual dump/check rows do not prove a whole nightly or future schedule. Keep this install's Python/venv consistent when upgrading.

Optional DIY LaunchAgents are operator-managed. They run in the logged-in user's context; use the same account/private config/pgpass as the foreground app. Replace every path and label below, including Intel versus Apple Silicon Homebrew paths, and make the log directory first. Check [Apple's launchd guidance](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html) and your Mac's `man launchctl`/`man launchd.plist` before installing them. Deck Lab installs none of these jobs.

Save the server example as `~/Library/LaunchAgents/com.example.decklab.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>WorkingDirectory</key>
	<string>/Users/YOUR-ACCOUNT/DeckLab</string>
	<key>EnvironmentVariables</key>
	<dict>
		<key>PATH</key>
		<string>/opt/homebrew/opt/postgresql@18/bin:/usr/local/opt/postgresql@18/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
	</dict>
	<key>Label</key>
	<string>com.example.decklab</string>
	<key>ProgramArguments</key>
	<array>
		<string>/opt/homebrew/bin/python3.14</string>
		<string>/Users/YOUR-ACCOUNT/DeckLab/decklab/server.py</string>
		<string>--background</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>KeepAlive</key>
	<true/>
	<key>StandardOutPath</key>
	<string>/Users/YOUR-ACCOUNT/DeckLab/decklab/data/logs/launchd-server.log</string>
	<key>StandardErrorPath</key>
	<string>/Users/YOUR-ACCOUNT/DeckLab/decklab/data/logs/launchd-server.log</string>
</dict>
</plist>
```

Save the calendar example as `~/Library/LaunchAgents/com.example.decklab-nightly.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>WorkingDirectory</key>
	<string>/Users/YOUR-ACCOUNT/DeckLab</string>
	<key>EnvironmentVariables</key>
	<dict>
		<key>PATH</key>
		<string>/opt/homebrew/opt/postgresql@18/bin:/usr/local/opt/postgresql@18/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
	</dict>
	<key>Label</key>
	<string>com.example.decklab-nightly</string>
	<key>ProgramArguments</key>
	<array>
		<string>/opt/homebrew/bin/python3.14</string>
		<string>-m</string>
		<string>decklab.db</string>
		<string>nightly</string>
	</array>
	<key>StartCalendarInterval</key>
	<dict>
		<key>Hour</key>
		<integer>3</integer>
		<key>Minute</key>
		<integer>30</integer>
	</dict>
	<key>StandardOutPath</key>
	<string>/Users/YOUR-ACCOUNT/DeckLab/decklab/data/logs/launchd-nightly.log</string>
	<key>StandardErrorPath</key>
	<string>/Users/YOUR-ACCOUNT/DeckLab/decklab/data/logs/launchd-nightly.log</string>
</dict>
</plist>
```

Validate edited files with `plutil -lint <file>`. Register each with `launchctl bootstrap "gui/$(id -u)" <file>`. For the loaded server, `launchctl kickstart -k "gui/$(id -u)/com.example.decklab"` restarts it; `launchctl bootout "gui/$(id -u)/com.example.decklab"` unloads/stops it. Boot out your own server job before the manual update, then bootstrap it again afterward; do not assume kickstart can restart an unloaded job. The calendar is Mac-local 03:30: align the system/config timezone, keep the Mac awake, and verify actual nightly receipts. A plist alone proves no backup or device acceptance.

Java discovery includes `/Library/Java/JavaVirtualMachines/*/Contents/Home` and Apple Silicon/Intel Homebrew openjdk layouts, alongside JAVA_HOME/PATH. Choose a full JDK 21+; source tests emulate these paths, not an actual Mac install. Phone/Safari, OCR and native scheduling checks remain separate.

### Check the whole install: the smoke test

Once the server runs in the background (or before, to see what's left), and again after every update:

```
python -m decklab.smoke
```

It takes under a minute on a typical PC and needs no test suite. The doctor (step 7) only reads files. This command goes further, and actually:

- connects as each of Deck Lab's three database roles, read-only, and checks that every migration is applied;
- runs `pg_dump` and `pg_restore` (their version must be at least the server's), and checks that the backup folders are writable and when the last backup worked;
- looks up real cards in the card index;
- reaches Scryfall, the exchange-rate site, EDHREC and the two shops;
- starts a throwaway server on a spare port on `127.0.0.1`, loads the page with every file it links to, and makes read-only API calls;
- asks the background server on your configured port whether it's running, and whether it runs older code than the checkout (after a `git pull` without a restart);
- runs `homenet status` and `schedule status` (their warnings are passed on), checks the tunnel's `cloudflared`, its config and that the server would really start it (an `access` listener, and cloudflared's config sending the hostname there) when `config.json` has a tunnel, and checks that `records_repo` is a git checkout when it's set;
- checks that Deck Lab may hold the PC awake (one try, let go at once), that the PC's clock keeps `config.json`'s `"timezone"`, and that photo scanning has an engine, by reading a drawn test card's bottom line (a warning without one);
- plays one real Forge game twice with the card log on (`forge engine-check`), and checks that Forge is the build this Deck Lab expects (skipped when Forge isn't installed, since it's optional).

Each part says PASS, WARN, FAIL or SKIP, with what to do. A warning (no backup yet, the nightly task not installed, the server not running yet) doesn't fail the run. The exit code is `0` with no failures and `1` with any. `--json` prints the results as JSON. `--offline` skips the network, `--no-forge` skips Forge and `--no-server` skips the throwaway server.

It never writes to the database or changes your cards, decks or settings, and it never stops or restarts the background server. It writes only temporary files and Forge's own caches under `decklab/data/forge`. Unlike the test suite, which uses stand-ins, it uses your real `config.json`, PostgreSQL and Forge, so it shows whether this PC works, not whether the code does. The test suite is for the PC the code is developed on.

### Updating

```
python -m decklab.update --dry-run     # what's coming, changing nothing
python -m decklab.update
```

**Which updates it takes (the update channel).** By default it follows the branch's upstream, `main`: every change as soon as it's merged (the channel Deck Lab's own server uses). For only the tested, numbered releases, set the release channel in `config.json`, `"update": {"channel": "release"}`, or give `--channel release` once (`--channel main` overrides the setting the other way). On the release channel it also fetches the tags and fast-forwards only to the newest stable version tag on `main` (`v1.2.0`, as the release workflow publishes them; never a pre-release such as `v1.3.0-rc1`, never a commit between releases). It never goes back: a checkout already at or past the newest release (one that followed `main` before) stays where it is until a newer release comes out. The checkout stays on its branch, so going back to the `main` channel later is an ordinary fast-forward. Everything else below is the same on both channels.

A home admin's Settings, About, shows how many updates are waiting in a git checkout: commits `origin/main` has that this checkout hasn't (main channel), or newer releases (release channel, naming the newest). It counts from what git last fetched, with that fetch's date, and never fetches for the page: `python -m decklab.update --dry-run` (or `git fetch`) brings it up to date. A release install shows its newer-release line instead (above).

It's for a PC that serves Deck Lab and only takes updates, with the code written and tested on another computer. It refuses a checkout with changed tracked files, or with commits its upstream doesn't have, so it never merges or loses anything. It also refuses, before fetching, to run on another Python than the one the `.venv` was made from, and on Linux than the one the background service and nightly timer run (install them again with that Python first). Then, stopping at the first step that fails:

1. fetches, shows the new commits, and fast-forwards (`git merge --ff-only`);
2. reinstalls psycopg into the `.venv` when `decklab/requirements.txt` changed (on Windows the server is stopped for it, since it holds psycopg's files open; on Linux it keeps running until step 3 or 5);
3. with migrations pending, stops the running server (on Windows and Linux alike, which ends any Forge games it's playing), makes a backup (`python -m decklab.db backup`), then migrates. The server is stopped first so that nothing is saved after the backup: restoring that backup then loses no change. Step 5 starts it again. With no migration pending the server isn't stopped here;
4. when the new Deck Lab expects another Forge build than `forge_dir` holds, downloads that release, checks its SHA-256, unzips it beside the old folder (keeping its files' modes on Linux, so its launch scripts stay executable) and points `forge_dir` in `config.json` at it (the old `config.json` is kept as `config.json.before-forge-update`, and the old Forge folder is left for you to delete). Nothing happens to Forge when it isn't installed;
5. restarts the background server, if it's running (or step 2 or 3 stopped it) and something changed (new code, psycopg, a migration, the Forge release, or the server itself says it runs older code); otherwise it leaves it running, so Forge games it's playing aren't stopped;
6. runs the smoke test.

Steps 2 to 6 run in the code just pulled. When a step fails, it says how to go back: `git reset --hard <the old commit>` and a restart for the code. Migrations aren't undone, so the backup from step 3 is the way back for the data (`python -m decklab.db restore`, below). When the backup or the migration fails, the server is still stopped: the message says so and how to start it (`python -m decklab.lib.homenet start`). Going back to the old code alone, without restoring, is fine when the migrations that were applied only added things (tables, columns, indexes), which is the rule Deck Lab's migrations follow: add in one release, remove in a later one. The old code then shows admins "Deck Lab's database is newer than this code" and refuses nothing. `--no-forge`, `--no-restart` and `--no-smoke` skip those steps, except that a server stopped for a migration is started again even with `--no-restart`.

## 10. From outside your home (optional)

This adds a locally managed Cloudflare Tunnel and an email-gated Access application. Deck Lab owns starting/stopping its tunnel process, using the local config file below. Leave these blocks absent until the policy and credentials are ready. Replace every example domain, UUID, path, team and audience with your own; no household values belong in git.

1. **Prepare the domain and tool.** Add a domain you control to Cloudflare and finish its zone/nameserver setup. Install `cloudflared` on the server PC using [Cloudflare's downloads](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/); Linux packages are at [pkg.cloudflare.com](https://pkg.cloudflare.com/). The app needs no public inbound firewall port. See the [local-tunnel guide](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/create-local-tunnel/) for the CLI workflow.
2. **Create the named tunnel.** From your normal server account, run:

   ```text
   cloudflared tunnel login
   cloudflared tunnel create decklab
   cloudflared tunnel route dns decklab decklab.example.com
   ```

   Login opens a browser for your Cloudflare account/zone. Creation prints a tunnel UUID and writes its credentials JSON under that account's `.cloudflared` folder. DNS routing creates the hostname's CNAME. Keep the printed UUID/path; do not start a separate tunnel service, since Deck Lab manages this one.
3. **Protect the full hostname with Access.** In Cloudflare One, go to **Access controls > Applications**, create a **Self-hosted and private** application and add the public hostname `decklab.example.com`. Add an Allow policy limited to the intended email addresses and enable your desired identity provider (email one-time PIN is sufficient for this example). Save it before starting the tunnel. Do not add a Bypass/Everyone policy. The [self-hosted application instructions](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/) describe the dashboard flow.
4. **Record team and audience.** Your Access login domain is `https://<team>.cloudflareaccess.com`; use just its team prefix below. In the application's **Edit > Additional settings**, copy its **Application Audience (AUD) Tag**. This is the application's audience, not the tunnel UUID. Put the same audience/team in both files below; Cloudflare's [JWT guide](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/) shows where to find it.
5. **Write `.cloudflared/config.yml`.** Use the credentials path printed in step 2 (forward slashes also work for a Windows path such as `C:/Users/YOUR-ACCOUNT/.cloudflared/TUNNEL-UUID.json`):

   ```yaml
   tunnel: TUNNEL-UUID
   credentials-file: /absolute/path/.cloudflared/TUNNEL-UUID.json
   ingress:
     - hostname: decklab.example.com
       service: http://127.0.0.1:8644
       originRequest:
         access:
           required: true
           teamName: example-team
           audTag:
             - ACCESS-APPLICATION-AUD
     - service: http_status:404
   ```

   Port 8644 is Deck Lab's loopback Access listener; do not point this hostname at the home listener on 8642. The final 404 is the catch-all. Cloudflared's [origin Access parameters](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/origin-parameters/#access) require the same team/audience; Deck Lab independently checks the signed token and maps its email to a configured profile.
6. **Merge blocks into your existing `decklab/config.json`.** Keep the profiles/timezone from step 4 and add each permitted person's lowercase email to that existing profile's `emails` array. An Access Allow policy does not create a Deck Lab profile or make its space Public.

   ```json
   {
     "allowed_hosts": ["decklab.example.com"],
     "tunnel": {"config": "~/.cloudflared/config.yml", "hostname": "decklab.example.com"},
     "access": {"team": "example-team", "aud": "ACCESS-APPLICATION-AUD", "port": 8644}
   }
   ```

   This snippet is not a replacement for your whole config. Both config files and the credentials/cert stay private. On Linux/macOS use `chmod 600` on their individual files; do not publish a tunnel credential, cert.pem, team policy or real hostname in this public repo.
7. **Check and start deliberately.** Run `cloudflared tunnel --config /path/to/config.yml ingress validate` (using your actual config path), then `python -m decklab.doctor`. Start/restart the installed Deck Lab service and run `python -m decklab.lib.homenet status`: it checks the credentials/config path, loopback ingress and tunnel state. Deck Lab runs `cloudflared tunnel --config <path> --no-autoupdate run` itself. Test the HTTPS hostname from an outside browser: Access should require your permitted email, and Deck Lab should show only what that profile may read. A tunnel login does not override private deck/inventory/kit permissions.

For port/path/credential diagnostics and updating cloudflared, use the [From outside the home reference](decklab/README.md#from-outside-the-home). On a background install the tunnel ends with Deck Lab. An abruptly killed foreground process can leave a tunnel behind, so use normal stop. The off-page Worker and wake-on-request are separate optional setup, not prerequisites for this tunnel. These instructions do not create a DNS record, policy, tunnel or deployment automatically.

## 11. Moving Deck Lab to another PC

For moving a working Deck Lab, with its data, to another computer (a spare PC that will be the server, say). The data moves as one database dump, checked on arrival against a digest of every table taken on the old PC. Deck Lab is off from the start of step B until step C's smoke test.

### A. Set up the new PC (the old one keeps running)

1. Follow steps 1 to 8 on the new PC, with these differences:
   - **PostgreSQL:** the same major version as the old PC, or newer (`python -m decklab.db sql "select version()"` on the old PC says which). A dump from a newer PostgreSQL can't be restored into an older one.
   - **The code:** on the same commit as the old PC, or newer. `restore` refuses a dump with migrations the checkout doesn't have.
   - **`config.json` (step 4):** copy it from the old PC, then change what's different there: `forge_dir`, `forge_java`, `database.pg_bin`, `database.backup_dir`, `database.staging_dir`, `database.export_repo`, `records_repo`, the tunnel's `config` and its `cloudflared` path, if set. While both PCs exist, give the new one its own `backup_dir` (a subfolder will do), so their nightly runs never prune each other's dumps.
   - **Take the `tunnel` block out for now.** Two PCs running the same tunnel share its visitors between two databases. If the old PC runs a tunnel, install `cloudflared` on the new one now (`winget install Cloudflare.cloudflared`, or on Linux from pkg.cloudflare.com, step 10) and check `cloudflared --version`.
2. `python -m decklab.db setup` makes the database roles and their pgpass lines, and an empty database that step B replaces.
3. Clone the repos the old PC uses beside the code: the export repo (`database.export_repo`, by default `../DeckLabData`, from its private remote) and `records_repo`, if set. Store the export repo's git credentials for the user the nightly task runs as, so its push never asks for a sign-in (on Linux, an SSH deploy key: step 9).
4. Don't install the background server or the nightly task yet. `python -m decklab.smoke --no-server` should pass, apart from warnings about what isn't installed yet.

### B. Move the data

On the old PC, turn off everything that could start Deck Lab or write to its data again, then take the dump and the digest:

```
python -m decklab.lib.homenet remove
python -m decklab.db schedule remove
python -m decklab.db backup --dest <a folder to carry>
python -m decklab.db digest -o <that folder>/digest.json
```

Take the `tunnel` block out of the old PC's `config.json` too. (`homenet stop` alone isn't enough: a server installed `--at-logon` starts again at the next logon, and with it its tunnel.) To go back to the old PC at any point before the switch-over, undo these: `homenet install --at-logon`, `schedule install`, and the `tunnel` block back.

`backup` prints the dump's name (`decklab-YYYY-MM-DD-HHMMSS.dump`). Take the folder to the new PC (a USB stick, or a share both reach), with these folders of `decklab/data` if you want them: `forge/results` (saved matchups), `forge/experiments` (Lab experiments) and `goldfish` (practice-hand results). The rest of `decklab/data` is caches the new PC fills itself, or settings of the old PC's own: after the move, set the Forge worker limit again on the Settings page (it's kept outside the repo, in the forge-slots folder), and measure the time estimates again on the new PC (`rates.json`: the reference’s [The overnight run](decklab/README.md#the-overnight-run-measuring-on-an-idle-pc)) rather than copying the old one. If a member change made on the Settings page didn't finish (`decklab/data/profile-config/pending.json` is there), run `python -m decklab.db sync-profiles` on the old PC before the dump.

On the new PC:

```
python -m decklab.db restore <the folder>/decklab-....dump --expect <the folder>/digest.json --replace
```

It restores into a database of its own first, checks every table's row count and contents against the digest, checks that this checkout knows every migration the dump has and applies any newer ones, and only then swaps it in: the database it replaces is renamed `decklab_before_restore` (kept until the next restore), and the restored one takes its name. If anything fails, the new PC's database is left as it was. `--replace` is needed because `setup` made one. A database already holding decks or cards needs `--force` as well. `python -m decklab.db digest --compare <the folder>/digest.json` checks it again any time. To try a dump first without touching the database Deck Lab uses, restore it under another name with `DECKLAB_DB_NAME` set for that one command (`DECKLAB_DB_NAME=decklab_trial python -m decklab.db restore ... --expect ...`; decklab/README.md, "Backups", has the PowerShell form and how to drop it afterwards).

### C. Switch over

On the new PC:

1. Put the `tunnel` block back in `config.json`, and copy the tunnel's files from the old PC: its config (`tunnel.config`, such as `~/.cloudflared/config.yml`) and the credentials file it names, fixing that path for this PC.
2. Bring the export repo up to date with the old PC's last export: `git -C <export_repo> pull --ff-only`.
3. Install the background server and the nightly task, so they come back by themselves after a restart (step 9, and the reference’s [Network setup (once, as administrator)](decklab/README.md#network-setup-once-as-administrator) for the firewall):
   ```
   python -m decklab.lib.homenet install --at-logon
   python -m decklab.db schedule install
   ```
   On Windows both run in your signed-in session, so a server PC should sign in by itself after a restart (or stay signed in). On Linux, turn on lingering (`loginctl enable-linger`) so they start at boot, and add the firewall rule from step 7 if a firewall is on.
4. Copy the folders from `decklab/data` into the same places, if you brought them.
5. `python -m decklab.smoke`. Every part should pass now; a warning that no backup has worked yet goes after the first nightly run, or a `python -m decklab.db backup`.
6. Phones and tablets on the Wi-Fi need the new PC's address (`homenet status` lists it). The tunnel's address doesn't change.

On the old PC, once the new one works:

1. Rename its copy of the database, so no command there writes to the old data by mistake. On Windows: `& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -h localhost -U decklab_owner -d postgres -c "alter database decklab rename to decklab_before_move"` (the folder of your version, or `database.pg_bin`). On Linux and macOS, `psql` with the same arguments. Every `python -m decklab.db` command there then says the database can't be reached. Drop it when you no longer want it as a fallback.
2. If the old PC is where the code is written, keep PostgreSQL installed there: the database integration tests make throwaway databases on the server `config.json` names, so never point that config at the new PC's live database.

The command line's inventory, deck and wishlist commands work on the database `config.json` names, so after the move run them on the new PC (in person, or over Remote Desktop or SSH).

### D. From a Windows server to a Linux one

The same route, A to C, in order, with what's different for Linux. Nothing Linux-only is needed for the data itself: the dump, the digest and `restore` are the same on both, and a dump recorded on Windows still matches its counts and digests on Linux.

1. **Install** (step 1, with its installer disk choices): git, Python 3.14 (Ubuntu 26.04's own, else uv or deadsnakes), PostgreSQL of the old PC's major version or newer (Ubuntu 26.04's `postgresql-18`, else apt.postgresql.org; `python -m decklab.db sql "select version()"` on the old PC says which, and so does a dump: `pg_restore -l <the dump>`'s "Dumped from database version" line), an OpenJDK 21 or later JDK, `tesseract-ocr`, `avahi-daemon`, and `cloudflared` from pkg.cloudflare.com. Set the time zone with `timedatectl`.
2. **The code** (steps 2 and 3): `git clone` it, on the old PC's commit or newer; don't copy the Windows folder. Make the `.venv` with `.venv/bin/python -m pip install -r decklab/requirements.txt`.
3. **`config.json`** (step 4): copy it over, `chmod 600` it, and change every Windows path to an absolute Linux one (Deck Lab refuses the ones it reads as folders): `forge_dir`, `forge_java` (the JDK's real path), `database.backup_dir` (the NAS mount, step 9), `staging_dir`, `export_repo`, `pg_bin` (or leave it out), `records_repo` and `tunnel.config`. Add `"timezone"`, and `"home_networks"` if anyone visits through a VPN. Take the `tunnel` block out for now.
4. **The database** (step 5): `python -m decklab.db setup` as yourself, not with `sudo` ("When something goes wrong" below has the pg_hba.conf and locale fixes). Then `python -m decklab.lib.cards update`.
5. **Forge** (step 8): download and check the release, unzip it into the folder above `forge_dir` (such as `~/tools`) and rename it to `forge_dir`'s last folder, or point `forge_dir` at the folder it made, then `python -m decklab.lib.forge status` and `python -m decklab.lib.forge cardlog-check`.
6. **Backups and the export repo** (step 9): mount the NAS share through `/etc/fstab`, clone the export repo and `records_repo`, each with its own SSH deploy key (step 9), and check a dry-run push. Step 9's "Backups the server itself can't destroy" is worth doing now too.
7. **Check:** `python -m decklab.smoke --no-server` passes, apart from warnings about what isn't installed yet.
8. **Move the data** (B): on the Windows PC, `homenet remove`, `schedule remove`, `backup --dest`, `digest -o`, and take its `tunnel` block out. On the Linux PC, `python -m decklab.db restore <the folder>/decklab-....dump --expect <the folder>/digest.json --replace`.
9. **Switch over** (C): copy `config.yml` and the credentials JSON into `~/.cloudflared`, fix `config.yml`'s `credentials-file:` to `/home/<you>/.cloudflared/<tunnel id>.json`, `chmod 600` both, and put the `tunnel` block back. `git -C <export_repo> pull --ff-only`. Then:
   ```
   loginctl enable-linger
   python -m decklab.lib.homenet install --at-logon
   python -m decklab.db schedule install
   ```
   Copy `forge/results`, `forge/experiments` and `goldfish` into `decklab/data`, add the firewall rule if a firewall is on, and set the worker limit again on Settings.
10. **Check again:** `python -m decklab.update --dry-run` (it should find nothing to change), then `python -m decklab.smoke`. Phones need the new address, which `homenet status` lists under Addresses (also `http://<the PC's name>.local:8642`). For sleeping and waking, follow step 12's Linux steps.
11. **The old PC:** rename its database as in C.

## 12. Let the server sleep (optional)

A PC that serves Deck Lab all day uses power all day. With an always-on device on the same network that can run a small container (a NAS), the PC can sleep when idle and wake whenever anyone opens Deck Lab, at home or through the tunnel; the visitor waits under a minute, with a page saying so. The reference’s [Sleeping and waking on request](decklab/README.md#sleeping-and-waking-on-request) explains how it works.

1. **The PC:** check `powercfg /a` lists "Standby (S3)". Turn on Wake-on-LAN in the BIOS. On the wired network adapter (Device Manager), set "Wake on Magic Packet" and tick "Allow this device to wake the computer" and "Only allow a magic packet to wake the computer". Give the PC a DHCP reservation in the router, and note its MAC address (`getmac /v`). Allow wake timers on mains power, so the nightly backup can wake the PC: Control Panel, Power Options, Change plan settings, Change advanced power settings, Sleep, "Allow wake timers", Plugged in: Enable (or `powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1`, then `powercfg /setactive SCHEME_CURRENT`).
2. **The wake gate on the NAS:** follow [decklab/wakegate/README.md](decklab/wakegate/README.md). Check `http://<the NAS>:8650/__status` says the PC is awake.
3. **`config.json`:** add `"wake": {"idle_minutes": 20, "gate": "http://<the NAS>:8650"}`, restart Deck Lab (`python -m decklab.lib.homenet restart`) and run `python -m decklab.db schedule install` again, so the nightly task wakes the PC.
4. **Windows' sleep timeout:** a few minutes (Settings, Power). Deck Lab keeps the PC awake while it's in use, and a command-line Forge run (`python -m decklab.lib.forge play ...`) keeps it awake by itself until it ends. The page's timer polls never wake the PC, at home or through Cloudflare: only opening a page and things you do there do.
5. **From outside (if you set up step 10):** the NAS tunnel, the Access service token and the Worker's three secrets, in the wake gate's README.
6. **Check:** `python -m decklab.lib.homenet status` (its Wake area) and `python -m decklab.smoke`. Then let it sleep, open the gate's address on a phone, and time the wake.

On a Linux PC, do these in place of steps 1, 3, 4 and 6; the wake gate (step 2) and outside access (step 5) are the same:

1. **The PC:** turn on Wake-on-LAN in the BIOS, and keep it on at every boot, the way your network is managed (`networkctl list` showing your adapter as `configured` means systemd-networkd; a missing `nmcli` means no NetworkManager):
   - **Netplan** (`/etc/netplan/` has files; Ubuntu Server's default, over systemd-networkd): write a file of its own, which netplan merges with the installer's, then `sudo chmod 600` it and `sudo netplan generate`. Match the adapter by its MAC address (`ip link` shows it as `link/ether`) and keep its name with `set-name`: netplan's documentation warns that `wakeonlan` on an adapter matched only by name may never be applied. It takes effect at the next boot (`sudo ethtool -s <adapter> wol g` arms it now):
     ```
     # /etc/netplan/60-wake-on-lan.yaml
     network:
       version: 2
       ethernets:
         <adapter>:
           match:
             macaddress: <its MAC address>
           set-name: <adapter>
           wakeonlan: true
     ```
     To check it survives a boot, shut the PC down fully (some adapters keep the setting through a restart) and start it again, then `sudo ethtool <adapter>`. `udevadm info /sys/class/net/<adapter> | grep LINK_FILE` should name netplan's `10-netplan-<adapter>.link`.
   - **NetworkManager** (desktops): `sudo nmcli connection modify <connection> 802-3-ethernet.wake-on-lan magic` (`nmcli connection show` lists them).
   - **systemd-networkd without netplan:** `WakeOnLan=magic` in the adapter's `.link` file. Netplan writes its own `.link` file, and only the first `.link` file that matches an adapter counts, so don't add one beside netplan's: one without the usual naming settings can rename the adapter and leave a headless PC off the network.

   `sudo ethtool <adapter>` should show `Wake-on: g`. Use the wired adapter: Wi-Fi usually can't wake. `cat /sys/power/mem_sleep` should show `[deep]`; if it shows `[s2idle]`, add `mem_sleep_default=deep` to the kernel command line. Give the PC a DHCP reservation and note its MAC address (`ip link`).
2. **Let it sleep when idle.** A Linux PC with no desktop never suspends by itself. As root, write `/etc/systemd/logind.conf.d/decklab.conf`:
   ```
   [Login]
   IdleAction=suspend
   IdleActionSec=10min
   ```
   and restart the PC. An open SSH or terminal session that isn't idle keeps it awake, so log out of them. Desktop power settings aren't read.
3. **Let Deck Lab hold it awake.** While in use, Deck Lab holds `systemd-inhibit --what=sleep:idle --who="Deck Lab" --mode=block` (`systemd-inhibit --list` shows it; while it's held, `systemctl suspend` fails unless given `-i`). polkit may refuse that to a service with no login session: the smoke test's "Keeping the PC awake" step says so, and `/api/status`'s `keep_awake` shows `"wanted": true` with `"holding": false`. Deck Lab logs the refusal once and tries again every 5 minutes. To allow it, write `/etc/polkit-1/rules.d/50-decklab-inhibit.rules` as root, with your user name:
   ```
   polkit.addRule(function(action, subject) {
       if ((action.id == "org.freedesktop.login1.inhibit-block-sleep" ||
            action.id == "org.freedesktop.login1.inhibit-block-idle") && subject.user == "<you>")
           return polkit.Result.YES;
   });
   ```
   `pkaction --verbose --action-id org.freedesktop.login1.inhibit-block-sleep` shows what's allowed by default.
4. **`config.json`:** add the `"wake"` block as above and `homenet restart`.
5. **Wake for the nightly run.** A user timer can't wake the PC, so `python -m decklab.db schedule wake-timer` prints the `sudo` commands that install a system timer, `decklab-wake.timer`, which wakes the PC a minute before 03:30 (`--at HH:MM` for another time), and the commands that take it away again. Deck Lab never installs it itself, and `schedule status` warns while `"wake"` is set and it isn't there. The wake timer counts 03:30 in `config.json`'s `"timezone"`, as the nightly timer does (the PC's own zone when it isn't set), so print and install it again after changing `"timezone"`.
6. **Check** as above: Linux `homenet status` has Sleep lines (logind's IdleAction, a masked `suspend.target`, and with `"wake"` whether Deck Lab may hold the PC awake) and, with `"wake"`, Wake lines (`mem_sleep`, the adapter's Wake-on, the wake timer and the gate).

Phones and tablets bookmark the gate's address instead of the PC's. A Deck Lab page already open at home hops through the gate when it can't reach the PC only if it was opened at exactly the address the gate sends people to (the wake gate's `DECKLAB_PC_HOST` and port, such as `http://<the PC's address>:8642`), so open Deck Lab at home by that address or the gate's bookmark, not `localhost` or another name for the PC. A save that fails while the PC sleeps never navigates away: it shows the usual can't-be-reached error, and your change stays on the page to try again. On Windows the server and the nightly task run in your signed-in session, so the PC should sign in by itself after a restart. On Linux, lingering (step 9) starts them at boot.

## Restoring from a backup

After completing core steps 1–5 on the replacement PC and restoring your private config to the new checkout, stop Deck Lab before replacing its database. Use the newest known-good dump from your backup folder and the same or a newer PostgreSQL major version:

```sh
python -m decklab.lib.homenet stop
python -m decklab.db restore /path/to/decklab-newest.dump --replace --force
python -m decklab.lib.homenet start
python -m decklab.smoke
```

Use your actual dump path (quote paths with spaces). `--replace --force` intentionally replaces the target database, so confirm it is the install you are recovering. A lost disk does not require an old digest.json. On a terminal-only platform stop/restart the foreground server manually; see the platform reference. See the full [Database reference](decklab/README.md#database) for restore checks and backups.

## Platform and acceptance reference

| | Windows 10 or 11 | Linux | macOS |
|---|---|---|---|
| The server, the database, the pages, the command line | Yes | Yes | Yes |
| Forge simulations | Yes | Yes (the same download, with a JDK 21 or later) | Yes (the same download) |
| Starting in the background and at logon (`homenet install`) | Yes (Task Scheduler) | Yes (a systemd user service) | No: run the server in a terminal, or under launchd |
| The firewall script (`decklab/network-setup.ps1`) | Yes | No: a firewall rule of your own (step 7), which `homenet status` checks for firewalld and ufw | No |
| `homenet status`'s network, address, sleep and wake checks | Yes | Yes | No |
| The nightly backup task (`python -m decklab.db schedule`) | Yes (Task Scheduler) | Yes (a systemd user timer) | No: run `python -m decklab.db nightly` from cron |
| Photo scanning (Scan cards, Scan token cards) | Yes (Windows' own OCR engine, nothing to install) | Yes, with the `tesseract-ocr` package | With Tesseract |
| Keeping the PC awake while in use, and waking on request (step 12) | Yes (a power request) | Yes (`systemd-inhibit`) | No |

Deck Lab is built and used every day on Windows. On Linux the whole test suite passes, and CI runs it there on every change, beside Windows, together with a check that installs, restarts, stops and removes the systemd service and timer under a real systemd. Since 2026-11-01 the live server can run on Linux too (story E11-S58): keeping the PC awake, photo scanning with Tesseract, Forge games and waking from sleep are built and fixture-tested. A full install in WSL's Ubuntu (2026-11-02) has run the database, backups, the services, keeping the PC awake and real Forge games; waking from sleep and scanning real card photos are still to be tried on a real Linux server PC.

Whatever the system, the home listener (port 8642) answers only addresses on a home network: loopback, the private IPv4 ranges (10/8, 172.16/12, 192.168/16), link-local addresses and IPv6's private ranges (fc00::/7, fe80::/10). Anything else gets 403 "This address only takes visits from the home network." A VPN such as Tailscale uses other addresses (100.64.0.0/10): add them to `config.json` as `"home_networks": ["100.64.0.0/10"]`. The tunnel's listener (step 10) isn't affected.

## When something goes wrong

- **Config isn't valid JSON:** use the line/column in the error, check commas and JSON path escaping, then run `python -m decklab.doctor`.
- **Python version is not 3.14:** reopen the right shell and verify `python --version`; recreate the venv with that interpreter before installing requirements.
- **Port in use:** choose `--port` or config.json's `port`; an already running Deck Lab names its stop command.
- **A phone cannot connect:** first open localhost on the server, then run `python -m decklab.lib.homenet status` there and use its home address. Check the same Wi-Fi, private-network firewall rule and selected port.
- **Forge or Java is unavailable:** simulations are optional. `python -m decklab.lib.forge status` names the expected files/version; see step 8.
- **Logs:** `decklab/data/logs/server.log` records startup; `decklab/data/logs/db.log` records database causes. Review them locally, since they may contain private configuration details.

- **"no password supplied"** from `setup`: run it in a terminal, so it can ask, or add the pgpass line from step 5.
- **"nothing answered", "connection refused" or "connection timeout expired":** check that PostgreSQL is running and `database.host`/`database.port` name its listener. On Windows, `Get-Service postgresql*` in PowerShell lists the service; on Linux, use `systemctl status postgresql`. Start the installed service if stopped, then run `python -m decklab.db status`. An unclassified connection error is not proof the service is down; `decklab/data/logs/db.log` on the PC holds its detail.
- **PostgreSQL answered but Deck Lab couldn't sign in, or its database/roles don't exist:** run `python -m decklab.db setup` on the PC. A refused `postgres` password on Windows has the reset procedure below. Setup refuses PostgreSQL older than 16 before creating roles or a database.
- **"Ident authentication failed", "Peer authentication failed" or "no pg_hba.conf entry"** on Linux: PostgreSQL doesn't take a password on `127.0.0.1`. `sudo -u postgres psql -c "show hba_file"` says where its `pg_hba.conf` is: set the `host` lines for `127.0.0.1/32` and `::1/128` to `scram-sha-256`, then `sudo systemctl reload postgresql`. Give `postgres` a password (step 5) and run `python -m decklab.db setup` again as yourself, not with `sudo`.
- **A locale or encoding error** from `setup`, `restore` or the restore check: the PostgreSQL cluster needs a UTF-8 (or C) locale. Make it again with `initdb --locale=C.UTF-8` (or your own UTF-8 locale, such as `en_AU.UTF-8`).
- **"Failed to connect to bus"** from `homenet` or `schedule` on Linux: `systemctl --user` can't find your session (after `sudo -u`, `su` or from cron). Log in as that user over SSH, or `export XDG_RUNTIME_DIR=/run/user/$(id -u)`, with lingering on.
- **A phone gets "This address only takes visits from the home network."**: it came from an address outside the home ranges, such as a VPN's. Add that network to `"home_networks"` in `config.json` and restart Deck Lab. The server's log names each refused address once.
- **"the database holds no inventory"** or **"the database holds no decks":** run `python -m decklab.db setup` again. It starts the empty collection and deck library on a new database.
- **The page says the card data isn't ready:** wait for the download, or run `python -m decklab.lib.cards update` and read what it says.
- **The server's log** is `decklab/data/logs/server.log` when it runs in the background.

### Windows postgres password reset

Use this only for the local PostgreSQL installation you administer when its `postgres` password is forgotten. Stop Deck Lab first and keep this recovery window short: temporary `trust` authentication lets local programs connect as `postgres`. Never enable it for a network range or all users/databases.

1. In an administrator PowerShell, run `Get-Service postgresql*` and note the installed service name (for example `postgresql-x64-18`). Find that installation's data folder and save a copy of `pg_hba.conf` so its original authentication can be restored.
2. Add these temporary lines **before** other matching host rules:

   ```text
   host postgres postgres 127.0.0.1/32 trust
   host postgres postgres ::1/128      trust
   ```

3. Restart that installed service, for example `Restart-Service postgresql-x64-18`. Open its `psql` from PowerShell (change `18` if another version is installed):

   ```powershell
   & 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -h 127.0.0.1 -U postgres -d postgres
   ```

   At the `psql` prompt, enter `\password postgres`, type the new password twice, then `\q`. The password is prompted, never placed in a command line or config.json.
4. Immediately restore the original `pg_hba.conf` (removing both temporary lines), and restart the same PostgreSQL service again. Keep its original password authentication, normally `scram-sha-256`.
5. Verify the new password with `psql -h 127.0.0.1 -U postgres -d postgres -W` from the same installation, then `\q`. Run `python -m decklab.db setup` and `python -m decklab.doctor` from the Deck Lab folder.

PostgreSQL uses the [first matching authentication rule](https://www.postgresql.org/docs/current/auth-pg-hba-conf.html); on Windows changes also apply to new connections immediately. The interactive [psql password command](https://www.postgresql.org/docs/current/app-psql.html) avoids putting a new password in shell history. These are recovery instructions, never steps Deck Lab runs automatically.
