"""Forge CLI soak probes: compare sampled warm-worker games with fresh processes."""
from . import cli_checks as checks
from . import cli_shared as shared


SOAK_NO_SERVER = "no live server pool on port {port}"
SOAK_RECENT_S = 15 * 60          # half a probe's games come from logs written in the last 15 minutes
SOAK_AT_ONCE = 4                 # fresh one-shot processes at once, each in a slot
SOAK_WARM_FEATURES = frozenset(("numbers", "seeds", "key", "kind", "log_dir"))


def _soak_probe_args(sub):
    probe = sub.add_parser("soak-probe", help="fresh-against-warm replays of sampled games (wave 3, the combined run)")
    probe.add_argument("--results-dir", required=True, action="append",
                       help="the results the logs' games belong to (repeat it with --logs-dir for pairs)")
    probe.add_argument("--logs-dir", required=True, action="append",
                       help="the tee'd chunk logs (<logs>/<key>/<first>-<last>.log.gz); each with the --results-dir "
                            "in the same place, or the one --results-dir")
    probe.add_argument("--server-port", type=shared._positive, required=True, help="the test server whose pool is probed")
    probe.add_argument("--constructed", type=int, default=35)
    probe.add_argument("--commander", type=int, default=0)
    probe.add_argument("--seed", type=int, default=0, help="the sampling's random seed")
    probe.add_argument("--out", help="the probe's JSON file")
    probe.add_argument("--ledger", help="the games probed so far (default: probed.json beside --out)")
    probe.add_argument("--json", action="store_true")


def _soak_server_live(port):
    """Is the Deck Lab server on 127.0.0.1:port up, with a pool service of this checkout answering?"""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as answer:
            answer.read(1)
    except Exception:
        return False
    for service in shared.pool.services():
        if service.get("checkout") == str(shared.config.REPO) and shared.pool.service_status(service) is not None:
            return True
    return False


def _soak_paired(key, results_dir):
    path = shared.common._results_dir(results_dir) / "paired" / f"{key}.json"
    try:
        data = shared.json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if shared.saved._is_result(data, key) else None


def _soak_logs(results_dir, logs_dir):
    """Every tee'd chunk log under logs_dir (searched to any depth) whose result is in results_dir
    (top level or paired/): [{"key", "path", "first", "last", "mtime", "result"}]."""
    found, results = [], {}
    root = shared.Path(logs_dir)
    if not root.is_dir():
        return found
    for path in sorted(root.rglob("*.log.gz")):
        m = shared.re.fullmatch(r"(\d+)-(\d+)\.log\.gz", path.name)
        key = path.parent.name
        if not m or not shared.re.fullmatch(r"[0-9a-f]{64}", key):
            continue
        if key not in results:
            results[key] = shared.saved.load(key, results_dir) or _soak_paired(key, results_dir)
        if results[key] is None or "seeds" not in results[key]:
            continue
        found.append({"key": key, "path": path, "first": int(m[1]), "last": int(m[2]),
                      "mtime": path.stat().st_mtime, "result": results[key]})
    return found


