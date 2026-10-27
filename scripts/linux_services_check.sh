#!/usr/bin/env bash
# Linux's background running from end to end, under a real systemd user manager (E11-S33):
# the nightly timer (python -m decklab.db schedule) and the server's service (python -m
# decklab.lib.homenet), installed, checked, restarted after a crash, stopped and removed.
# CI's linux-services job runs it; on your own PC it leaves nothing installed when it passes.
#
# Run from the repo root, with the Python you run Deck Lab with as $PYTHON (default python3),
# a .venv holding psycopg and a decklab/config.json. It uses port 18642 and listens on
# 127.0.0.1 only, so it doesn't touch a Deck Lab on 8642. It needs no database.
set -euo pipefail
PYTHON=${PYTHON:-python3}
PORT=18642
URL="http://127.0.0.1:$PORT/api/status"

step() { echo; echo "== $*"; }
answers() { curl -fsS --max-time 2 "$URL" > /dev/null 2>&1; }
wait_until() {      # wait_until SECONDS COMMAND...: true once COMMAND succeeds
  local until=$((SECONDS + $1)); shift
  until "$@"; do
    [ "$SECONDS" -lt "$until" ] || return 1
    sleep 1
  done
}
refute() {          # refute COMMAND...: fails when COMMAND succeeds (set -e ignores a "! COMMAND")
  if "$@"; then echo "Unexpectedly true: $*" >&2; return 1; fi
}
says() {            # says TEXT COMMAND...: runs COMMAND (any exit code), shows and checks what it said
  local text=$1 out; shift
  out=$("$@" 2>&1) || true
  echo "$out"
  grep -qF -- "$text" <<< "$out" || { echo "Missing: $text" >&2; return 1; }
}
main_pid() { systemctl --user show decklab.service -p MainPID --value; }
cleanup() {
  "$PYTHON" -m decklab.lib.homenet remove --port "$PORT" > /dev/null 2>&1 || true
  "$PYTHON" -m decklab.db schedule remove > /dev/null 2>&1 || true
}
trap cleanup EXIT

step "The nightly timer"
"$PYTHON" -m decklab.db schedule install
systemctl --user is-enabled decklab-nightly.timer
systemctl --user is-active decklab-nightly.timer
says "Next run:" "$PYTHON" -m decklab.db schedule status
refute grep -q WARNING <<< "$("$PYTHON" -m decklab.db schedule status)"

step "The server's service"
"$PYTHON" -m decklab.lib.homenet install --at-logon --host 127.0.0.1 --port "$PORT"
systemctl --user is-enabled decklab.service
answers
# (status exits 1 here: listening on 127.0.0.1 only is a problem for phones.)
says "Service: decklab.service is installed (starts at logon); it's active (running)" \
  "$PYTHON" -m decklab.lib.homenet status --port "$PORT"

step "Restart: a new process answers"
before=$(main_pid)
"$PYTHON" -m decklab.lib.homenet restart --port "$PORT"
answers
[ "$(main_pid)" != "$before" ]

step "A crash: systemd starts it again"
before=$(main_pid)
kill -9 "$before"
wait_until 60 answers
[ "$(main_pid)" != "$before" ]

step "Stop: it stops cleanly and stays stopped"
"$PYTHON" -m decklab.lib.homenet stop --port "$PORT"
refute systemctl --user is-active --quiet decklab.service
[ "$(systemctl --user show decklab.service -p Result --value)" = success ]
sleep 12                                       # longer than RestartSec
refute answers
[ ! -e decklab/data/server.json ]              # the server cleared its state on the way out

step "A server in a terminal: stopped from another one with SIGTERM"
"$PYTHON" decklab/server.py --host 127.0.0.1 --port "$PORT" --no-update > /dev/null 2>&1 &
terminal=$!
wait_until 30 answers
"$PYTHON" decklab/server.py --port "$PORT" --stop
wait "$terminal"                               # exits 0: a clean stop, not killed
refute answers

step "Remove both"
"$PYTHON" -m decklab.lib.homenet remove --port "$PORT"
"$PYTHON" -m decklab.db schedule remove
[ ! -e "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/decklab.service" ]
[ ! -e "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/decklab-nightly.timer" ]
trap - EXIT
echo; echo "Linux services: all checks passed."
