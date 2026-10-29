"""Forge matchups (PLAN.md part 6): play two deck lists against each other in
Forge, the free Magic rules engine, with its computer players on both sides,
many games at a time (since simulation wave 2, in a warm pool of Forge workers),
and keep the results; and, with the card log (Milestone 8), what each card of each
list did in those games: drawn, in hand by its side's turn 3, cast once drawn, stuck
in hand, the turn it was cast, and the win rates with and without it.

Usage (from the repo root):
    python -m decklab.lib.forge status                  is Forge ready: its version, or what's wrong;
                                                        whether runs keep the card log, or why not;
                                                        and the running server's warm pool
    python -m decklab.lib.forge audit casual/gruul-ramp [--owned]
                                                        cards Forge's AI can't play, and whether Forge
                                                        pilots the list poorly, with each card's reason
    python -m decklab.lib.forge play casual/izzet-prowess casual/gruul-ramp
        [--owned-a] [--owned-b]     the owned-only lists
        [--games N]                 200, 400, 800 (the default), 1600 or 3200
        [--until assess|ahead] [--max N]
                                    (wave 3, adaptive.py) instead of --games: play in stages until the
                                    win rate is known to within ±3 points (assess), or until one deck
                                    is clearly ahead or they're about even (ahead: checks at 400, 800,
                                    1,600 and 3,200 games); --max caps the result's games
        [--workers N]               Forge processes at once (config.json's forge_workers): at most
                                    forge_workers run at once all the same, the PC's budget (slots.py)
        [--batch N] [--seed-base S] [--a-first]
                                    exact runs: --games may then be any multiple of --batch. With the
                                    card log (the v2 engine): N caps a chunk's games, S is a new
                                    result's seed base, and deck A is Forge's deck 1 in a new result's
                                    first seat block. Without it (plain Forge): N games per process,
                                    seeds from S, deck A as deck 1 in even batches (as Milestone 0's
                                    run_matchup.py did)
        [--local]                   play in a pool of this command's own, not the running server's
        [--results-dir DIR]         save here instead of decklab/data/forge/results/
        [--no-save] [--json] [--by NAME]
    python -m decklab.lib.forge list [--results-dir DIR]
                                    the saved results, marked [earlier engine] ([earlier engine:
                                    v1], [earlier engine: plain Forge]) when they aren't today's
                                    engine's, and [plain Forge] while today's is plain Forge
    python -m decklab.lib.forge cards casual/gruul-ramp [--owned] [--results-dir DIR] [--json]
                                    how each card of a list played in all its saved matchups of
                                    today's engine, from the card log ("No card data yet." without
                                    any; how many games other engines played, which don't count)
    python -m decklab.lib.forge cardlog-check [--games N] [--commander-games N]
                                    after a Forge upgrade: plays the same games (12 Constructed and 3
                                    Commander, at most 25 each) four ways, plain Forge one game per
                                    process and DeckLabSim with game patches off, on and without the
                                    card log, then in a warm worker (servecheck.warm_leg), and lets
                                    runs use the card log with this Forge only when every game is
                                    the same
    python -m decklab.lib.forge serve-check [--games N] [--commander-games N] [--v1]
                                    the warm leg alone: a warm worker, pinned as the pool pins,
                                    plays the same games as fresh processes (servecheck.py); exits 1
                                    when one differs, and records nothing
    python -m decklab.lib.forge replay [--results-dir DIR] [--dry-run] [--local] [--matchups N] [--json]
                                    play again with today's engine every saved matchup of another
                                    engine whose two lists are still current, up to the most games
                                    an earlier result of the pair has (cli._cmd_replay); --dry-run
                                    lists the matchups, the games and a rough time
    python -m decklab.lib.forge pool [--json]
                                    the running server's warm pool: its workers and what's queued
    python -m decklab.lib.forge slots [--json]
                                    the Forge processes running on this PC, from every Deck Lab
                                    checkout: the slots in use, who holds each (process id, what,
                                    since, checkout) and the slots' folder
    Since simulation wave 3 (2026-10-03; below, "Wave 3"):
    python -m decklab.lib.forge field casual/mono-white-angels [--owned]
        [--budget quick|standard|thorough|N | --fixed N] [--opponents a,b,...] [--show] [--dry-run]
        [--inflight N] [--seed-base S] [--local] [--results-dir DIR] [--json] [--by NAME]
                                    the list against the current decks of its format (field.py): a
                                    floor of 200 games an opponent, then APT up to the budget (standard:
                                    about 400 a deck); --show prints the view and plays nothing,
                                    --dry-run the plan and its time
    python -m decklab.lib.forge variant casual/gruul-ramp [--owned]
        (--remove "N Name")... (--add "N Name")... | --list FILE
        (--against DECK [--owned-b] | --field [--opponents a,b,...])
        [--until ahead | --games N | --quick] [--more TEST] [--local] [--results-dir DIR] [--json]
                                    a change of the same size, played on the list's own games and
                                    judged by paired differences (variants.py)
    python -m decklab.lib.forge experiment SPEC.json [--results-dir DIR] [--control-dir DIR]
        [--control-logs-dir DIR] [--only ARM,...] [--games N] [--dry-run] [--report FILE] [--local] [--json]
                                    an experiment's arms (override sets, pilots, seeds, config knobs)
                                    against its control, with a recommendation for each (experiment.py)
    python -m decklab.lib.forge pilots [--check] [--json]
                                    each list's AI pilot (decklab/simulation.json), and the profiles and
                                    switches available; --check exits 1 on a bad entry
    python -m decklab.lib.forge overrides [list | check | make [--set S] | deploy [--user-dir DIR]
        [--sets a,b]] [--json]      Deck Lab's card-script overrides (overrides.py): the sets, whether
                                    each file is Forge's script with its edits, making them again from
                                    the installed Forge, and putting the adopted sets in the user folder
    python -m decklab.lib.forge staged-move --from DIR [--to DIR] [--hold FILE] [--dry-run] [--json]
                                    move staged results of today's engine (and field/ notes) into the
                                    results folder: never earlier engines', paired/ or experiment
                                    results; a stale file stays and says what differs
    python -m decklab.lib.forge soak-probe --results-dir DIR --logs-dir DIR --server-port P
        [--constructed N] [--commander N] [--seed S] [--out FILE] [--json]
                                    the overnight run's fresh-against-warm replays of sampled games
                                    (forge-trial/sim-combined-run.md section 7.1)
    Since AI round 1 (2026-10-13):
    python -m decklab.lib.forge engine-check --old DIR [--new DIR] [--games N] [--commander-games N]
        [--pair DECK DECK]... [--switch ID]... [--game-patches on|off] [--seed N] [--json FILE]
                                    a new build of the fork against the installed one (cli_engine.py):
                                    the same seeded games with each, card log on, compared line for
                                    line, and whether the two share an engine key; --old equal to
                                    --new is the noise floor. Exit 0 identical, 1 a difference, 2
                                    couldn't run, 3 only "can't tell". It records nothing
    python -m decklab.lib.forge decisions FOLDER [--card NAME]... [--json]
                                    the decision log's counts in a folder of game logs
                                    (decisionlog.py): each card's opportunities, how many the AI took,
                                    why it passed the rest, per phase and per seat
    play, replay, field, variant and experiment also take --logs-dir DIR [--log-every N]: Forge's
    output of the games played, gzip-compressed, in DIR/<matchup key>/<first>-<last>.log.gz (with
    --log-every N, only every Nth block of 25 game numbers).

    A deck in "play" can also be a .dck file (decklab/forge-trial/decks/compare/*.dck): its
    [Commander] and [Main] are played as they are, in their own order, which Forge's
    shuffle depends on. Ctrl+C stops a run and saves the games that finished (not with
    --no-save). list prints "No saved matchups." when there are none.

From code:

    from decklab.lib import decks, forge
    a = forge.entry("casual/izzet-prowess", "owned", "Izzet Prowess", "constructed",
                    decks.load_deck("casual/izzet-prowess", "owned"))
    b = forge.entry("casual/gruul-ramp", "owned", "Gruul Ramp", "constructed",
                    decks.load_deck("casual/gruul-ramp", "owned"))
    forge.matchup_key(a, b)            # the same for (b, a): today's engine's key (engine.py)
    result = forge.run(a, b, 800, by="Matt", progress=report)   # saved; report(done, total, detail)
    with forge.pool.session() as s:    # several runs in one place: the server's pool, or one of
        forge.run(a, b, 200, by="Matt", pool=s)     # this process's own (local=True: always)
    forge.view(result, a["card_sha"])  # the numbers, from a's point of view
    forge.load(key); forge.results(); forge.results_for(a["card_sha"])
    forge.ai_limits(sections, "constructed")   # cards the AI can't play, before any game
    forge.list_ai(sections, "constructed")     # the same with what it never cast in all its saved games
    forge.side_ai(result, 0)                   # the same for side 0 of a result, with its casts
    forge.side_cards(result, 0)                # CardStats: what each card of side 0 did (None: no card data)
    forge.list_cards(sections, "constructed")  # the same, pooled over every saved result of the list
    forge.status()                     # {"ready", "version", "problem", "card_log": {"ready", "problem"}}
    forge.forge_version()              # the Forge version keys use (no Java needed)
    forge.card_sha(sections, "constructed")    # entry()'s card_sha alone (no git)
    forge.engine_kind(summary); forge.page_kind(deck_id)   # a list's kind for entry(), for the page
    forge.slots.status()               # who holds the PC's Forge slots (forge_workers of them)
    forge.engine.today(); forge.engine.is_current(result)  # today's engine; is a result of it?
    forge.pool.status()                # the server's warm pool (in the server; else None)
    # Wave 3 (each module's docstring has the rest):
    forge.adaptive.run_adaptive(a, b, "assess", by="Matt")   # or "ahead": a run in stages, saved
    forge.field.view(a); forge.field.run_field(a, "standard", by="Matt")    # the field view, a field run
    forge.variants.run_test(a, cards, "field", by="Matt")    # cards: the changed {"Commander", "Main"}
    forge.experiment.run(forge.experiment.load_spec(path), by="Matt")
    forge.overrides.status(); forge.pilots.pilot_for("casual/gruul-ramp", "target")
    forge.estimate.matchup(a, b, game_dicts)   # the page's rough times (minutes) for a result holding them

Deck lists (.dck)
    Forge reads decks from .dck files: "[metadata]" with "Name=", then "[Commander]"
    (Commander decks) and "[Main]", one "<count> <name>" line per card. Deck Lab writes
    name-only lines (the printing doesn't matter to a simulation), the front face of
    "Front // Back" cards (Forge only knows that form for split cards and drops the
    rest), repeated printings merged, sorted by name. The sideboard is left out: sim
    mode never uses it. The card lines' SHA-256 is the list's card_sha, which also
    names the file (data/forge/decks/<card_sha>.dck) and, by its first 12 hex digits,
    the deck (Name=), so Forge's players are "Ai(1)-<12 hex>" and "Ai(2)-<12 hex>".
    The order of the lines matters: Forge builds the library in that order before
    shuffling, so the same seed plays different games with the lines in another order
    (checked 2026-10-01). Sorting makes the text, and so the games, depend only on the
    cards.

Matchups, engines, keys and seeds (since simulation wave 2, 2026-10-03: engine.py, seeds.py)
    A matchup's key is its engine id (engine.py's docstring has it whole): the SHA-256 of a
    canonical JSON description of everything that decides the games Forge plays for a
    seed: FORGE_RUN_VERSION (2), the kind (decklab: DeckLabSim with the card log; plain:
    Forge's own sim, which runs fall back to when the card log can't be used), Forge's
    version, the format, the per-game clock, the seed scheme, PERFORMANCE_MODE, the
    game-changing changes to Forge's classes in its jar (simjar.FORGE_PATCH_LIST),
    card-script overrides, and both sides' [card_sha, AI profile, the profile's SHA-256],
    sorted. Since wave 3 (id_version 2) the overrides part covers only the deployed override
    files whose card is in either list, and a side also holds its pilot's switches when it has
    any, so adopting an override set or a pilot re-keys only the matchups it touches. So A vs
    B is B vs A, and a changed list, a Forge upgrade, the card log turning on or off, an
    adoption or a setting starts a new result. Each side also has an id of its own (the
    same with that side alone), which per-card numbers pool by. Forge's version is the
    newest forge-gui-desktop jar's in its folder, the one a run plays with, looked up each
    time (so an upgrade while Deck Lab runs starts a new result at once); while the folder
    can't be reached, the last version found (data/forge/forge-version.txt), and what was
    read from it (data/forge/engine.json), so saved results are still found. Java doesn't
    matter to the key, nor do the chunk or batch sizes, warm or fresh workers, pinning,
    -XX:ActiveProcessorCount=2, the priority, the mulligan copy or R14a's AI copy, which
    play the same games for a seed (apart from a game that runs into a time limit, the
    clock or the AI's 5 s, which can go either way between any two runs). Results saved
    before wave 2 (run_version 1, lists._key) and those of another engine are never
    pooled with today's: views, saved, cardstats and ai label or leave them out
    (engine.is_current(), engine.words()), and "replay" plays their matchups again. A
    result's sides are stored in that sorted order (side 0 has the smaller card_sha);
    view() turns a result round to the page's point of view.
    The decklab engine (the card log ready): a result's games are numbered 0, 1, 2... over
    all its runs (next_game), and game g is a pure function of the two lists, the result's
    seed base and seed stream, and g (seeds.py): DeckLabSim reseeds Forge with
    seeds.game_seed(base, stream, g) before each game, after resetting Forge's per-JVM state
    (WarmState.java), and plays it as a Match of its own, so a coin flip picks who starts
    every game and Forge's auto-profile (a slower, non-aggro deck: "Control" in its name,
    or a nonland average mana value over 3, rounded down) applies in every game. Side 0 is
    Forge's deck 1 in even seat blocks of 25 games, side 1 in odd ones (the other way
    round with a new result's --a-first), and a chunk never spans two blocks, so game g is
    the same game whichever chunk or worker plays it, and the same as plain Forge's
    "sim -n 1 -s <its seed>" with that deck order. A run of G games plays [next_game,
    next_game + G) (lists.plan_v2) in chunks of the warm pool (pool.py's docstring: one
    queue for every run, chunks of at most 25 games, workers pinned to a core of their
    slot, recycled after a time limit, crash or 2,000 games), and saves them as one batch
    record for the run (runner._record_v2). Where it plays (pool.place): the server's pool
    in the server; from the command line, the running server's through its pool service
    when it plays the same engine, else a pool of the run's own (always with --local).
    The plain engine (the card log off): Forge's own sim, played in cold batches as before
    wave 2, below.
    A run of G games (GAME_CHOICES) is split into the largest even number of batches, at
    least 2 and at most min(forge_workers, G // SMALL_BATCH) (SMALL_BATCH is 25), that
    divides G (lists._batch_count; since 2026-10-03, the simulation report's R02). With 16
    workers: 200 games are 8 x 25, 400 are 16 x 25, 800 are 16 x 50, 1,600 are 16 x 100
    and 3,200 are 16 x 200. With 8 workers, 3,200 are 8 x 400; with 12, 400 are 10 x 40.
    With 1 worker it's 2 batches, played one after the other; a run under 50 games is 2
    batches when 2 divides it, else 1. So every batch starts at once (one wave of cold
    starts), and the number of batches is even. config.json's forge_batch_games no longer
    changes anything (it's kept so older config.json files load). A batch given to run()
    or --batch is used as given. Each batch is one Forge process with its own seed. Seeds
    go on from the result's highest seed so far (a first run starts at SEED_BASE), and
    batch n (counted over the whole result) plays side 0 as Forge's deck 1 when n is even,
    side 1 when odd. So the first run of two lists always plays the same games, and "play
    more" adds new ones.
    config.json's forge_workers is a budget for the whole PC (slots.py, since 2026-10-03):
    every run in every checkout and worktree, the server's and the command line's, shares
    it. Each Forge process holds a slot while it runs: a batch starts only in a free slot
    and gives it back when its process ends, however it ends. A run starts as many of its
    batches as it gets slots for, and the rest as slots come free (its own or other runs');
    with every slot taken it waits. So runs going at once never have more than
    forge_workers Forge processes between them (three 1,600-game runs from the command line
    used to start 48).

Running Forge (HISTORY.md "Installing and running Forge")
    The JDK's java.exe (config forge_java, or the newest JDK found), -Xmx<forge_xmx>
    -XX:+DisableExplicitGC -XX:ActiveProcessorCount=2
    -Dio.netty.tryReflectionSetAccessible=true -Dfile.encoding=UTF-8
    -jar forge-gui-desktop-<version>-jar-with-dependencies.jar sim -D <decks folder>
    -d <sha>.dck <sha>.dck -n <games> -s <seed> -f Constructed|Commander -c <clock>
    -a Default Default, from the Forge folder, with the full game log (no -q): who went
    first and what was cast come from it. -XX:ActiveProcessorCount=2 (since 2026-10-03,
    R01a) makes Java size its compiler and garbage-collector threads for 2 CPUs instead of
    the PC's 32, so 16 processes starting together start faster and play the same games
    (1,011 -> 1,086 games a minute and start-up 5.2 -> 3.4 s in the report's measurements).
    Forge's per-attack thread pool also drops from 32 threads to 2 (the card log's
    AiAttackController copy, below, uses none), and Java's sizing should be checked again
    after a JDK upgrade. APPDATA and LOCALAPPDATA point at data/forge/user, whose
    forge.preferences (runner.PREFERENCES) turns on lazy card loading (start-up 1.3 s
    instead of 9 s, same games) and, since wave 2, Forge's PERFORMANCE_MODE (R08: part of
    the engine id; the DLENGINE line's perf says it took); each Forge process leaves a
    copy of its output there (forge.log, forge1.log..., renamed forge.<time>.log by the
    next start), and those are deleted before and after each run. The first time that
    folder is used, one process starts alone and the rest wait for its header line (16
    starting together on a new folder race to create it, and one can crash).
    With the card log (below), the same command starts DeckLabSim instead of -jar: after
    the same flags, "--add-opens <module/package>=ALL-UNNAMED" for every entry of the
    Forge jar manifest's Add-Opens (java applies those only for -jar), then -cp <card-log
    jar><os.pathsep><Forge jar> decklab.DeckLabSim sim ... with the same arguments (a v2
    run's one-shot process adds -dlgame <stream> <first>, with -s the result's seed base).
    Deck Lab runs its own build of Forge, from the fork's decklab branch (github.com/
    matt439/forge, cloned at C:/VSProjects/forge; its decklab/install.py installs it in
    C:/Tools/forge-decklab), which holds Deck Lab's changes to Forge's own classes
    (AbstractMulligan without its 100 ms sleep per mulligan; AiController with each AI
    decision's eval on a virtual thread, R14a; AiAttackController with its forced-attacker
    checks run in turn, in attacker order, R14b; Match building each library in the .dck's
    line order, deck-order-1, through the hook DeckOrder.java plugs in) and its AI fixes.
    Until 2026-10-11 the first four were copies in the card-log jar. Forge's jar lists them
    (simjar.FORGE_PATCH_LIST): the first two play the same games; AiAttackController can
    change games with two or more must-attack creatures (Forge's thread pool finishes its
    checks in any order) and Match changes each library's order, so they're game patches,
    named in the engine id, and -Ddecklab.gamePatches=off plays Forge's own code
    (cardlog-check's parity leg, and every plain-Forge run). The card-log jar holds Deck
    Lab's own classes for pilots (Pilots, TeamPumpAi, AiPatches) and start-up hooks
    (Startup: the AI profile folder, the overrides' hash, the deck order's hook). The fork
    needs JDK 21 or later. A Forge jar without the list (a stock release) gets no card log,
    and runs play plain Forge.
    A warm worker (pool.py) is the same class path started as "decklab.DeckLabSim serve"
    (runner.serve_command): it loads Forge once, then plays "play" requests read from its
    stdin, one at a time, each with sim's arguments (runner.request_line), and says how
    each ended with DLSERVE| lines (done, cancelled, recycle after a clock stop, an AI
    timeout or a crash, or error). It's started like any Forge process (below: the job,
    below normal priority), and pinned to its slot's core while it plays (cores.py).
    Each process is read by a thread of its own, line by line, keeping only each game's
    summary (and, with the card log, its cards' tallies). A watchdog kills a process that prints no header line in HEADER_TIMEOUT
    seconds, or no "Game Result" line for the clock plus GAME_GRACE seconds; its batch
    fails with "Forge stopped responding".
    On Windows every java.exe is started suspended, put in a Job Object made with
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE and only then resumed. This process holds the only
    handle to that job, so however it ends (Ctrl+C, taskkill /F, Task Manager), Windows
    kills every Forge process with it. Each process also gets a job of its own, nested in
    that one, and a stop or the watchdog kills that whole job: a java.exe that's only a
    launcher (the one on the PATH) starts the real one as its child, which killing the
    launcher alone would leave running. Elsewhere each process gets its own process
    group instead.
    On Windows, java.exe also starts below normal priority (BELOW_NORMAL_PRIORITY_CLASS,
    with CREATE_NO_WINDOW and the suspended start: processes._SPAWN_FLAGS, since
    2026-10-03, R18), and the processes it starts inherit it. So the PC's other programs,
    and the practice-hand workers (normal priority), come first when they want the same
    cores. Practice hands take no slots and never wait for Forge (slots.py says why).
    Elsewhere Forge keeps normal priority.

Reading Forge's output (the trial's run_sim.parse and setup-notes.md sections 4-5)
    Forge names a winner even for a game that hit the clock or crashed, so a game is a
    win only when exactly one player "has won" and no "Stopping slow match as draw" line
    came; otherwise it's a timeout, an error (a stack trace was printed) or a draw. A
    batch fails, and none of its games count, when Forge printed "An unsupported card was
    requested" (it drops the card and plays on) or "Could not load deck" (it still exits
    with 0), exited with another code, or played fewer games than asked. "AI eval thread
    at timeout" lines (the AI ran out of its 5 seconds for a decision) are counted; the
    TimeoutException and InterruptedException stack traces that come with them and with
    a clock stop don't make a game an error.
    Casts come from "Add To Stack: Ai(n)-... cast <card>" and land plays from
    "Land: Ai(n)-... played <card> (id)", per card and side. With the card log, LogReader
    also hands the DL| lines, the "Mulligan: ... has kept a hand of N cards" lines
    (RE_KEPT), the land plays' ids, the cast lines and Forge's "Add To Stack: <card>
    (<id>) - [Couldn't add to stack, ..." lines (RE_NOT_CAST: the AI started a cast it
    couldn't finish, which doesn't count as cast) to cardlog.py; none of that changes
    the games, casts or lands above. A failed batch's saved output leaves the DL| lines out.
    Before Forge starts, every card name of both lists is checked against Forge's own
    card scripts (res/cardsfolder/cardsfolder.zip, indexed once per Forge version into
    data/forge/cardscripts-<version>.json); an unknown name stops the run with ForgeError.
    DeckLabSim prints a "DLENGINE|key=value|..." line before Forge's header for each request
    (a one-shot process, or one serve request): the loop's version (v=2 and seeds=game,
    with base, stream and first, for the v2 loop), perf (PERFORMANCE_MODE took), the card
    log, the game patches loaded and whether they're on, and each seat's auto-profile flag
    and average mana value (LogReader.engine, engine_by_side()). A v2 chunk whose line
    doesn't say the run's engine fails (engine.check_echo); the first chunk's flags are
    stored on the result's sides (engine.side_fields: "auto_profile"). A warm worker's
    DLSERVE| lines (runner.serve_event) end each request.

Stopping, failures and saving
    progress(done, total, detail) is called as games finish (at most 4 times a second,
    and at least once a second while nothing finishes, so a Stop is seen soon), with
    detail {"wins": [side 0, side 1], "other", "games_per_min", "eta_s",
    "failed_batches", "waiting"}. "waiting" is slots.WAITING ("Waiting for other Forge
    runs on this PC to finish.") while no process of the run is playing because every
    slot is another run's, else None; the page's job and Running item carry it, and play
    prints it. When progress raises (jobs.Stopped from the page's Stop button or the
    server stopping) or Ctrl+C comes, every Forge process is killed and every game that
    finished is saved: a batch cut short keeps its finished games as a partial batch
    ("partial": true; the game each process was playing is lost, and one that had
    finished none isn't kept). The run record says "stopped": true (with "stopped_by",
    the exception's "by"), and the exception goes on up, its saved_games saying how
    many of this run's games were saved (None: nothing was). A second Ctrl+C only stops
    the waiting for the killed processes; the games are still saved. A Stop or Ctrl+C
    while the run waits for a slot stops it the same way (a stopped run record, with no
    games). Any other exception in the loop (a bug) is handled the same way, but its run
    record has an "error" instead.
    Failed batches are saved with their seed and reason but not counted, and their seeds
    aren't used again, nor are a partial batch's. When no batch could be played, run()
    raises ForgeError with the first reason, after saving the run record.
    A run record: when, by, "a" (the list asked for first), asked and played (games),
    batches (planned), played_batches (kept, partial ones included) and partial,
    workers (the processes it asked for at once: the smaller of workers and its batches),
    batch_games (the first batch's games), seeds ([first, last] of the seeds used: kept
    and failed batches'), wall_s (from its first process's start, so a wait for a slot is
    left out), startup_s, waited_s (how long it waited for a slot before its first
    process started) and most_running (the most processes it had at once; both since
    2026-10-03, so older records lack them), stopped, stopped_by, failed, failure (the
    first failed batch's reason), error, and card_log (true when its batches ran with the
    card log; when false, card_log_problem says why in a plain sentence). Each kept batch,
    partial ones included, has "cards" when the card log was on (below).
    A v2 run (the decklab engine, runner._run_v2) plays chunks instead of batches. Each
    game is sent to the run as it's read, so a Stop or Ctrl+C saves exactly the games read
    (the game each worker was playing is lost), and a Stop doesn't wait for the workers.
    A chunk that fails (an error, an unknown card, another engine's DLENGINE line), or a
    range whose games went back to the queue more than MAX_REQUEUE times, is saved in
    "failed" as {"n" (the run's ordinal), "first", "games", "error"}; its game numbers
    aren't used again. The kept games go into one batch record for the run ({"n", "first",
    "games" (each with its number "g"), "casts", "lands", "cards", "chunks", "wall_s"}).
    Its run record has the keys above, with batches and played_batches counting chunks,
    batch_games the largest chunk, seeds [first g, last g], workers and most_running the
    most chunks playing at once and startup_s the slowest start-up it waited for (None
    when every worker was warm), plus pool ("server", "remote": a command line run in the
    server's pool, or "local"), chunks, recycled, requeued, games_from, games_to, engine
    (the key), xmx (the heap its games were played with) and, when serve couldn't start
    and the chunks played as one-shot processes, fallback (why). The result also has
    "engine" (engine.result_fields), "seeds" {"scheme", "base", "stream", "seat_block",
    "flip"} and next_game; each side has engine_id, ai, ai_sha and auto_profile.
    Results are written whole or not at all (a temporary file, then os.replace, tried
    again for a moment while another program has the file open), one file per key:
    data/forge/results/<key>.json. A file there that isn't a result of that key in
    run()'s shape (a hand edit, a newer format) is read as no result: it's left out of
    the lists, and run() won't play that matchup rather than save over it. Before
    Forge starts, run() checks that folder can be written and takes the matchup's lock
    (an OS lock on <key>.lock, gone with the process however it ends), so the same
    matchup can't be played twice at once (by the server and the command line, say),
    which would play the same seeds twice and keep only one run's games. A failed batch
    also leaves the end of Forge's output in data/forge/logs/ (the newest
    KEEP_FAILURE_LOGS are kept).

AI limits (HISTORY.md "Card support")
    cannot_play lists cards whose Forge script has AI:RemoveDeck:All (the AI never casts
    them or uses their abilities) and, once there are MIN_GAMES_NEVER_CAST counted games
    to judge by ("games"), its nonland cards that were never cast (or played as a land)
    in them, like Fiery Annihilation. side_ai() judges by one result's games;
    list_ai() (the deck page's) by every saved result that played the list: each side
    with its card_sha (both sides of a mirror, each once) adds its casts, land plays and
    counted games, so a card cast in any of them isn't flagged. commander_unplayable
    says the commander is one of them (the Gisa decks), which makes that deck's results
    meaningless. team_pump flags a list with 3 or more instants and sorceries tagged
    power-boost-to-all or overrun in Scryfall's oracle tags (child tags included): Forge's
    AI holds such spells, so it rates go-wide pump decks too low. The page and the audit
    show it only when "pilot" is None (Forge's card scripts can't be read), so they never
    give two team pump counts. unknown lists names Forge has no script for. When card
    data covers every one of the counted games, a never_cast card of the Main deck also
    has "drawn_games", the games it was drawn in (the page says "drawn in N games, never
    cast").
    pilot (since 2026-10-03, the report's R19) says whether Forge pilots the list poorly,
    from its cards' Forge scripts (ai.weak_cards(), read once per Forge version and
    cardsfolder.zip), or is None, with the reason in "problem", when the scripts can't be
    read. The kinds of card Forge's AI misplays are in ai.WEAK_KINDS, each confirmed in
    Forge's source: AI:RemoveDeck:All; "when this enters" abilities that stop a cast
    (they shrink the opponent's team, destroy all of something, target "up to" one card, or
    must target the opponent's things); flash creatures with no enters ability; team pumps
    (spells, or permanents' abilities, both judged one creature at a time); removal whose
    AITgts the AI follows strictly; and counterspells. A list is flagged ("poor", with
    "why") when its commander is one the AI never casts or holds back ("commander"), it
    has TEAM_PUMP_MIN (3) or more team pump copies ("team_pumps"), or its weak copies
    reach PILOT_SHARE of its cards, 4 in 60 ("share"; a counterspell counts as half a
    copy). Its other fields: "cards" ([{"name", "qty", "commander", "why": [kinds],
    "detail"}]), "copies", "needed", "team_pumps" (spells and permanents' abilities),
    "team_pump_spells" and "counterspells". On the decks of 2026-10-03 it flags Selesnya
    Rabbits, The Free Peoples, Finneas, Gisa, the Wretched Ranks precon and Hare Raising.

The lead, the starting player and how far to trust them (views.py, since 2026-10-03)
    view() gives, besides the win rates:
    - "lead": {"verdict", "side", "basis"}. verdict is "ahead" (the range leaves out an
      even split), "about_even" (the range stays within ABOUT_EVEN, 5 points, of it:
      45-55%), "slightly_ahead" (both: "<deck> is slightly ahead (by under 5 points)") or
      "not_settled"; side is the deck ahead, 0 for the page's first deck, or None. basis is
      "decided" when every game has a winner (the headline range is judged), else
      "comparison" (the both-sides comparison from 2026-10-01, with about even scaled by
      the share of games decided). verdict_words() words it, as the page (LEAD_WORDS) and
      play do.
    - "starter": {"value", "low", "high", "balanced"}, the starting player's chance of
      winning: the average of both decks' win rates going first, with balanced()'s range.
      When a deck never went first it's the plain share with a Wilson range, and
      "balanced" is False. (The plain share misled, since the loser starts the next game.)
    - "noise_points": how far two results of this many games can differ by chance, in
      points: the headline range's width / sqrt(2).
    "starter_won" is gone (nothing read it). These are worked out when a result is read,
    so saved results need no migration. play prints the starter, the lead and "!" lines
    for the noise, each deck Forge pilots poorly (not for a commander that's never cast:
    the "not meaningful" line says so), the tempo caveat when both decks hold counterspells,
    and "Commander results are indicative only" in Commander.

The card log (Milestone 8: java/, simjar.py, cardlog.py, cardstats.py)
    DeckLabSim (java/decklab/DeckLabSim.java) is Forge's sim with one event listener added
    that logs every card move, the kept hands and the hands after the game as
    "Information: DL|..." lines; cardlog.py's docstring has their format. It only reads
    the game and adds log lines, so it plays the same games as plain Forge (checked game
    for game, with game patches off: the game-changing copies below play Forge's own code
    then). Since wave 2 the jar also holds the v2 game loop (GameLoop.java, Request.java,
    Seeds.java, WarmState.java) and serve mode (DeckLabServe.java), so the card log is
    also what the decklab engine and the warm pool run. Every run uses it when it can
    (simjar.card_log()); otherwise the run plays plain Forge (the plain engine) and keeps
    no card data, and status() and the run record say why. It can't be used without the
    JDK's javac and jar beside java.exe (a JRE has neither), with a JDK older than 21,
    when the jar won't build, or with a Forge it wasn't checked with: a version in
    simjar.CHECKED (with the Forge build and DeckLabSim source it was checked with) or
    one "cardlog-check" passed, recorded in data/forge/cardlog/checked.json. A check that
    failed (Constructed games that differed, or a card log that went wrong) turns it off
    for that Forge until a check passes; one that can't tell (a time limit, or Commander
    games that differ the way plain Forge's own can) changes nothing.
    Deck Lab builds the jar itself at the start of a run (never in status()), into
    data/forge/cardlog/, under an OS lock, and again when the source, the Forge jar or javac
    change; a stamp beside it records them, with Deck Lab's changes in that Forge jar. The
    checked source (source_sha256(), CHECKED_SOURCE, checked.json) covers every Java file in
    java/decklab/, so editing any of them turns the card log off until cardlog-check passes,
    and each build of the fork is a Forge version of its own (install.forge_version()), so a
    new build is checked too.
    A batch's "cards" record is all that's kept: per side and card, the games it was
    drawn in and won, copies drawn, cast or played, stuck in hand and discarded, the
    rounds they were first cast in, casts from anywhere but the hand, and (since wave 2,
    record version 3) the games a copy was in the side's hand by its own 3rd turn and won
    (early_games, early_wins); per commander, its casts (cardlog.py has the definitions
    and the record's shape). No per-game events or raw logs are kept. A game counts only
    when its card log passes cardlog's checks (every move adds up to the hands and
    libraries at the end, among others); otherwise it's in "bad", for both sides. Records
    of versions 2 and 3 count (cardlog.RECORD_VERSION is 3); the 8 numbers they share pool
    over both, and the early ones over version 3 only, out of their own games and wins.
    Batches with no record (played before the card log, or while it was off) or with
    version 1's (it counted a cast the AI couldn't finish) don't count, so per-card stats
    say "from N of M games" (version 1's games are "old", and the page says an earlier
    card log kept them). Per-card numbers pooled over a list (list_cards) only count
    results played with today's decklab engine (its side id, engine.side_ids()), and
    ai.list_ai those and today's plain ones; both say how many of the list's games other
    engines played ("other_engine_games").
    cardstats.py turns the records into rows: shares, the average
    turn cast (each player's own turn number), the win rate when drawn and when not with
    Wilson ranges, and their difference with its range, judged once a card has
    MIN_SPLIT_GAMES games each way (never a land: the games without one were mostly short
    of lands or of its colour). Win rates are raw (not balanced for who went first,
    which moves them about a point), and long games draw more cards, so a difference
    says what happened, not why. Numbers are called early below MIN_CARD_GAMES (800)
    games with card data; they're still shown. 4-player pods and sideboards aren't
    covered.
    Since 2026-10-03 (the report's R11, items 1-3): a difference pooled over a list's
    matchups (list_cards) is worked out matchup by matchup (Mantel-Haenszel, one stratum
    per saved result: saved._pooled_cards' "strata"), so a card isn't credited for which
    opponents its list played most; with one matchup it's plain Newcombe, as before. Each
    difference has a best estimate pulled toward 0 ("shrunk": empirical Bayes, the spread
    of real card effects being r5's CARD_SPREAD, 4.5 points, averaged by precision with
    the list's own). "won more/less when drawn" is given only to a card that stands out
    among the list's judged cards (a Benjamini-Hochberg discovery at FALSE_DISCOVERIES,
    10%, commanders included) and whose 95% range is clear of 0. A Row also has
    "shrunk", "p" and "discovery"; a CardStats dict also has "compared", "fdr", "spread"
    and "spread_weight" (cardstats.py's docstring has them all). The cards command prints
    the best estimates, and says when a range clear of 0 is still within chance.
    Since wave 2 (R11 item 4): when any of a list's games have version 3's tallies, a
    card's verdict is "won more/less when in hand by turn 3" (CardStats "basis" "early",
    "early_of" the games it rests on): games with a copy in hand by the side's own turn 3
    against games without, which doesn't lean with game length, since by turn 3 every
    game has seen about as many cards. Otherwise ("basis" "drawn") the drawn verdict stays,
    labelled as leaning with game length. "enough" counts early_of with basis early. A Row
    also has early_games, early_share, wr_early, wr_not_early and basis; each card's drawn
    win rates are still there. A land is never judged, and its diff is always the drawn
    split's. The cards command has a "by t3" column.

Wave 3: adaptive runs, the field view, tests of a change, overrides, pilots and experiments
(simulation wave 3, 2026-10-03: forge-trial/sim-wave3-contract.md; merged 2026-10-04)
    The coordinators (adaptive, field, variants, experiment) never handle chunks: each calls
    runner.run for whole runs and reads the saved results, keeps the key its first run of a
    pair returned, and stops with "The engine changed during this run: play it again." when a
    later run returns another. Every statistic is in seqstats.py, as pure functions over a
    result's game dicts, shared by the page, the command line, the coordinators and the
    overnight harness.
    - Adaptive runs (adaptive.py): "assess" (a 400-game pilot, then the games planned for a
      ±3-point range, at most one top-up) and "ahead" (checks at 400, 800, 1,600 and 3,200
      games, Haybittle-Peto boundaries, an "about even" exit). A check happens only once its
      stage's games have all finished; a Stop makes one last check at |z| ≥ 3. Each run's
      summary goes in the result's "adaptive" list, and view()'s lead follows it while it
      applies (adaptive.lead_from_summary).
    - The field view (field.py): a list against the current decks of its format (deck files'
      built or target lists, intact products, simulation.json's "field" additions and
      removals): the equal-weight average, a Bradley-Terry rating with a starter term, its
      rank, residual flags and one row per opponent. A field run is ordinary matchup runs:
      a floor of 200 games an opponent, then APT; its note goes in <results>/field/.
    - Tests of a change (variants.py): the changed list (same size) plays the base result's
      game numbers on its seed base, stream and seats, as a "paired" result in
      <results>/paired/, so only games where the change mattered differ; seqstats judges the
      paired difference against forge_variant_margin (the field, 0.02) or
      forge_variant_margin_one (one deck, 0.03). It refuses to start without deck-order-1.
    - Card-script overrides (overrides.py, overrides/sets.json): Forge's scripts with small AI
      edits, put in the run's user folder's custom/cards by ensure_deployed before every run.
      Only "adopted" sets go in the real user folder; experiment sets play in folders of their
      own (user_dir_for). A file whose Forge script changed (the upstream check) isn't used.
      The AI limits read the deployed scripts (overrides.overlay_index).
    - Pilots (pilots.py, decklab/simulation.json, ai-profiles/): a list's AI profile and
      switches (simjar.PILOT_SWITCHES: team-pump-1, aisim-hybrid-1). Every list has Forge's
      Default and no switches until one is adopted.
    - Experiments (experiment.py): arms played on a control result's game numbers and seeds,
      as results of kind "experiment" with keys of their own (never pooled with matchups), and
      measured against the control; override and pilot arms get "adopt", "don't adopt" or
      "more games".
    - Time estimates (estimate.py): a pair's saved speed, else its lists' speed class, at the
      rates in <data>/forge/rates.json (the combined run's measured warm rates since
      2026-10-04), else wave 2's defaults.
    - Adopting an override set or a pilot is the owner's: sets.json's "status" or
      simulation.json, committed; both are read again when they change. The re-keyed
      matchups are then "Earlier engine" until "replay" plays them again.

Where things are (decklab/lib/forge/, each part importing only those above it)
    common.py       what the parts share: constants, the data folder, settings, errors,
                    logging, writing a file whole, holding Ctrl+C back, Forge's card names
    seeds.py        the v2 engine's per-game seeds (game_seed(), stream_of(), the seat
                    blocks), the same as java/decklab/Seeds.java; it imports nothing
    slots.py        the PC's budget of Forge processes: OS-locked slots shared by every
                    checkout (claim(), Lease, status()); it imports only common and
                    decklab.lib.config
    cores.py        the PC's physical cores, V-Cache first, and pinning a process to slot
                    k's core (pin()): simulation wave 2
    simjar.py       the card log's jar: card_log() builds it (with the copies of Forge's
                    classes that fit, PATCHES and fitting_patches(), and the game patches
                    among them, GAME_PATCHES) and says how to start it, readiness(), the
                    Forge versions it was checked with
    install.py      Java and the Forge jar, status() (with the card log's readiness),
                    forge_version(), the card script index
    lists.py        .dck text, entry(), card_sha(), entry_from_dck(), matchup_key(), plan()
                    (the plain engine's batch plan: _batch_count()), plan_v2() (a v2 run's
                    game numbers, cut at the seat blocks), lists._key (the v1 key)
    overrides.py    Deck Lab's card-script overrides (wave 3): the sets (overrides/sets.json),
                    ensure_deployed(), the per-list hash, the upstream check, status()
    pilots.py       each list's pilot from decklab/simulation.json (wave 3): pilot_for(),
                    the profiles (Forge's and ai-profiles/) and switches available
    engine.py       the engine a run plays (current()) and its matchup key (key(),
                    matchup_key()): simulation wave 2's engine id, version 2 since wave 3
                    (per-list overrides, pilots); today(), side_ids(), is_current() and
                    words() for the consumers
    processes.py    starting and killing Forge's processes (Job Objects and below normal
                    priority on Windows; start_process(stdin=True) for warm workers)
    cardlog.py      the card log's lines: one game's moves, its checks, a batch's tallies
                    (record version 3: in hand by turn 3), merge_record() for a run's chunks
    logreader.py    LogReader, which reads Forge's output
    decisionlog.py  the decision log's DLAI| lines (AI round 1): read(), read_folder(), summary()
    saved.py        the saved results: load(), and what a result's batches add up to
                    (casts, land plays, and the card log's tallies: _pooled_cards(), which
                    keeps each result's part as a stratum: _add_stratum(), _stratum_key())
    tokenpeaks.py   a list's token peaks pooled over its saved results: list_token_peaks()
                    (E7-S08; the deck page's Tokens part reads them as forge.tokenpeaks)
    cardstats.py    per-card stats: card_rows(), side_cards(), list_cards(), and how a
                    difference is judged (_difference(), _spread(), _shrunk(),
                    _discoveries(), _judge()); and the helpers ai and views share
                    (wilson(), _is_land(), _merged_cards())
    runner.py       build_command() and run(): playing the plain engine's batches, each in
                    a slot (_play), or a v2 run's chunks in the warm pool (_run_v2,
                    _play_v2, _record_v2), and saving the result; serve_command() and
                    request_line() for warm workers
    pool.py         the warm pool (simulation wave 2): warm workers, one queue of chunks
                    for every run, the server's pool and its service for the command line
                    (place(), session(), start_server_pool())
    servecheck.py   the check that a warm worker plays the same games as a fresh process
                    (warm_leg(), serve-check, cardlog-check's warm leg)
    ai.py           AI limits: ai_limits(), list_ai(), side_ai(), and how well Forge pilots
                    a list (weak_cards(), _pilot())
    views.py        the win-rate maths, the lead and the starting player (_lead(),
                    verdict_words(), _starter()), list_item(), view(), results(),
                    results_for()
    seqstats.py     wave 3's statistics: adaptive checks, paired differences, the field
                    average, Bradley-Terry, residual flags, APT (pure functions)
    estimate.py     time estimates for the page, field runs and tests (rates.json)
    adaptive.py     adaptive runs: run_adaptive(), last_summary(), lead_from_summary()
    field.py        the field view: field_lists(), plan(), run_field(), view()
    variants.py     tests of a change: aligned_dck(), run_test(), view(), tests_for()
    experiment.py   the experiment harness: load_spec(), plan(), run(), measures(), report()
    cli.py          the command line (__main__.py runs it)
    java/           DeckLabSim's source and, since wave 2, the v2 game loop (GameLoop,
                    Request, Seeds), the warm reset (WarmState) and serve mode
                    (DeckLabServe); since wave 3 the deck order (DeckOrder), pilots (Pilots,
                    TeamPumpAi, AiPatches) and start-up hooks (Startup), all under
                    java/decklab/ (simjar.py builds them into one jar). Deck Lab's changes to
                    Forge's own classes are in its fork of Forge (simjar.py's docstring).
    overrides/      the override sets' card scripts and sets.json (wave 3)
    ai-profiles/    Deck Lab's AI profiles: DLAggro, DLTempo, DLControl (wave 3)
    forge.<name> works for every name the import lines below bring in (the module's names
    from before Milestone 7 split it up, and some added since), except the few the tests
    patch or reset, or that change at run time (_OWNED below): those live only in their
    part, as forge.common.DATA_DIR does, and are patched and set there. Other names are
    read on their part (forge.slots.claim, forge.ai.weak_cards).
"""
import sys
import types