def _soak_sample(logs, done, constructed, commander, rng, now):
    """Games to probe: [(log item, g)], none probed before (done: a set of "key:g"), spread over the
    logs, half of each format's from logs written in the last SOAK_RECENT_S seconds."""
    picked = []
    for commander_format, want in ((False, constructed), (True, commander)):
        found = [(item, g) for item in logs if (item["result"].get("format") == "Commander") == commander_format
                 for g in range(item["first"], item["last"] + 1) if f"{item['key']}:{g}" not in done]
        recent = [x for x in found if now - x[0]["mtime"] <= SOAK_RECENT_S]
        older = [x for x in found if now - x[0]["mtime"] > SOAK_RECENT_S]
        rng.shuffle(recent)
        take = recent[:want // 2]
        rest = older + recent[want // 2:]
        rng.shuffle(rest)
        picked += take + rest[:max(0, want - len(take))]
    return picked


def _soak_game_text(path, g, first):
    """Game g's lines from a tee'd chunk log (the chunk's games in order from first), or None."""
    import gzip
    text = gzip.decompress(shared.Path(path).read_bytes()).decode("utf-8", errors="replace")
    games = checks._split_games(text)
    if not games:                       # a request's output without Forge's header line
        cur = []
        for line in text.splitlines():
            cur.append(line)
            if line.startswith("Game Result:"):
                games.append(cur)
                cur = []
    i = g - first
    return "\n".join(games[i]) if 0 <= i < len(games) else None


def _soak_fresh(setup, folder, result, g):
    """Play game g of result fresh: one one-shot DeckLabSim v2 request with the chunk's arguments
    (decks in g's seat order, -n 1, first g, the result's base, stream and pilots). Its output."""
    record = result["seeds"]
    names = []
    for side in result["sides"]:
        name = f"{side['card_sha']}.dck"
        (folder / name).write_text(side["dck"], encoding="utf-8")
        names.append(name)
    deck1 = shared.seeds.deck1_side(g, record["flip"])
    order = [deck1, 1 - deck1]
    seat_pilots = [result["sides"][i].get("pilot") for i in order]
    launch = dict(setup, decks_dir=folder)
    v2 = {"stream": record["stream"], "first": g}
    if all(seat_pilots) and any(p.get("profile", "Default") != "Default" or p.get("switches")
                                for p in seat_pilots):
        argv = shared.runner._java(launch) + shared.runner._class_path_launch(launch) + shared.runner.request_args(
            launch, result["format"], names[order[0]], names[order[1]], 1, record["base"], v2=v2, pilots=seat_pilots)
    else:       # the default pilots: the command line every v2 batch has
        argv = shared.runner.build_command(launch, result["format"], names[order[0]], names[order[1]], 1, record["base"], v2)
    env = shared._prepare_user_dir(setup["user_dir"])
    proc = shared.processes.start_process(argv, cwd=str(setup["forge_dir"]), env=env)
    try:
        out, _ = proc.communicate(timeout=max(600, 4 * setup["clock_s"]))
    except Exception:
        shared._end_process(proc)
        raise
    return out.decode("utf-8", errors="replace") if isinstance(out, bytes) else (out or "")


def _soak_lines(text):
    """One game's lines with wave 2's masks (timings, the game's place in its request, Java's stack
    frames and notices, blank lines, attackers in name order), DL| lines kept and the DLENGINE echo
    left out (a chunk prints it once, before its first game): from after the last header line (a
    one-shot's output) or from the start (a game cut from a chunk's log), to its Game Result line."""
    lines = text.splitlines()
    start = max((i for i, line in enumerate(lines) if shared.RE_HEADER.match(line)), default=-1)
    out = []
    for line in lines[start + 1:]:
        if not line.strip() or line.startswith(checks.JVM_WARNING) or checks.RE_FRAME.match(line) or "DLENGINE|" in line:
            continue
        out.append(checks.RE_ORDINAL.sub(r"\g<1>?", checks.RE_TIMING.sub("?", checks._attackers_in_order(line))))
        if line.startswith("Game Result:"):
            break
    return out


SOAK_HEADER = "Ai(1)-a - Ai(2)-b - 1 game of {fmt}"


def _soak_outcomes(fmt, text):
    """_outcomes of one game's text. A game cut from a chunk's log has no Forge header line, and
    LogReader reads no game before one, so a stand-in header (SOAK_HEADER) goes first when the
    text has none."""
    if not any(shared.RE_HEADER.match(line) for line in text.splitlines()):
        text = SOAK_HEADER.format(fmt=fmt) + "\n" + text
    return checks._outcomes(text)


def _soak_same(fmt, a, b):
    """Do two copies of one game agree: Constructed line for line (_soak_lines), Commander by
    outcome (result, winner, starter, turns)?"""
    if fmt == "Commander":
        return _soak_outcomes(fmt, a)[:1] == _soak_outcomes(fmt, b)[:1]
    return _soak_lines(a) == _soak_lines(b)


def _soak_difference(a, b):
    """Where two copies of a game first differ, in words."""
    la, lb = _soak_lines(a), _soak_lines(b)
    for i, (x, y) in enumerate(zip(la, lb)):
        if x != y:
            return f"line {i + 1}: fresh printed {x!r}, warm {y!r}"
    return f"fresh printed {len(la)} lines, warm {len(lb)}"


def _soak_warm(result, g, scratch):
    """Play game g again warm, alone, in the server's pool (runner.run with numbers=[g], the
    result's seeds, a scratch key and kind "experiment", its chunk log tee'd): its game text, or
    None when R's hooks aren't built (the verdict is then "unsure")."""
    if not shared.runner.RUN_FEATURES >= SOAK_WARM_FEATURES:
        return None
    import hashlib
    key = hashlib.sha256(f"soak:{result['key']}:{g}".encode()).hexdigest()
    entries = []
    for side in result["sides"]:
        seen = (side.get("seen_as") or [{}])[-1]
        entries.append(dict(side, id=seen.get("id"), version=seen.get("version"), title=seen.get("title") or "side"))
    logs = shared.Path(scratch) / "logs"
    with shared.pool.session(local=False) as session:
        shared.runner.run(entries[0], entries[1], 1, by="soak-probe", results_dir=str(scratch), pool=session, exact=True,
                   numbers=[g], seeds=dict(result["seeds"]), key=key, kind="experiment", log_dir=str(logs),
                   log_every=1)
    found = sorted((logs / key).glob("*.log.gz"))
    return _soak_game_text(found[0], g, g) if found else None


def _cmd_soak_probe(args):
    """soak-probe (sim-combined-run.md section 7.1): sample games from the tee'd logs of server-pool
    runs, play each fresh in a one-shot process and compare (Constructed line for line with
    wave 2's masks, Commander by outcome; each Commander game is played fresh twice, for MG7's
    paired baseline). A Constructed difference is played again warm, alone, in the server's pool:
    the same as fresh -> "unsure", different again -> "failed". It refuses (exit 1) when the
    server on --server-port has no live pool: it never falls back to a local pool."""
    import random
    if not _soak_server_live(args.server_port):
        raise shared._CliError(SOAK_NO_SERVER.format(port=args.server_port))
    out = shared.Path(args.out) if args.out else None
    ledger = shared.Path(args.ledger) if args.ledger else (out.parent / "probed.json" if out else None)
    done = set()
    if ledger and ledger.is_file():
        try:
            done = set(shared.json.loads(ledger.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            done = set()
    folders = args.results_dir if len(args.results_dir) == len(args.logs_dir) else args.results_dir[:1] * len(
        args.logs_dir)
    logs = [found for results_dir, logs_dir in zip(folders, args.logs_dir) for found in _soak_logs(results_dir, logs_dir)]
    picked = _soak_sample(logs, done, args.constructed, args.commander, random.Random(args.seed), shared.time.time())
    setup = shared._setup()
    log = shared.simjar.card_log(setup["java"], setup["forge_dir"], setup["jar"], setup["version"])
    if not log["ready"]:
        raise shared._CliError(log["problem"])
    setup = dict(setup, card_log=log)
    games, todo, lock = [], list(picked), shared.threading.Lock()
    folder = shared.Path(shared.tempfile.mkdtemp(prefix="decklab-soak-"))

    def probe(item, g):
        result, fmt = item["result"], item["result"]["format"]
        row = {"key": item["key"], "g": g, "format": fmt, "log": str(item["path"])}
        try:
            warm = _soak_game_text(item["path"], g, item["first"])
            if warm is None:
                return dict(row, verdict="skipped", why="the game isn't in its chunk's log")
            own = folder / f"{item['key'][:12]}-{g}"
            own.mkdir()
            with shared.slots.claim(1, what="soak-probe"):
                fresh = _soak_fresh(setup, own, result, g)
                if fmt == "Commander":
                    row["fresh2_differs"] = not _soak_same(fmt, fresh, _soak_fresh(setup, own, result, g))
            if _soak_same(fmt, fresh, warm):
                row["verdict"] = "same"
            elif fmt == "Commander":
                row["verdict"] = "differs"
            else:
                row["diff"] = _soak_difference(fresh, warm)[:400]
                again = _soak_warm(result, g, own / "warm")
                row["warm_again"] = again is not None
                row["verdict"] = "unsure" if again is None or _soak_same(fmt, fresh, again) else "failed"
        except Exception as e:      # one game's problem is that game's verdict
            row.update(verdict="error", why=f"{type(e).__name__}: {e}"[:400])
        return row

    def worker():
        while True:
            with lock:
                if not todo:
                    return
                item, g = todo.pop(0)
            row = probe(item, g)
            with lock:
                games.append(row)

    try:
        threads = [shared.threading.Thread(target=worker, daemon=True) for _ in range(min(SOAK_AT_ONCE, len(todo)))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        shared.shutil.rmtree(folder, ignore_errors=True)
        shared.runner._tidy_user_dir(setup["user_dir"])
    counts = {}
    for row in games:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    answer = {"when": shared.time.strftime("%Y-%m-%dT%H:%M:%S"), "port": args.server_port, "logs": len(logs),
              "asked": {"constructed": args.constructed, "commander": args.commander}, "counts": counts,
              "warm_replay": shared.runner.RUN_FEATURES >= SOAK_WARM_FEATURES,
              "games": sorted(games, key=lambda row: (row["key"], row["g"]))}
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(shared.json.dumps(answer, indent=1), encoding="utf-8")
    if ledger:
        done |= {f"{row['key']}:{row['g']}" for row in games if row["verdict"] not in ("error", "skipped")}
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(shared.json.dumps(sorted(done)), encoding="utf-8")
    if args.json:
        print(shared.json.dumps(answer, ensure_ascii=False))
    else:
        print(f"Probed {len(games)} games: " + (", ".join(f"{n} {k}" for k, n in sorted(counts.items())) or "none"))
    return 1 if counts.get("failed") else 0
