# Running your own Deck Lab

This guide sets up Deck Lab on your own computer, from nothing, for you and your household. It covers the parts every install needs (Python, PostgreSQL, the card data, the first run) and then the optional parts: Forge simulations, starting in the background, and reaching it from outside your home.

[decklab/README.md](decklab/README.md) is the full reference for every page and command. It was written for one household's PC, so it names that PC's folders (`C:\VSProjects\...`, `C:\Tools\...`) and people. Wherever it does, use your own.

## What runs where

| | Windows 10 or 11 | Linux | macOS |
|---|---|---|---|
| The server, the database, the pages, the command line | Yes | Yes | Yes |
| Forge simulations | Yes | Yes (the same download, with a JDK 21 or later) | Yes (the same download) |
| Starting in the background and at logon (`homenet install`) | Yes (Task Scheduler) | Yes (a systemd user service) | No: run the server in a terminal, or under launchd |
| The firewall script (`decklab/network-setup.ps1`) and `homenet status`'s network checks | Yes | No: open the port in your own firewall | No |
| The nightly backup task (`python -m decklab.db schedule`) | Yes (Task Scheduler) | Yes (a systemd user timer) | No: run `python -m decklab.db nightly` from cron |

Deck Lab is built and used every day on Windows. On Linux the whole test suite passes, and CI runs it there on every change, beside Windows, together with a check that installs, restarts, stops and removes the systemd service and timer under a real systemd.

## 1. What to install