from . import (common, seeds, cores, simjar, install, lists, overrides, pilots, engine, processes, cardlog, logreader,
               saved, cardstats, runner, pool, servecheck, ai, views, seqstats, estimate, adaptive, field, variants,
               experiment, cli, tokenpeaks)
# Wave 3's parts (forge-trial/sim-wave3-contract.md) are reached through their modules
# (forge.seqstats.look, forge.field.view, ...); none is re-exported here.
# Every name the module had before Milestone 7 split it up, except those in _OWNED below.
from .common import (
    FORGE_RUN_VERSION, GAME_CHOICES, DEFAULT_GAMES, AI_PROFILES, MIXED_KINDS, ForgeError, Stopped, STOPS,
    _decks_dir, _results_dir, _user_dir, _now, _interrupts_held, norm, forge_name, _os_reason)
from .simjar import (
    CHECKED, CHECKED_BUILDS, MAIN, readiness, checked_versions, record_checked, record_failed, forge_build)
from .install import (
    JAR_GLOB, JAR_RE, SCRIPTS_ZIP, VERSION_FILE, _version_tuple, find_java, _find_jar, _setup, _known_lock,
    _remember_version, forge_version, _status_lock, status, SPECIALIZE_FACE, _read_script, _scripts_lock,
    _forge_card, _log_names)
