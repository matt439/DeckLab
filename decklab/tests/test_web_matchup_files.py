"""Source checks of the matchup screens and their per-card numbers (Milestones 5 and 8).

These read the matchup scripts' and stylesheets' source only: no network, no server,
no Node. The shared helpers (_scripts, _styles, _function, ...) stay in test_web.
"""
import re
import unittest

from decklab.tests.test_web import MATCHUP_SCRIPTS, SCRIPTS, _enclosing_function, _function, _inner, _lib_text, _scripts, _styles, _text


class MatchupFileTests(unittest.TestCase):

    def test_matchup_screens_read_the_contract(self):
        # Milestone 5: the page reads exactly the JSON the shared contract gives (GET /api/matchups and
        # /api/matchup, POST run and stop, the deck view's "matchups", the "matchup_games" setting). The deck
        # page's Matchups tab is deck-tools.js's.
        script = _scripts([*MATCHUP_SCRIPTS, "deck-tools.js"])
        for text in ('"/api/matchups"', "/api/matchup?", '"/api/matchup/run"', '"/api/matchup/stop"',
                     "matchup_games", "default_games", "data.choices", "not_meaningful", "commander_unplayable",
                     "team_pump", "cannot_play", "never_cast", "games_per_min", "eta_s", "job.ahead", "current",
                     "data.notice", "data.error", "data.matchups", "winrate", "on_play", "on_draw",
                     "r.starter", "ai_timeouts"):
            with self.subTest(text=text):
                self.assertIn(text, script)
        # The games choice saves the profile's setting through the settings write.
        self.assertIn('{ matchup_games: String(n) }, "PUT"', _function(script, "saveGames"))

    def test_matchup_polling_stops_when_the_page_is_left(self):
        # All views use the same lifecycle-aware watcher; runtime tests cover cancellation.
        script = _scripts(MATCHUP_SCRIPTS)
        for name in ("follow", "followList"):
            body = _function(script, name)
            with self.subTest(function=name):
                self.assertIn("watchMatchupUpdates(", body)
        watcher = _function(script, "watchMatchupUpdates")
        self.assertIn("token === routeToken", watcher)
        self.assertIn('removeEventListener("visibilitychange"', watcher)

    def test_stopping_a_matchup_asks_first(self):
        script = _scripts(MATCHUP_SCRIPTS)
        calls = [m.start() for m in re.finditer(r'apiWrite\("/api/matchup/stop"', script)]
        self.assertEqual(len(calls), 2)     # the pair page, and an anonymous admin row/pill
        for at in calls:
            body = _enclosing_function(script, at)
            self.assertTrue(body.startswith(("async function stopRun(", "async function stopListedRun(")), body[:40])
            self.assertLess(body.index("await ask("), body.index('apiWrite("/api/matchup/stop"'))
            self.assertIn('value: "stop"', body)

    def test_matchup_routes_and_deck_page_part(self):
        # The rest of the page only gets small hooks: the routes (app.js), the nav's place (core.js's ROUTES), and
        # the deck page's part (deck.js) between Practice hands and Owned vs needed (in the section nav as
        # "Matchups").
        app = _scripts()
        route = _function(app, "route")
        self.assertIn('path === "matchups"', route)
        self.assertIn('path === "matchup"', route)
        self.assertIn('{ path: "matchups", label: "Matchups"', app)
        self.assertNotIn('href: "#/matchups"', _function(app, "drawLibrary"))     # the shell has it, not the page
        # The deck page's tabs: Matchups after Practice, drawn when it opens (the matchups part, the field and
        # the tests of changes). The price table is on the Cards tab, null for a visitor who may not see the
        # deck's collection.
        tabs = re.search(r"const DECK_TABS = \[(.*?)\];", app, re.S).group(1)
        self.assertLess(tabs.index('"practice"'), tabs.index('["matchups", "Matchups"]'))
        self.assertIn("return [deckMatchupsPart(data), fieldSection(data), variantTestsSection(data)];",
                      _function(app, "deckTabParts"))
        self.assertIn("ownedSection(data)", _function(app, "cardsParts"))
        self.assertIn('if (!("owned" in data)) return null;', _function(app, "ownedSection"))
        self.assertIn('id: "sec-matchups"', _function(_scripts(["deck-tools.js"]), "deckMatchupsPart"))
        # The tab strip sticks under the top bar, its tabs a little tighter on a phone.
        css = _styles()
        self.assertRegex(css, r"\.deck-tabs \{[^}]*position: sticky; top: var\(--shell-top\)")
        self.assertIn(".deck-tabs > button { padding: 0 var(--s-2); }", css)

    def test_win_rate_figures_and_range_bars(self):
        # E11-S30 slice 6 (design/visual-design.md 4.9), in place of MU-06's diverging green and red bars: a win rate
        # is sim-ui.js's mono figure in ink with its range bar on the fixed 20-80% scale, on the rows, the pair
        # page's verdict, a live run and the field part, and the old bar is gone. Beside a figure the bar is
        # decorative, the figure saying it once. Only the matrix's cells still shade around 50% (--win and --loss).
        script = _scripts([*MATCHUP_SCRIPTS, "field.js"])
        self.assertNotRegex(script, r"\bwinBar\(|drawWinBar|winBarKey|wb-bar")
        self.assertNotIn(".wb-", _styles())
        row = _function(script, "resultRow")
        self.assertIn("rangeBar(side.rate, { compact: true, muted, decorative: true })", row)
        self.assertIn("winRateFigure(side.rate, { what, barred: true })", row)
        verdict = _function(script, "resultPart")
        self.assertIn('winRateFigure(wr, { size: "hero", what, games: r.games, barred: true })', verdict)
        self.assertIn("rangeBar(wr, { axis: true, muted, decorative: true })", verdict)
        self.assertIn("rangeKey()", verdict)
        self.assertIn("rangeBar(job.range, { live: true", _function(script, "liveBox"))
        rows = _function(script, "fvRows")
        self.assertIn("rangeBar(o.rate, { compact: true, muted: o.not_meaningful, decorative: true })", rows)
        self.assertIn("winRateFigure(o.rate, { what, barred: true })", rows)
        headline = _function(script, "fvHeadline")
        self.assertIn('winRateFigure(average, { size: "hero", what, games: fvGames(a) || null, barred: true })', headline)
        self.assertIn("rangeBar(average, { axis: true, decorative: true })", headline)
        # Not a role="img" bar repeating the figure's words in a row link's name.
        self.assertNotRegex(row + rows, r"rangeBar\([^)]*\bwhat\b")
        matchups = re.sub(r"/\*.*?\*/", "", _text("matchups.css"), flags=re.S)
        shaded = [line for line in matchups.splitlines() if re.search(r"var\(--(win|loss)\)", line)]
        self.assertTrue(shaded)
        self.assertEqual([line for line in shaded if not line.startswith(".mu-h-")], [])
        components = _text("components.css")
        self.assertIn(".range-point {", components)
        self.assertIn(".wr-value { font-family: var(--font-mono);", components)

    # Milestone 5 review, round 2 (the matchup screens).

    def test_stop_says_every_finished_game_is_kept(self):
        # PAGE-1, QUALITY-1: a stopped run keeps every game that finished (a batch cut short counts the
        # games it finished), so no page text says "whole batches" any more.
        script = _scripts(MATCHUP_SCRIPTS)
        self.assertNotRegex(script, r"whole batches|batch(es)? (that )?finished|batches it")
        stop = _function(script, "stopRun")
        self.assertIn("Every game finished so far is kept and saved with the result", stop)
        # "Never cast" is only flagged from forge's MIN_GAMES_NEVER_CAST counted games, and a stopped run
        # can have fewer, so the casts table says when.
        forge = _lib_text("forge")
        flagged = re.search(r"^MIN_GAMES_NEVER_CAST = (\d+)", forge, re.M).group(1)
        self.assertIn(f"const NEVER_CAST_GAMES = {flagged};", script)
        self.assertIn("once ${NEVER_CAST_GAMES} games", _function(script, "castsPart"))
        # QUALITY-1: only counted games count towards it (a failed batch's games don't).
        self.assertIn('"been counted."', _function(script, "castsPart"))
        self.assertIn("before any game finished", script[script.index("function noticeBox(") - 400:
                                                         script.index("function noticeBox(")])

    def test_deck_page_rows_say_which_list_is_older(self):
        # E2E-4: a deck page's results can hold rows played with this deck's earlier list (sides[0]) as
        # well as ones whose opponent has changed since (sides[1]); its rows say which (their title and
        # screen-reader words), faded with a dashed edge and one key line above the list rather than a pill
        # on almost every row (UI review round 2). The list page, where neither deck is "this" one, keeps the
        # freshness badge's "retest: changed since".
        body = _function(_scripts(MATCHUP_SCRIPTS), "resultRow")
        self.assertIn('side.me.current === false ? "this list has changed since"', body)
        self.assertIn('side.them.current === false ? "the opponent\'s list has changed since"', body)
        self.assertIn('freshnessBadge(item.updated, { size: "row", compact: true, changed: !against && !!olderWords })', body)
        self.assertNotIn("Older list", body)
        self.assertIn("is-older", body)
        # "Earlier engine" only when the caller asks (MU-02: today's engine has results elsewhere and the pair has no
        # newer one), as a neutral tag; while every result is an earlier engine's, one line says so above the list.
        self.assertIn('if (engineTag && earlierEngine(item)) tags.push(status("plain", "Earlier engine"));', body)
        script = _scripts(MATCHUP_SCRIPTS)
        self.assertIn("anyTodaysEngine(results)", _function(script, "allEarlierLine"))
        self.assertIn("engineTag: engines && !pair.newer", _function(script, "deckMatchupList"))
        self.assertIn("engineTag: engines && !e.all.some((item) => !earlierEngine(item))", _function(script, "deckResultParts"))

    def test_list_answers_leave_the_form_error_alone(self):
        # PAGE-2: the list's answers came every 2 s while a run went and called changed(), which cleared
        # the form's error before it could be read. The form is a sheet now (openPlaySheet), which reads the
        # page's latest answer (live()) without the list's answers ever touching its error.
        script = _scripts(MATCHUP_SCRIPTS)
        draw = _function(script, "drawMatchups")
        follow = draw[draw.index("followList("):]
        self.assertNotIn("changed(", follow)
        self.assertNotIn("error.textContent", follow)
        sheet = _function(script, "openPlaySheet")
        self.assertNotIn("error.textContent", _inner(sheet, "refresh"))
        self.assertIn('error.textContent = ""', _inner(sheet, "changed"))
        self.assertIn("const data = live();", _inner(sheet, "refresh"))

    def test_picker_words_a_run_of_these_lists_by_its_status(self):
        # PAGE-3: a waiting run isn't "playing now"; one way to it (the button), not a link as well; and
        # the games choice, which a joined run ignores, is hidden meanwhile.
        refresh = _inner(_function(_scripts(MATCHUP_SCRIPTS), "openPlaySheet"), "refresh")
        self.assertIn("waiting their turn", refresh)
        self.assertIn("are playing now", refresh)
        self.assertIn("games.node.hidden = !!running", refresh)
        running = refresh[refresh.index("if (running) {"):refresh.index("} else if (saved)")]
        self.assertNotIn('el("a"', running)

    def test_matchup_links_are_big_enough_to_tap(self):
        # PAGE-4: the deck titles in the matchup page's deck boxes were 20 px tall.
        css = _styles()
        title = re.search(r"\.mu-side-title \{([^}]*)\}", css).group(1)
        self.assertIn("min-height: 44px", title)
        self.assertIn("align-self: stretch", title)
        self.assertRegex(css, r"\.mu-links a \{[^}]*min-height: 44px")

    def test_focus_goes_to_the_news_after_a_redraw(self):
        # PAGE-5: Stop's answer (or the poll that sees the run end) draws the page afresh, which took the
        # focused Stop button away and left the focus on the body.
        script = _scripts(MATCHUP_SCRIPTS)
        show = _function(script, "show")
        self.assertLess(show.index("drawMatchup(page, data)"), show.index("focusNews()"))
        self.assertIn('$("#main").contains(focused)', show)
        news = _function(script, "focusNews")
        self.assertIn('setAttribute("tabindex", "-1")', news)
        self.assertIn("preventScroll: true", news)
        ids = re.search(r"const NEWS_IDS = \[(.*)\];", script).group(1)
        for name in re.findall(r'"([\w-]+)"', ids):
            with self.subTest(id=name):
                self.assertRegex(script, rf'id: "{name}"')
        self.assertIn("focusNews()", _function(script, "stopRun"))   # the run ended while Stop asked

    def test_matchup_boxes_carry_their_status_icon(self):
        # PAGE-6: status carries an icon and a word, so every crit, warn or info box on the matchup pages
        # is a markedBox (its heading gets the icon), except the running box, which has its spinner.
        script = _scripts(MATCHUP_SCRIPTS)
        boxes = re.findall(r'class: [`"]box box-[^`"]*[`"]', script)
        self.assertEqual(sorted(boxes), sorted(['class: `box box-${kind}`', 'class: "box box-info mu-running"']))
        self.assertIn('class: "box-head"', _function(script, "markedBox"))
        css = _styles()
        for kind in ("warn", "crit"):
            with self.subTest(kind=kind):
                self.assertRegex(css, rf"\.status-{kind}::before, \.box-{kind} > \.box-head::before[^{{]*\{{")
        # An info box's icon is the notices' stroke info circle (design/visual-design.md 4.5), a mask in --warn-icon.
        self.assertRegex(css, r'\.box-info > \.box-head::before[^{]*\{[^}]*background: var\(--warn-icon\);[^}]*mask: url')

    def test_team_pump_box_names_its_example_as_one(self):
        # PAGE-7: the box read as if it were about the deck it's on ("...too low: Selesnya Rabbits by 12 to
        # 15 points"), on a Commander deck's page too.
        parts = _function(_scripts(MATCHUP_SCRIPTS), "aiLimitsParts")
        self.assertNotIn("too low: a go-wide", parts)
        self.assertIn("Forge rated a go-wide pump deck 12 to 15 points too low for this reason", parts)

    def test_team_pump_box_only_without_forge_scripts(self):
        # R19: the pilot box (pilotFlag) counts team pumps from Forge's card scripts, so the oracle tags'
        # box and chip are only a fallback for when those scripts can't be read (ai.pilot is null).
        script = _scripts(MATCHUP_SCRIPTS)
        self.assertIn("const pump = ai.pilot ? null : ai.team_pump;", _function(script, "aiLimitsParts"))
        self.assertIn('ai.pilot ? ai.pilot.poor && ai.pilot.why === "team_pumps"', _function(script, "aiChips"))

    def test_score_table_says_why_its_share_differs(self):
        # PAGE-9: the headline is balanced for play and draw, the score table's Share is plain wins/games.
        script = _scripts(MATCHUP_SCRIPTS)
        score = _function(script, "scorePanel")
        self.assertIn("wr.balanced !== false", score)
        self.assertIn("balanced for going first and second", score)
        self.assertIn("scorePanel(r, ta, tb, wr)", _function(script, "resultPart"))

    def test_bad_matchup_addresses_lead_back_to_matchups(self):
        # PAGE-10: "key must be the 64-character key of a matchup (error 400)" with "Try again" (which
        # can't help) and "Back to the library".
        app = _scripts()
        box = _function(app, "errorBox")
        self.assertIn("error.status !== 400 && error.status !== 404", box)
        self.assertIn("back[0]", box)
        self.assertIn("errorBox(title, e, route, back)", _function(app, "load"))
        script = _scripts(MATCHUP_SCRIPTS)
        show = _function(script, "showMatchup")
        self.assertLess(show.index("/^[0-9a-f]{64}$/i.test("), show.index("load("))
        self.assertIn("That link isn't a matchup's address", show)
        self.assertIn("MATCHUP_ERROR);", show)
        self.assertIn('back: ["#/matchups", "Back to Matchups"]', script)

    def test_pairing_links_name_both_halves(self):
        # PAGE-11: "+ Vampires" looked like an "add" button and read as "plus Vampires"; the Matchups part
        # also marks the pairings that have saved results.
        app = _scripts()
        links = _function(app, "pairingLinks")
        self.assertIn('text: `${own ? own.title : "This half"} + ${h.title}`', links)
        self.assertNotIn("`+ ${", links)
        self.assertIn("marks.catch(", links)       # a mark that can't be had isn't a page error
        script = _scripts(MATCHUP_SCRIPTS)
        self.assertIn('api("/api/matchups").then(resultCounts)', _function(_scripts(["deck-tools.js"]), "deckMatchupsPart"))
        self.assertIn('plural(n, "result")', _function(script, "resultCounts"))

    def test_shared_page_parts_are_written_once(self):
        # QUALITY-9: the progress bar, a row's names, pairing ids and sleep() were written out in several places
        # in app.js (since split into core.js and five more files) and matchups.js. (The editor's scripts aren't
        # counted: editor.js has its own copy of a deck id's "+" fix.)
        both = _scripts([name for name in SCRIPTS if not name.startswith("editor")])
        self.assertEqual(both.count('"progress-fill"'), 1)
        self.assertIn('"progress-fill"', _function(both, "progressBar"))
        self.assertEqual(both.count('class: "mu-names"'), 2)
        self.assertEqual(both.count("replace(/ /g, \"+\")"), 1)
        self.assertEqual(len(re.findall(r"`pairing/\$\{", both)), 2)
        self.assertIn("`pairing/${", _function(both, "pairingId"))
        self.assertIn("`pairing/${", _function(both, "sameDeckId"))
        self.assertEqual(both.count("new Promise((resolve) => setTimeout(resolve"), 1)
        self.assertIn("setTimeout(resolve", _function(both, "sleep"))
        # A run's bar is marked at its planned checks (checkBar, MU-11), which is a progressBar too.
        self.assertIn("progressBar(", _function(both, "practiceProgress"))
        self.assertIn("progressBar(label, tag)", _function(both, "checkBar"))
        for name in ("liveBox", "runningRow"):
            self.assertIn("checkBar(", _function(both, name))

    def test_rough_time_follows_forge_plan(self):
        # QUALITY-9: roughMinutes copies forge.plan's batch rule; the server's worker count wins when it sends
        # one, and the page's own numbers match config.json's default and forge/lists.py's smallest batch.
        # Since 2026-10-03 (R02) the rule is batchPlan, a copy of lists._batch_count, and config.json's
        # forge_batch_games (the server's "batch_games") no longer matters. test_forge_batchplan runs both.
        from decklab.lib import config
        script = _scripts(MATCHUP_SCRIPTS)
        forge = _lib_text("forge")
        consts = dict(re.findall(r"^const (FORGE_WORKERS|BIG_BATCH|SMALL_BATCH) = (\d+);", script, re.M))
        self.assertEqual(int(consts["FORGE_WORKERS"]), config.DEFAULTS["forge_workers"])
        self.assertNotIn("BIG_BATCH", consts)
        self.assertEqual(consts["SMALL_BATCH"], re.search(r"^SMALL_BATCH = (\d+)", forge, re.M).group(1))
        self.assertIn("Math.max(2, Math.min(workers, Math.floor(games / SMALL_BATCH)))", _function(script, "batchPlan"))
        self.assertIn("max(2, min(workers, games // SMALL_BATCH))",
                      re.search(r"^def _batch_count\(.*?(?=^\S|\Z)", forge, re.M | re.S).group(0))
        self.assertIn("batchPlan(games, workers)", _function(script, "roughMinutes"))
        self.assertIn("data.workers", _function(script, "batching"))
        self.assertNotIn("batch_games", _function(script, "batching"))
        # Wave 3's runModeChoice, which every place a run starts uses (the play sheet, a new matchup's play box
        # and "More games").
        self.assertEqual(script.count("const split = batching(data);"), 1)
        self.assertIn("{ commander, split, estimates: estimates && estimates.fixed", _function(script, "runModeChoice"))

    def test_matchup_page_reads_what_the_server_sends(self):
        # QUALITY-10: fallbacks for keys view() never sends (r.clock_s, adding up runs' batches), a string
        # form of AiLimits' unknown that forge never sends, and a roundabout filter.
        script = _scripts(MATCHUP_SCRIPTS)
        self.assertNotIn("r.clock_s", script)
        self.assertNotIn("run.batches", _function(script, "howPart"))
        self.assertNotIn('typeof u === "string"', script)
        self.assertIn("cannot.filter((c) => c.why === why)", _function(script, "aiLimitsParts"))

    def test_ai_limits_say_what_was_checked(self):
        # The deck page said "Forge's AI can play every card" with no games played (only the card scripts
        # had been checked), and never showed the cards its saved games never cast (forge.list_ai).
        script = _scripts(MATCHUP_SCRIPTS)
        parts = _function(script, "aiLimitsParts")
        self.assertIn("const judged = games >= NEVER_CAST_GAMES;", parts)
        # An all-clear is a plain sentence, not a green chip (UI kit: chips only for exceptions).
        self.assertRegex(parts, r'judged\s*\? el\("p", \{\}, el\("b", \{ text: "Forge\'s AI can play every card\." \}\),\s*'
                                r'` None is held back by its card scripts, and every spell was cast in \$\{whose\}\.`\)')
        self.assertNotIn('status("good"', parts)
        self.assertIn("Forge's card scripts don't stop its AI from playing any of these cards.", parts)
        # A list whose earlier engine's games never cast its commander says so instead of an all-clear.
        self.assertLess(parts.index('status("warn", "Earlier games: commander never cast")'),
                        parts.index('el("b", { text: "Nothing held back." })'))
        # A list Forge pilots poorly (pilotFlag's box) never gets the green "can play every card" line.
        self.assertIn("const poor = Boolean(ai.pilot && ai.pilot.poor);", parts)
        self.assertIn("if (!parts.length && !ai.problem && poor) {", parts)
        self.assertIn('status("info", judged ? "Every card cast" : "Nothing held back")', parts)
        self.assertIn("} else if (!parts.length && !ai.problem) {", parts)
        self.assertIn('"Cards it never casts show up here once "', parts)
        self.assertIn('deckPage ? "this list has played" : "this matchup has"', parts)
        # Never cast on the deck page is across all this list's games, not one matchup's.
        self.assertIn('deckPage ? "this list\'s" : "this matchup\'s"', parts)
        self.assertIn(", across all its matchups", parts)
        self.assertNotIn("WHY_WORDS", script)
        tab = _function(_scripts(["deck-tools.js"]), "drawDeckMatchups")
        self.assertIn("const earlier = earlierFlags(m);", tab)
        self.assertIn("aiLimitsParts(m.ai, s.title, {deckPage: true, otherSaid: !!otherLine, earlier})", tab)
        self.assertIn("aiLimitsParts(s.ai, s.title, { brief: muted })", _function(script, "resultPart"))
        api_text = _lib_text("api")
        self.assertIn('"ai": forge.list_ai(sections, kind, keep=lambda result: seen.result(forge, result))', api_text)

    def test_matchup_numbers_are_named(self):
        # QUALITY-11.
        script = _scripts(MATCHUP_SCRIPTS)
        self.assertIn("Math.min(MAX_BACKOFF, failures + 1)", _function(script, "watchMatchupUpdates"))
        self.assertIn("a practice run or a matchup", _scripts())

    # Milestone 8: per-card numbers from the card log.

    def test_card_stats_thresholds_mirror_forge(self):
        # The page calls per-card numbers early, and holds back a card's win-rate verdict, by forge's own
        # thresholds. The server sends them with the numbers (min_games, min_split); the page's copies are
        # for wording without them, and must say the same.
        script = _scripts(MATCHUP_SCRIPTS)
        forge = _lib_text("forge")
        for js, py in (("CARD_STATS_GAMES", "MIN_CARD_GAMES"), ("CARD_SPLIT_GAMES", "MIN_SPLIT_GAMES")):
            with self.subTest(name=js):
                value = re.search(rf"^{py} = (\d+)", forge, re.M).group(1)
                self.assertIn(f"const {js} = {value};", script)
        coverage = _function(script, "cardStatsCoverage")
        self.assertIn("if (!stats.enough)", coverage)
        self.assertIn("stats.min_games || CARD_STATS_GAMES", coverage)
        self.assertIn('status("warn", "Early numbers")', coverage)
        self.assertIn("stats.min_split || CARD_SPLIT_GAMES", _function(script, "winSplitWords"))

    def test_card_stats_read_forges_keys(self):
        # The page reads the keys forge's cardstats.py (CardStats, Row, CommanderRow), ai.py (a never_cast
        # card's drawn_games), views.py (each run's card_log) and install.py (status's card_log) write, spelt
        # the same on both sides; the api adds the deck page's pooled "cards".
        script = _scripts(MATCHUP_SCRIPTS)
        forge = _lib_text("forge")
        keys = ("games", "bad", "old", "of", "matchups", "enough", "min_games", "min_split", "rows", "commander",
                "name", "qty", "land", "drawn_games", "drawn_share", "copies_drawn", "cast", "cast_share", "stuck",
                "stuck_share", "discarded", "other_casts", "avg_turn", "wr_drawn", "wr_not", "diff", "judged",
                "verdict", "cast_games", "cast_share", "casts", "avg_first_turn", "wr_cast", "wr_not_cast",
                "card_log", "card_log_problem")
        for key in keys:
            with self.subTest(key=key):
                self.assertRegex(script, rf"\.{key}\b")
                self.assertIn(f'"{key}"', forge)
        self.assertIn("r.cards", _function(script, "castsPart"))
        self.assertIn("m.cards", _function(script, "deckCardStats"))
        self.assertIn('"cards"', _lib_text("api"))
        for verdict in ('"more"', '"less"'):
            self.assertIn(verdict, _function(script, "winSplitWords"))

    def test_matchup_result_shows_each_sides_cards(self):
        # castsPart is the per-card part when either side has counted games with card data, else "What each
        # deck cast" as before: one panel per side, the commander first, then spells, then lands.
        script = _scripts(MATCHUP_SCRIPTS)
        casts = _function(script, "castsPart")
        handoff = "if (r.cards && r.cards.some((side) => side && side.games)) return cardStatsPart(r, sides);"
        self.assertLess(casts.index(handoff), casts.index('"What each deck cast"'))
        # Card data whose games all failed their checks (games 0) keeps the casts table, which counts every
        # game, and says there why there are no per-card numbers; only with no casts either is that said alone.
        self.assertLess(casts.index('"What each deck cast"'), casts.index("stats ? cardStatsCoverage(stats) : null"))
        self.assertIn("return stats ? cardStatsPart(r, sides) : null;", casts)
        part = _function(script, "cardStatsPart")
        self.assertIn('el("summary", { text: "How each deck\'s cards played" })', part)
        self.assertIn('class: "more mu-cards"', part)
        self.assertIn('el("div", { class: "panels" }, sideTitles(sides).map(', part)
        self.assertIn("No card data for this deck.", part)
        groups = _function(script, "cardStatsGroups")
        self.assertLess(groups.index('"Commander"'), groups.index('"Spells"'))
        self.assertLess(groups.index('"Spells"'), groups.index('"Lands"'))
        self.assertIn("row.land === true", groups)
        # "From N of M games", and why not the rest: earlier games were played before the card log, logged by
        # an earlier version of it, or their card log failed its checks. The page calls the failed ones one
        # thing, and says once what the checks do.
        coverage = _function(script, "cardStatsCoverage")
        self.assertIn("`From ${thousands(games)} of ", coverage)
        self.assertIn("played without the card log (before", coverage)
        # Games an earlier card log kept (stats.old) are told apart from those, not called played without it.
        self.assertIn("logged by an earlier version of the card log, which counted casts", coverage)
        self.assertIn("const without = Math.max(0, of - games - bad - old);", coverage)
        self.assertIn('const checks = "(which make sure every card move adds up)";', coverage)
        self.assertEqual(coverage.count("failed its"), 2)
        self.assertIn("\"games' card logs failed their\"", coverage)
        self.assertEqual(coverage.count("checks ${checks}"), 2)
        self.assertNotRegex(script, r"didn't add up|logs? added up|didn't pass Deck Lab's checks")
        # Card names open the card on the deck page only: the matchup page has no card data to show.
        # Each side's names open the card viewer, one swipe group per deck.
        self.assertIn("cardStatsGroups(r.cards[i], { links: true, group: `matchup-cards-${i}` })", part)
        self.assertIn("cardStatsGroups(stats, { links: true })", _function(script, "deckCardStats"))
        self.assertIn("if (links) return cardLink(", _function(script, "cardStatsName"))

    def test_card_tables_fit_a_phone(self):
        # 390 px: at most four narrow number columns, one <tbody> per card with the rest of its numbers across
        # the row under it (tr.label-row), so no table is wider than its panel and names keep some room.
        script = _scripts(MATCHUP_SCRIPTS)
        css = _styles()
        for name in ("cardStatsTable", "commanderStatsTable"):
            body = _function(script, name)
            with self.subTest(table=name):
                self.assertLessEqual(body.count('el("col", { class: "c-'), 4)
                self.assertLessEqual(len(re.findall(r'el\("td", \{ class: "num', body)), 4)
                self.assertIn('el("tbody", { class:', body)
                self.assertIn('el("tr", { class: "label-row" }', body)
        widths = dict(re.findall(r"\.card-table col\.(c-n|c-turn) \{ width: ([\d.]+)em; \}", css))
        self.assertEqual(set(widths), {"c-n", "c-turn"})
        self.assertLessEqual(3 * float(widths["c-n"]) + float(widths["c-turn"]), 14)
        self.assertRegex(css, r"\.card-table \.num \{[^}]*white-space: nowrap")
        # Numbers are written in ink, never in a series colour; a card never cast says so in words too.
        self.assertNotRegex(css, r"\.(card-table|stand-out|drawn-n)[^{]*\{[^}]*color: var\(--series")
        self.assertIn('status("warn", lands ? "Drawn, never played" : "Drawn, never cast")',
                      _function(script, "cardStatsNotes"))

    def test_card_win_rates_say_only_what_they_can(self):
        # A verdict in words only once a card is judged (min_split games each way); before that, "Not
        # enough games to tell" with the counts. The difference always comes with its range, and the key says
        # once what each figure means, including that long games draw more cards.
        script = _scripts(MATCHUP_SCRIPTS)
        words = _function(script, "winSplitWords")
        self.assertLess(words.index("if (!row.judged"), words.index("Won more when ${act}"))
        # A land is never judged (cardstats.py): its rates and "No verdict for a land", before any other
        # words, and the key says once why (PageScriptTests run these).
        self.assertLess(words.index("if (row.land === true && yes)"), words.index("if (!row.judged"))
        self.assertIn("return `${rates} No verdict for a land.`;", words)
        # The difference beside the rates is the difference of the rates as shown (one decimal each), and the
        # deck page's lead shows the same one.
        self.assertIn('el("b", { text: gapWords(yes, no) })', words)
        self.assertIn("const gap = rateTenths(yes.value) - rateTenths(no.value);", _function(script, "gapWords"))
        self.assertIn("`${gapWords(r.wr_drawn, r.wr_not)} (${pointsWords(r.diff.low)} to `",
                      _function(script, "standOutParts"))
        for text in ("Not enough games to tell", "Won more when ${act}", "Won less when ${act}",
                     '"No clear difference"', "pointsWords(d.low)", "pointsWords(d.high)"):
            with self.subTest(text=text):
                self.assertIn(text, words)
        key = _function(script, "cardStatsKey")
        for text in ("Long games draw more cards", "as both cast and stuck",
                     "not balanced for play and draw", "95% range", "lands beyond the turns",
                     '["Lands", "No win-rate verdict, only the two win rates'):
            with self.subTest(text=text):
                self.assertIn(text, key)
        self.assertIn("cardStatsKey(commander)", _function(script, "cardStatsPart"))
        self.assertIn("cardStatsKey(", _function(script, "deckCardStats"))
        # A range end that isn't 0 never prints as "0" (a clear verdict's range would seem to touch 0): it
        # gets the decimals it needs instead of rounding to whole points.
        points = _function(script, "pointsWords")
        self.assertIn("while (v !== 0 && digits < 4 && Number(Math.abs(v).toFixed(digits)) === 0) digits++;", points)
        self.assertIn('Number(size) === 0 ? "0"', points)
        self.assertNotIn("Math.round", points)
        # A card in nearly every game has too few games without it to compare with, and more games barely
        # change that: it's said so, not "yet".
        self.assertIn("const NEARLY_EVERY_GAME = 0.95;", script)
        nearly = words.index("(inGames || 0) / games >= NEARLY_EVERY_GAME")
        self.assertLess(nearly, words.index("Not enough games to tell a win-rate difference yet"))
        self.assertIn("in nearly every game (", words)
        self.assertIn("so there are no games without it to ", words)
        # Casts from anywhere but the hand and discards are said for a card never drawn too (a card milled and
        # cast from the graveyard): "Not drawn" no longer returns early. other_casts counts every zone but the
        # hand and the command zone, the library included, so the words don't name only some of them.
        notes = _function(script, "cardStatsNotes")
        self.assertNotIn("return `Not drawn", notes)
        self.assertLess(notes.index("Not drawn in any of the"), notes.index("if (row.other_casts)"))
        self.assertIn("from anywhere but the hand (the ` +", notes)
        self.assertIn('"graveyard, exile, the library...)"', notes)
        self.assertNotIn("outside the hand", script)

    def test_deck_page_leads_with_what_stands_out(self):
        # "How its cards played" sits between "What Forge's AI can't play" and "Results": what stands out
        # first (counted), then every card's numbers, collapsed.
        script = _scripts(MATCHUP_SCRIPTS)
        # Since the UI review (DK-13) the results come first, as they answer the question.
        section = _function(_scripts(["deck-tools.js"]), "drawDeckMatchups")
        ai = "aiLimitsParts(m.ai, s.title, {deckPage: true, otherSaid: !!otherLine, earlier})"
        self.assertLess(section.index('text: "Head to head"'), section.index(ai))
        self.assertLess(section.index(ai), section.index("deckCardStats(m, version, {otherSaid: !!otherLine})"))
        deck = _function(script, "deckCardStats")
        self.assertIn('el("h3", { text: "How its cards played" })', deck)
        self.assertIn("cardStatsCoverage(stats, true, { otherSaid })", deck)
        self.assertLess(deck.index("standOutParts(stats)"), deck.index('el("details", { class: "more mu-cards" }'))
        lead = _function(script, "standOutParts")
        for text in ("r.stuck_share >= STUCK_NOTED", "r.copies_drawn >= STUCK_MIN_COPIES", "slice(0, STUCK_SHOWN)",
                     '"Most often stuck in hand: "', 'status("warn", "Drawn, never cast")', "slice(0, CLEAR_SHOWN)",
                     "game length can be the cause rather than the card"):
            with self.subTest(text=text):
                self.assertIn(text, lead)
        # What's said about stuck spells is said only of those drawn often enough to count, and names how
        # many weren't (a 1-of drawn 15 times could be stuck more often than any counted spell).
        self.assertIn("r.copies_drawn < STUCK_MIN_COPIES", lead)
        # Its clear win-rate differences are judged rows, and never a land's.
        self.assertIn("rows.filter((r) => r.judged && r.diff && r.wr_drawn && r.wr_not && r.land !== true)", lead)
        self.assertIn("`no spell with ${STUCK_MIN_COPIES} or `", lead)
        self.assertEqual(lead.count("${fewWords}"), 2)
        self.assertNotIn('"no spell had more than "', lead)
        # No card data and no saved results of this list (only the deck's earlier lists'): nothing to say.
        # list_cards pools only this list's results, so "none of its saved games kept the card log" would be wrong.
        self.assertIn("r.sides[0].current !== false)) return null;", deck)

    def test_card_log_on_or_off_is_said(self):
        # Status: per-card stats off, and why. Each run: whether it kept the card log. A card never cast:
        # how often it was drawn, when card data covers it.
        script = _scripts(MATCHUP_SCRIPTS)
        box = _function(script, "forgeBox")
        self.assertLess(box.index("forge.ready === false"), box.index("forge.card_log"))
        self.assertIn('status("warn", "Per-card stats are off")', box)
        self.assertIn("log.problem", box)
        how = _function(script, "howPart")
        self.assertIn("cardLogWords(runs)", how)
        # A run's reason is a whole sentence, so it follows "Card log off." rather than a colon.
        self.assertIn('run.card_log === false ? ["Card log off.", run.card_log_problem ? ` ${run.card_log_problem}`',
                      how)
        self.assertNotIn("No card log: ${run.card_log_problem", how)
        self.assertIn('run.card_log === true', _function(script, "cardLogWords"))
        parts = _function(script, "aiLimitsParts")
        self.assertIn('why === "never_cast" && cards.some((c) => c.drawn_games != null)', parts)
        self.assertIn("`drawn in ${gamesWords(c.drawn_games)}, never cast`", _function(script, "neverCastNames"))


if __name__ == "__main__":
    unittest.main()