- **Git**, to get the code.
- **Python 3.14.** On Windows, the python.org installer. On Linux or macOS, if your system has an older Python, [uv](https://docs.astral.sh/uv/) installs one beside it: `uv python install 3.14`. Use that Python (`uv python find 3.14` prints where it is) wherever this guide says `python`.
- **PostgreSQL 16 or later.** On Windows, the installer from postgresql.org; it asks you to choose a password for the `postgres` superuser. Remember it for step 4. On Linux, your distribution's `postgresql` package. On macOS, Postgres.app or Homebrew.
- **For simulations only:** a JDK 21 or later (the full JDK, with `javac` and `jar`) and Maven. See step 8.

## 2. Get the code

```
git clone https://github.com/matt439/DeckLab
cd DeckLab
```

Run every command in this guide from that folder, the repo root.

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

Copy the example and change the profile to yours:

```
cp decklab/config.example.json decklab/config.json
```

(`copy` instead of `cp` in a Windows command prompt.)

```json
{
  "profiles": [
    {"id": "alex", "name": "Alex", "plays_as": "user", "role": "admin", "space": "home", "emails": []}
  ]
}
```

- `id` is lowercase letters, digits and hyphens, and `name` is what the page shows.
- `role` `admin` may change everything at home. Give the first profile that role.
- `space` `home` is the household's shared collection and decks.
- `plays_as` says whose decks are whose at home: `user` for the first home player, `wife` for the second, and a deck's **Played by** can also be `either`. The words are the original household's and only label decks.
- `emails` is used only for logins from outside the home (step 10). Leave it empty.

To add a second person who shares your cards, add another profile with `"space": "home"`, `"role": "member"` and `"plays_as": "wife"`. Someone with a collection of their own gets `"space"` set to their own `id` and no `plays_as`. The reference's "People's own collections (spaces)" explains what each can see and change.

`config.json` is gitignored, so your names and addresses never end up in a commit. The other settings all have defaults. [decklab/config.full.example.json](decklab/config.full.example.json) shows the optional blocks for a backup folder, outside access through Cloudflare and a records repo.

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

```
python decklab/server.py
```

Open http://localhost:8642 and pick yourself on **Who are you?**. Ctrl+C stops the server.

- **Only this computer:** `python decklab/server.py --host 127.0.0.1`. Without `--host`, Deck Lab listens on every network interface, so phones and tablets on your Wi-Fi can open `http://<this computer's address>:8642`. On Windows, the first start may ask about Python's network access: allow it on private networks, or run the firewall script (reference, "Network setup (once, as administrator)").
- **Another port:** `--port 8650`, or `"port"` in `config.json`.

Some first steps:

- **Collection page, More, Import cards…:** a ManaBox, Moxfield, Deckbox or collection-columns CSV export.
- **Collection page, More, Add a precon…:** a published precon's cards, with its deck.
- **Decks, New deck:** write or paste a deck list. Owned versus needed works from your collection.

## 8. Forge simulations (optional)

Matchups play full games with [Forge](https://github.com/Card-Forge/forge)'s computer players. Deck Lab needs its own build of Forge, from the fork [matt439/forge](https://github.com/matt439/forge), branch `decklab`, which adds the hooks the card log and game patches use. Deck Lab works without it: only the Matchups and Lab pages need it.

You need a **Java JDK 21 or later** (a full JDK, with `javac` and `jar`: the card log is compiled on your PC), such as [Eclipse Temurin](https://adoptium.net/). Then get Deck Lab's Forge one of two ways.

### Download it (the usual way)

1. **Download the release** Deck Lab expects: [2.0.15-decklab-52387e83f](https://github.com/matt439/forge/releases/tag/2.0.15-decklab-52387e83f) (it's `RELEASE` in [decklab/lib/forge/simjar.py](decklab/lib/forge/simjar.py)). It's Forge 2.0.15 with the fork built in. Get both files: `forge-2.0.15-decklab-52387e83f.zip` and its `.zip.sha256`.
2. **Check the checksum** matches the one in the `.sha256` file and the release's notes:
   - Windows (PowerShell): `Get-FileHash forge-2.0.15-decklab-52387e83f.zip -Algorithm SHA256`
   - Linux: `sha256sum -c forge-2.0.15-decklab-52387e83f.zip.sha256`
   - macOS: `shasum -a 256 -c forge-2.0.15-decklab-52387e83f.zip.sha256`

   If it doesn't match, the download is damaged: delete it and download it again.
3. **Unzip it** somewhere of its own, such as `C:\Tools` or `~/tools`. It makes one folder, `forge-2.0.15-decklab-52387e83f`.
4. Go on with "Point Deck Lab at it" below.

### Or build it from source

Only if you want to change Forge itself, or no release fits your Deck Lab. It needs Maven as well as the JDK.

1. **Download the Forge 2.0.15 release** from [Forge's releases](https://github.com/Card-Forge/forge/releases/tag/forge-2.0.15) (the desktop archive) and unpack it into a folder of its own, such as `C:\Tools\forge` or `~/forge-2.0.15`. It should hold one `forge-gui-desktop-2.0.15-jar-with-dependencies.jar` and a `res` folder. The build copies its `res` folder and launch scripts, and never changes it.
2. **Clone the fork with its history.** The build compares the branch with the `forge-2.0.15` tag, so don't make a shallow clone:
   ```
   git clone -b decklab https://github.com/matt439/forge forge-decklab-src
   ```
   Deck Lab trusts the card log only from the fork build it was checked with: `RELEASE` in [decklab/lib/forge/simjar.py](decklab/lib/forge/simjar.py), such as `2.0.15-decklab-52387e83f`. If the branch has moved on since, check out that commit (`git checkout 52387e83f`). Any other build still plays matchups, but with plain Forge and without per-card stats.
3. **Build and install it** with `JAVA_HOME` set to the JDK and Maven on the PATH. From the fork's folder:
   ```
   python decklab/install.py --release <the release folder> --out <where to install it>
   ```
   The first build downloads Maven's dependencies and takes several minutes. The `--out` folder is made new; nothing else is changed.

### Point Deck Lab at it

1. **Set `forge_dir`** in `config.json` to the folder you unzipped or installed:
   ```json
   "forge_dir": "<that folder>",
   ```
   Deck Lab looks for Java in `C:\Program Files\Java\jdk-*`, then `JAVA_HOME`, then (off Windows) the PATH. Set `"forge_java"` to the JDK's `java` (`java.exe` on Windows) if it picks the wrong one.
2. **Check it:** `python -m decklab.lib.forge status` says whether Forge is ready, and its `build:` line whether it's the build this Deck Lab expects (and what to download if not). Then run `python -m decklab.lib.forge cardlog-check` once: it plays a few games several ways and turns on the card log when they match.

Deck Lab runs up to 16 Forge workers at once, each with up to 1 GB of memory. That suits a 16-core PC with 32 GB or more. On a smaller one, set `"forge_workers"` in `config.json` to your number of cores or fewer (such as `"forge_workers": 4`), or admins can lower it on the Settings page.

## 9. Keep it running and backed up

- **Windows, in the background:** `python -m decklab.lib.homenet install --no-start`, then `python -m decklab.lib.homenet start` (the reference's "Start it" covers starting at logon and the restart watchdog).
- **Linux, in the background:** `python -m decklab.lib.homenet install --at-logon` writes a systemd user service, `~/.config/systemd/user/decklab.service`, which runs `python decklab/server.py --background` in the repo with the Python you ran install with, enables it and starts it. `start`, `stop`, `restart`, `remove` and `status` work as on Windows; without `--at-logon` it starts only when you run `homenet start`. If the server stops with an error, systemd starts it again after 10 seconds; `homenet stop` leaves it stopped. Its log is `decklab/data/logs/server.log` (and `journalctl --user -u decklab.service` shows what systemd saw). Give `install` the same `--port` and `--host` you'd give the server.
- **Linux, at boot:** systemd runs your own services only while you're logged in. For Deck Lab to start at boot and keep running after you log out, turn on lingering once: `loginctl enable-linger` (on some systems, `sudo loginctl enable-linger $USER`). `install` and `status` remind you while it's off.
- **macOS:** run `python decklab/server.py` under launchd, from the repo root.
- **Backups:** `python -m decklab.db backup` writes a dump to `decklab/data/backups/` and copies it to `database.backup_dir` in `config.json`, a folder on another disk or a NAS:
  ```json
  "database": {"backup_dir": "D:\\Backups\\DeckLab"}
  ```
  Set it on Windows, where the default is the original household's NAS share and the copy fails without it. Off Windows there's no default, and the dumps stay in `decklab/data/backups/` only.
- **The nightly job:** `python -m decklab.db nightly` runs the backup, its pruning, a restore check now and then, and the data's check. It also exports the data as plain files into a git repo of their own, `../DeckLabData` beside this repo, unless `database.export_repo` says where. `python -m decklab.db schedule install` runs it every night at 03:30: on Windows as a Task Scheduler task, on Linux as a systemd user timer (`decklab-nightly.timer` and `decklab-nightly.service` in `~/.config/systemd/user`), which catches up a night the computer was off, as soon as it's on again. `schedule status` shows the next and last run, and `schedule remove` takes it away. Run `schedule install` with the Python you run Deck Lab with, after installing psycopg (step 3), and again after moving the repo or upgrading Python; `status` warns when its units are out of date. Lingering (above) lets it run while you're logged out. On macOS, schedule it with cron.
- **pg_dump:** Deck Lab finds it in `C:\Program Files\PostgreSQL\<version>\bin` or on the PATH. Set `database.pg_bin` to its folder if it's somewhere else.
- **Updating:** `git pull`, then `python -m decklab.db migrate`, then restart the server.

To see the nightly units without installing anything (for another computer, say), `schedule preview-systemd` prints one, for the paths you give:

```
python -m decklab.db schedule preview-systemd --unit service --python /usr/bin/python3.14 --workdir /srv/DeckLab
python -m decklab.db schedule preview-systemd --unit timer --python /usr/bin/python3.14 --workdir /srv/DeckLab --at 03:30
```

To check the Linux services on your computer from end to end, `scripts/linux_services_check.sh` installs the timer and the service on port 18642, restarts the server, kills it to see systemd start it again, stops it and removes both (`PYTHON=<your python> scripts/linux_services_check.sh`).

## 10. From outside your home (optional)

Deck Lab can start a Cloudflare Tunnel itself, behind Cloudflare Access's email login. That needs a domain on Cloudflare, `cloudflared`, and `allowed_hosts`, `tunnel` and `access` blocks in `config.json` (see `config.full.example.json`, and the reference's "From outside the home"). Leave those blocks out of `config.json` until you set this up. Without them, Deck Lab serves your home network only.

## When something goes wrong

- **"no password supplied"** from `setup`: run it in a terminal, so it can ask, or add the pgpass line from step 5.
- **"can't reach PostgreSQL ... connection refused":** PostgreSQL isn't running, or it isn't on port 5432 (set `database.port` in `config.json`).
- **"the database holds no inventory"** or **"the database holds no decks":** run `python -m decklab.db setup` again. It starts the empty collection and deck library on a new database.
- **The page says the card data isn't ready:** wait for the download, or run `python -m decklab.lib.cards update` and read what it says.
- **The server's log** is `decklab/data/logs/server.log` when it runs in the background.