from .lists import (
    SEED_BASE, SMALL_BATCH, FORMATS, SOURCE_TTL, SOURCE_CACHE_MAX, fmt_for, _merge_lines, _list_text, _dck,
    _section_cards, _sources_lock, _source, entry, card_sha, entry_from_dck, matchup_key,
    _key, _list_lines, plan, _batch_size)
from .processes import (
    _job_lock, _new_job, _job_handle, _own_job, _close_job, kill_process, _end_process, in_job)
if sys.platform == "win32":     # processes.py's Windows-only names
    from .processes import (
        _k32, _BASIC_LIMIT, _IO_COUNTERS, _EXTENDED_LIMIT, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, PROCESS_TERMINATE, PROCESS_SET_QUOTA, PROCESS_SUSPEND_RESUME,
        PROCESS_QUERY_LIMITED_INFORMATION, _SPAWN_FLAGS, _SUSPENDED)
from .logreader import (
    RE_HEADER, RE_RESULT_WIN, RE_RESULT_DRAW, RE_ROUNDS, RE_OUTCOME, RE_TURN, RE_CAST, RE_LAND,
    RE_KEPT, RE_UNSUPPORTED, RE_NOLOAD, RE_EXC, EXPECTED_EXC, AI_TIMEOUT, SLOW_STOP, LogReader)
from .saved import (
    READ_CACHE_MAX, _read_lock, GAME_KEYS, _is_result, _read_result, load, _stored, _counted, _pooled,
    _pooled_cards)
from .cardstats import newcombe, side_cards
from .runner import (
    JVM_FLAGS, PREFERENCES, HEARTBEAT, KILL_WAIT, TAIL_LINES, KEEP_FAILURE_LOGS, EVENT_POLL_S, BUSY,
    CANT_SAVE, NOT_SAVED, UNREADABLE, _Batch, STOP_KILL, _prepare_user_dir, _read, _save_failure_log, _kill,
    _play, _side, _seen, _check_names, _write_decks, _claim, _release, run, _run, _record)
from .ai import (
    TEAM_PUMP_TAGS, TEAM_PUMP_MIN, _card_fields, _types, _is_land, _merged_cards, _index_or_problem,
    _cannot_play, _limits, ai_limits, list_ai, _side_cards, _commander_unplayable)
from .views import (
    wilson, balanced, _r, _games, _perspective, _winrate, page_kind, _page_side, _not_meaningful, view,
    _items, results, results_for)
from .cli import (
    _CliError, engine_kind, _cli_list, _cli_entry, _positive, _games_problem, _stopped_message, _pct,
    _print_limits, main, _main)

# The names that live only in their part, not here: the tests patch or reset them, or
# they change at run time, so a copy here would be one a patch or reset doesn't reach.
# Patch, set and read them on their part (forge.common.DATA_DIR, forge.install._status).
# The api calls forge.list_item, forge.side_ai and forge.list_cards, so those three read
# through to their part, and a patch there reaches the api too.
_OWNED = {name: part for part, names in (
    (common, ("DATA_DIR", "_settings", "_log", "_write_atomic")),
    (simjar, ("card_log", "_built", "_builds", "_build", "_manifest", "_replace", "_failed", "SOURCE",
              "LOCK_WAIT")),
    (install, ("_status", "_known", "_scripts", "_build_index", "script_index")),
    (lists, ("_sources",)),
    (processes, ("_job", "_job_warned", "_ntdll", "start_process")),
    (saved, ("_read_cache",)),
    (cardstats, ("MIN_CARD_GAMES", "MIN_SPLIT_GAMES", "card_rows", "list_cards")),
    (runner, ("build_command", "_tidy_user_dir", "PROGRESS_GAP", "GAME_GRACE", "HEADER_TIMEOUT")),
    (ai, ("TAG_FILE", "MIN_GAMES_NEVER_CAST", "side_ai")),
    (views, ("list_item",)),
) for name in names}
_READ_THROUGH = ("list_item", "side_ai", "list_cards")


def _elsewhere(name):
    """The error for using a name in _OWNED on the package."""
    return AttributeError(f"forge.{name} is {_OWNED[name].__name__}.{name}: patch, set and read it there")


def __getattr__(name):
    """forge.list_item, forge.side_ai and forge.list_cards, read through to their part; for
    any other name in _OWNED, an error that says where it is now."""
    if name in _READ_THROUGH:
        return getattr(_OWNED[name], name)
    if name in _OWNED:
        raise _elsewhere(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class _Package(types.ModuleType):
    """The package, which won't take a name its parts own (_OWNED): forge._status = None,
    or a patch of forge.list_item, would change a copy nothing reads, so it fails."""

    def __setattr__(self, name, value):
        if name in _OWNED:
            raise _elsewhere(name)
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if name in _OWNED:
            raise _elsewhere(name)
        super().__delattr__(name)


sys.modules[__name__].__class__ = _Package
