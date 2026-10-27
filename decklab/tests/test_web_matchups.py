"""Web matchups tests; shared fixtures remain in test_web."""
import unittest
import json
import random
import re
from decklab.tests.test_web import (
    MATCHUP_SCRIPTS, NODE, _function, _run_page, _scripts,
    _text,
)


class AdaptivePlayTests(unittest.TestCase):
    """Wave 3's run modes on the matchup page (matchups.js; sim-wave3-contract.md section 9.4): the
    "What do you want to know?" radios with the server's rough times, Play sending the mode, the live
    box's plan, dashed live range and the link to a field run or a test that plays the matchup, and
    the adaptive run's sentence in "How these games were played"."""

    ESTIMATES = {"fixed": {"200": [0.2, 0.5], "400": [0.5, 1.0], "800": [1, 3]}, "assess": [2, 6], "ahead": [1.4, 13.7]}

    @unittest.skipUnless(NODE, "needs Node.js")
    def test_the_modes_and_their_rough_times(self):
        data = {"choices": [200, 400, 800], "default_games": 400, "format": "Constructed", "workers": 16,
                "estimates": self.ESTIMATES}
        [text, fixed, without] = _run_page([
            f"runModeChoice({json.dumps(data)}).node",
            f"(() => {{ state.matchupMode = 'fixed'; const c = runModeChoice({json.dumps(data)}); "
            f"return JSON.stringify(c.value()); }})()",
            f"(() => {{ state.matchupMode = undefined; const c = runModeChoice({json.dumps(dict(data, estimates=None))}); "
            f"return JSON.stringify(c.value()) + c.node.textContent; }})()"])
        # One run vocabulary (UI review MU-05): Quick look, Settle it and Precise, with only the picked one's
        # words and its one time estimate; a set number of games under "More options".
        self.assertTrue(text.startswith("How long to playQuick lookSettle itPrecise"), text)
        self.assertIn("PrecisePlays until the win rate is known to within 3 points either way (usually 700-1,100 games). "
                      "About 2-6 minutes.More options", text)
        self.assertNotIn("About 1-14 minutes", text)                 # Settle it's time shows only when it's picked
        self.assertIn("More optionsA set number of games200400800", text)
        self.assertEqual(text.count("About"), 1)                     # one time estimate
        self.assertEqual(json.loads(fixed), {"mode": "fixed", "games": 400})
        self.assertTrue(without.startswith('{"mode":"assess","games":null}'), without)
        self.assertNotIn("About 2-6", without)          # no estimates: Milestone 0's speeds instead

    @unittest.skipUnless(NODE, "needs Node.js")
    def test_a_quick_look_and_a_set_number(self):
        # A Quick look is 200 games; a profile whose usual choice is a set 200 games starts on it, and another set
        # number opens "More options" with that number picked.
        data = {"choices": [200, 400, 800], "default_games": 400, "format": "Constructed", "workers": 16,
                "estimates": {"fixed": {"200": [0.2, 0.5], "400": [0.5, 1.0]}, "assess": [2, 6], "ahead": [1, 14]}}
        quick, custom = _run_page([
            f"(() => {{ state.matchupMode = 'fixed'; state.matchupGames = 200; const c = runModeChoice({json.dumps(data)}); "
            f"return JSON.stringify(c.value()) + c.node.textContent; }})()",
            f"(() => {{ state.matchupMode = 'fixed'; state.matchupGames = 400; const c = runModeChoice({json.dumps(data)}); "
            f"const walk = (n) => [n, ...(n.children || []).flatMap(walk)]; "
            f"return JSON.stringify(c.value()) + '|' + (walk(c.node).find((n) => n.tag === 'details').getAttribute('open') !== null); }})()"])
        self.assertTrue(quick.startswith('{"mode":"fixed","games":200}'), quick)
        self.assertIn("200 games: a first idea. Under a minute.", quick)
        self.assertEqual(custom, '{"mode":"fixed","games":400}|true')

    @unittest.skipUnless(NODE, "needs Node.js")
    def test_the_plain_verdict(self):
        # The result page leads with a verdict anyone can read (MU-04), from the lead and the win rate.
        def call(value, verdict=None, side=None, muted=False):
            result = {"winrate": {"value": value}, "not_meaningful": muted,
                      "lead": {"verdict": verdict, "side": side} if verdict else None}
            return f"JSON.stringify(plainVerdict({json.dumps(result)}, ['Angels', 'Rabbits']))"
        found = [json.loads(x) for x in _run_page([
            call(0.918, "ahead", 0), call(0.13, "ahead", 1), call(0.66, "ahead", 0), call(0.53, "slightly_ahead", 0),
            call(0.5, "about_even"), call(0.6, "not_settled"), call(0.9, "ahead", 0, muted=True), call(0.97),
            call(0.48)])]
        self.assertEqual([f["text"] for f in found], [
            "Angels is a big favourite: wins about 9 in 10",
            "Rabbits is a big favourite: wins about 9 in 10",
            "Angels is the favourite: wins about 7 in 10",
            "Angels has a slight edge: wins a little over half the games",
            "These two are about even: each wins about half the games",
            "Too close to call so far: Angels has won 60% of the games",
            "These games don't say anything about the real decks",
            "Angels is a big favourite: wins nearly every game",
            "These two are about even: each wins about half the games"])
        self.assertEqual([f["kind"] for f in found], ["win", "loss", "win", "win", "even", "open", "none", "win", "even"])

    @unittest.skipUnless(NODE, "needs Node.js")
    def test_pairs_choose_the_current_lists_before_the_engine(self):
        # One entry per pair (MU-01): a pair's best result is today's lists with today's engine, then today's lists;
        # choosing the opponent table must not change that rule or lose the pair's earlier results.
        side = lambda i, t, cur=True: {"id": i, "version": "target", "title": t, "current": cur}
        today = {"kind": "decklab", "current": True}
        old = {"kind": "decklab", "current": False}
        results = [
            {"key": "1" * 64, "format": "Constructed", "sides": [side("casual/a", "A"), side("casual/b", "B", False)],
             "winrate": {"value": 0.3}, "games": 400, "engine": today, "updated": "2026-10-05T10:00:00"},
            {"key": "2" * 64, "format": "Constructed", "sides": [side("casual/b", "B"), side("casual/a", "A")],
             "winrate": {"value": 0.8}, "games": 400, "engine": old, "updated": "2026-10-04T10:00:00"},
            {"key": "3" * 64, "format": "Constructed", "sides": [side("casual/a", "A"), side("casual/b", "B")],
             "winrate": {"value": 0.6}, "games": 400, "engine": old, "updated": "2026-10-03T10:00:00"}]
        pairs = _run_page([
            f"(() => {{ const p = pairsOf({json.dumps(results)}); const [only] = [...p.values()]; "
            f"return JSON.stringify([p.size, only.latest.key[0], only.earlier.map((i) => i.key[0]), only.newer]); }})()"])[0]
        self.assertEqual(json.loads(pairs), [1, "2", ["1", "3"], True])     # B's 80% with today's lists wins

    @unittest.skipUnless(NODE, "needs Node.js")
    def test_opponent_views_share_sorted_results_and_exact_perspective(self):
        side = lambda name, current=True: {"id": f"casual/{name.lower()}", "title": name,
                                           "version": "target", "current": current}
        def result(key, a, b, value, low, high, **extra):
            return {"key": key * 64, "format": "Constructed", "sides": [a, b], "games": 400,
                    "winrate": {"value": value, "low": low, "high": high}, "engine": {"current": True},
                    "updated": "2026-10-05T10:00:00", **extra}
        decks = [side(name) for name in ("A", "B", "C", "D", "E", "Z")]
        results = [result("1", side("B"), side("A"), .8, .7, .9),
                   result("2", side("A"), side("C"), .65, .6, .7),
                   result("3", side("A"), side("D"), .99, .98, 1, not_meaningful=True),
                   result("4", side("A"), side("E", False), .5, .45, .55),
                   result("5", side("A"), side("Hidden"), .9, .8, 1),
                   result("6", side("A"), side("Z"), .9, .8, 1, format="Commander")]
        script = f"""
          const decks={json.dumps(decks)}, pairs=pairsOf({json.dumps(results)});
          const {{entries,others}}=matchupEntries(decks[0],decks,pairs,'Constructed');
          const walk=n=>[n,...(n.children||[]).flatMap(walk)];
          const table=matchupOpponentTable(entries), links=matchupOpponentLinks(entries);
          const tableNode=walk(table).find(n=>n.tag==='table');
          const thead=walk(tableNode).find(n=>n.tag==='thead');
          const tbody=walk(tableNode).find(n=>n.tag==='tbody');
          const anchors=n=>walk(n).filter(n=>n.tag==='a');
          return JSON.stringify({{
            entries:entries.map(e=>[e.side.them.id,e.side.rate,e.side.href,!!e.muted,e.olderWords]),
            others:others.map(d=>d.id),tableTag:tableNode.tag,
            headers:walk(thead).filter(n=>n.tag==='th').map(n=>n.textContent),
            tableLinks:anchors(tbody).map(n=>[n.textContent,n.getAttribute('href')]),
            linkTag:links.tag,linkRows:links.children.map(n=>n.tag),
            links:anchors(links).map(n=>[n.getAttribute('href'),n.getAttribute('aria-label')]),
            tableWords:table.textContent,linkWords:links.textContent,
            figureCounts:[table,links].map(n=>walk(n).filter(n=>(n.getAttribute('class')||'').split(' ').includes('wr')).length),
            decorativeBars:[table,links].map(n=>walk(n).filter(n=>(n.getAttribute('class')||'').split(' ').includes('range-bar'))
              .every(n=>n.getAttribute('aria-hidden')==='true'))
          }});
        """
        answer = json.loads(_run_page([f"(() => {{{script}}})()"])[0])
        self.assertEqual([row[0] for row in answer["entries"]], ["casual/c", "casual/e", "casual/b", "casual/d"])
        reversed_rate = answer["entries"][2][1]
        for key, expected in (("value", .2), ("low", .1), ("high", .3)):
            self.assertAlmostEqual(reversed_rate[key], expected)
        self.assertEqual(answer["others"], ["casual/z"])
        self.assertEqual(answer["tableTag"], "table")
        self.assertEqual(answer["headers"], ["Opponent", "Win rate", "95% range", "Range", "Games", "Flag"])
        self.assertEqual([row[0] for row in answer["tableLinks"]], ["C", "E", "B", "D"])
        self.assertEqual([row[1] for row in answer["tableLinks"]], [row[0] for row in answer["links"]])
        self.assertEqual(answer["linkTag"], "ul")
        self.assertEqual(answer["linkRows"], ["li"] * 4)
        self.assertEqual(answer["figureCounts"], [4, 4])
        self.assertEqual(answer["decorativeBars"], [True, True])
        for href, label in answer["links"]:
            self.assertTrue(href.startswith("#/matchup?"), href)
            self.assertEqual(label.lower().count("win rate"), 1, label)
            self.assertNotIn("400", label)       # metadata is visible, not repeated in the row's spoken name
            self.assertNotIn("2026", label)
        self.assertIn("65 percent", answer["links"][0][1])
        self.assertIn("range 60 to 70", answer["links"][0][1])
        self.assertIn("changed since", answer["links"][1][1].lower())
        self.assertIn("not meaningful", answer["links"][-1][1].lower())
        for words in (answer["tableWords"], answer["linkWords"]):
            self.assertIn("Not meaningful", words)
            self.assertNotIn("strong against", words)
            self.assertNotIn("weak against", words)     # raw win rates do not supply field residual flags

    @unittest.skipUnless(NODE, "needs Node.js")
    def test_opponent_old_engine_links_and_unplayed_targets_respect_run_gate(self):
        data = {"key": "e" * 64, "format": "Constructed", "games": 100,
                "sides": [{"id": "casual/a", "title": "A", "version": "target", "current": True},
                          {"id": "casual/b", "title": "B", "version": "target", "current": True}],
                "winrate": {"value": .6, "low": .5, "high": .7}, "engine": {"current": False}}
        script = f"""
          const item={json.dumps(data)},decks=[...item.sides,{{id:'casual/c',title:'C',version:'target'}}];
          const {{entries,others}}=matchupEntries(decks[0],decks,pairsOf([item]),'Constructed');
          const walk=n=>[n,...(n.children||[]).flatMap(walk)];
          const table=matchupOpponentTable(entries),links=matchupOpponentLinks(entries);
          const tagged=matchupEntries(decks[0],decks,pairsOf([item]),'Constructed',true).entries;
          globalThis.mayStartRuns=()=>true;
          const allowed=notPlayedLine(decks[0],others);
          globalThis.mayStartRuns=()=>false;
          const blocked=notPlayedLine(decks[0],others);
          return JSON.stringify([walk(table).filter(n=>n.tag==='a').map(n=>n.getAttribute('href')),
            walk(links).filter(n=>n.tag==='a').map(n=>n.getAttribute('href')),
            walk(allowed).filter(n=>n.tag==='a').map(n=>n.getAttribute('href')),
            walk(blocked).filter(n=>n.tag==='a').length,blocked.textContent,notPlayedLine(decks[0],[]),
            table.textContent,matchupOpponentTable(tagged).textContent,matchupOpponentLabel(tagged[0])]);
        """
        table, links, allowed, blocked_links, blocked_words, empty, plain, tagged, label = json.loads(
            _run_page([f"(() => {{{script}}})()"])[0])
        self.assertEqual(table, [f"#/matchup?key={'e' * 64}"])
        self.assertEqual(links, table)
        self.assertEqual(len(allowed), 1)
        self.assertIn("b=casual%2Fc", allowed[0])
        self.assertEqual(blocked_links, 0)
        self.assertIn("Not played yet against: C", blocked_words)
        self.assertIsNone(empty)
        self.assertNotIn("Earlier engine", plain)      # an all-earlier list explains it once above the rows
        self.assertIn("Earlier engine", tagged)        # mixed-engine lists mark the older exception
        self.assertIn("earlier engine", label)

    @unittest.skipUnless(NODE, "needs Node.js")
    def test_the_matchups_page_works_while_the_settings_cant_be_read(self):
        # The settings answer 503 while the database is down: the page still draws, without the
        # profile's choices, and it uses them when they can be read.
        setup = ("state.profile = {id: 'matt', name: 'Matt'}; globalThis.seen = []; globalThis.drawn = 0; "
                 "globalThis.mainNode = el('main'); $ = (s) => s === '#main' ? mainNode : null; "
                 "load = (paths, token, draw) => { seen.push(paths); draw([{decks: []}, {results: []}]); }; "
                 "drawMatchups = () => { drawn += 1; }; ''")
        down = "api = () => Promise.reject(new ApiError(503, 'Database down', {reason: 'database'})); ''"
        up = "api = () => Promise.resolve({matchup_games: '1600', matchup_mode: 'ahead'}); ''"
        result = "JSON.stringify([seen, drawn, state.matchupGames || null, state.matchupMode || null])"
        broken = _run_page([setup, down, "await showMatchups({}, routeToken)", result])[-1]
        self.assertEqual(json.loads(broken), [[["/api/decks", "/api/matchups"]], 1, None, None])
        working = _run_page([setup, up, "await showMatchups({}, routeToken)", result])[-1]
        self.assertEqual(json.loads(working), [[["/api/decks", "/api/matchups"]], 1, 1600, "ahead"])

    @unittest.skipUnless(NODE, "needs Node.js")
    def test_the_loading_state_shows_while_the_settings_are_read(self):
        # A slow settings answer: the loading state replaces the last page at once, and a route
        # changed meanwhile never loads the matchups.
        setup = ("state.profile = {id: 'matt', name: 'Matt'}; globalThis.seen = []; "
                 "globalThis.mainNode = el('main'); $ = (s) => s === '#main' ? mainNode : null; "
                 "load = (paths) => { seen.push(paths); }; "
                 "globalThis.answer = null; api = () => new Promise((resolve) => { answer = resolve; }); "
                 "$('#main').append(el('p', {text: 'The last page'})); ''")
        [_, waiting, after] = _run_page([
            setup,
            "(() => { globalThis.done = showMatchups({}, routeToken); return $('#main').textContent; })()",
            "await (async () => { routeToken += 1; answer({}); await done; return JSON.stringify(seen); })()"])
        self.assertNotIn("The last page", waiting)
        self.assertIn("Loading", waiting)
        self.assertEqual(json.loads(after), [])

    @unittest.skipUnless(NODE, "needs Node.js")
    def test_the_first_mode_is_this_devices_then_the_profiles(self):
        # A matchup page opened directly: the answer's default_mode (the profile's matchup_mode) until a mode
        # is picked here; an unknown one, or none, is "assess".
        calls = [f"(() => {{ state.matchupMode = {json.dumps(mine)}; "
                 f"return startingMode({json.dumps({'default_mode': profiles})}); }})()"
                 for mine, profiles in ((None, "ahead"), ("fixed", "ahead"), (None, "both"), (None, None))]
        self.assertEqual(_run_page(calls), ["ahead", "fixed", "assess", "assess"])

    @unittest.skipUnless(NODE, "needs Node.js")
    def test_more_games_words_follow_the_mode(self):
        side = {"id": "casual/a", "version": "target", "title": "A", "current": True}
        data = {"key": "k" * 64, "format": "Constructed", "sides": [side, dict(side, id="casual/b", title="B")],
                "choices": [200, 800], "default_games": 800, "status": "done",
                "result": {"engine": {"kind": "decklab", "run_version": 2, "current": True, "words": None}}}
        fresh = dict(data, result={"engine": {"kind": "v1", "run_version": 1, "current": False, "words": "old"}})
        calls = [f"(() => {{ state.matchupMode = {json.dumps(mode)}; state.matchupGames = 800; "
                 f"return actionsPart({{}}, {json.dumps(d)}).textContent; }})()"
                 for mode, d in (("assess", data), ("fixed", data), ("ahead", fresh), ("fixed", fresh))]
        texts = _run_page(calls)
        self.assertIn("How long to playQuick lookSettle itPrecise", texts[0])
        for text, words in zip(texts, ("Play more", "Play 800 more games", "Play with today's engine",
                                       "Play 800 games with today's engine")):
            self.assertIn(words, text)
            self.assertIn("Swap sides", text)

    @unittest.skipUnless(NODE, "needs Node.js")
    def test_estimate_words(self):
        calls = [f"estimateWords({json.dumps(span)})" for span in
                 ([0.2, 0.8], [2, 6], [3, 3.2], [40, 110], [100, 200], None)]
        self.assertEqual(_run_page(calls), ["under a minute", "about 2-6 minutes", "about 3 minutes",
                                            "about 40 minutes to 2 hours", "about 2-3 hours", ""])

    @unittest.skipUnless(NODE, "needs Node.js")
    def test_why_an_adaptive_run_stopped(self):
        titles = '["Gruul Ramp", "Izzet Prowess"]'
        base = {"games_after": 1600, "half_width": 0.028, "looks": []}
        cases = [
            (dict(base, outcome="ahead", decision="ahead"), {"verdict": "ahead", "side": 1},
             "This run stopped at a planned check after 1,600 games: Izzet Prowess is clearly ahead."),
            (dict(base, outcome="precise"), None,
             "This run stopped at a planned check after 1,600 games: the win rate is known to within ±2.8 points "
             "of win rate."),
            (dict(base, outcome="about_even", decision="about_even"), {"verdict": "about_even", "side": None},
             "This run stopped at a planned check after 1,600 games: the decks are about even (within 5 points of "
             "win rate)."),
            (dict(base, games_after=3200, outcome="not_settled"), {"verdict": "not_settled", "side": None},
             "This run stopped at a planned check after 3,200 games: it reached 3,200 games without a clear leader."),
            (dict(base, games_after=650, outcome="stopped", decision="not_settled_stopped",
                  range={"value": 0.55, "low": 0.49, "high": 0.62}), {"verdict": "not_settled", "side": None},
             "Stopped early after 650 games, between checks. A range that allows for stopping at any time: 49-62 %. "
             "Not settled."),
            (dict(base, games_after=650, outcome="stopped", decision="ahead", range=None), {"verdict": "ahead", "side": 0},
             "Stopped early after 650 games, between checks. Gruul Ramp is clearly ahead even so."),
        ]
        calls = [f"adaptiveWords({json.dumps(s)}, {json.dumps(lead)}, {titles})" for s, lead, _ in cases]
        calls.append('adaptiveDetails({"looks": [{"z": -3.41, "bound": 3.0}]})')
        self.assertEqual(_run_page(calls), [words for *_, words in cases] + ["z = 3.41; needed 3.00"])

    def test_play_sends_the_mode_and_the_live_box_follows_the_plan(self):
        script = _scripts(MATCHUP_SCRIPTS)
        box = _function(script, "playBox")
        self.assertIn("runModeChoice(data)", box)
        self.assertIn('text: "Play"', box)
        play = _function(script, "play")
        self.assertIn("mode: asked.mode", play)
        self.assertIn('if (asked.mode === "fixed") body.games = asked.games;', play)
        self.assertIn("answer.joined", play)
        self.assertIn("Joined the run already playing", play)
        live = _function(script, "liveBox")
        for words in ("Next check at", "Planned: ", "to within 3 points either way", "of up to ",
                      "Live range: wider while games are still being played", "open it to stop or follow it",
                      "job.via", "actions.hidden = true", 'left${job.plan ? " in this stage" : ""}'):
            self.assertIn(words, live)
        self.assertIn("adaptiveWords(r.adaptive_last, r.lead, sideTitles(data.sides))", _function(script, "howPart"))
        self.assertIn("matchup_mode: mode", _function(script, "saveMode"))
        # Coordinator jobs (no sides) are rows of their own, linking to their page.
        self.assertIn("if (!run.sides) return jobRow(run);", _function(script, "runningRow"))
        self.assertIn("run.link", _function(script, "jobRow"))
        self.assertIn("r.sides &&", _function(script, "findItem"))
        css = _text("matchups.css")
        # The live range is a range bar whose band is a dashed outline (sim-ui.js rangeBar, components.css).
        self.assertIn(".range-bar.is-live .range-band {", _text("components.css"))
        self.assertIn("live: true", live)
        # The live bar is marked at the planned checks (MU-11), from the whole result's games.
        self.assertIn("bar.set(progress.done, progress.total, progress.checks)", live)
        self.assertIn("AHEAD_LOOKS.filter((n) => n <= max)", _function(script, "runProgress"))



@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckMatchupTests(unittest.TestCase):
    """The deck page's results (DK-13): one row per opponent, best first, the rest folded under "Earlier results",
    and "Not played yet against" (never "No games yet" for an opponent with older results)."""

    def test_one_row_per_opponent(self):
        me = {"id": "casual/a", "version": "target", "title": "A", "current": True}
        def item(key, opp, title, value, current=True, engine=False):
            return {"key": key * 64, "format": "Constructed", "games": 400, "updated": "2026-10-04T10:00:00",
                    "winrate": {"value": value}, "engine": {"kind": "decklab", "current": engine},
                    "sides": [me, {"id": opp, "version": "target", "title": title, "current": current}]}
        m = {"results": [item("1", "casual/b", "B", 0.3, current=False), item("2", "casual/c", "C", 0.7),
                         item("3", "casual/b", "B", 0.6)]}
        library = {"decks": [{"id": d, "title": t, "kind": "casual", "space": "home"} for d, t in
                             (("casual/a", "A"), ("casual/b", "B"), ("casual/c", "C"), ("casual/d", "D"))]}
        s = {"id": "casual/a", "kind": "casual", "title": "A"}
        text, = _run_page(["globalThis.fitWidth = () => {}; globalThis.mayStartRuns = () => true; "
                           f"deckResultParts({json.dumps(m)}, {json.dumps(s)}, 'list', {json.dumps(library)})"])
        self.assertIn("vs C70%Favourite · 400 games", text)
        self.assertIn("vs B60%Favourite · 400 games", text)
        self.assertLess(text.index("vs C"), text.index("vs B60%"))       # best first
        self.assertIn("Earlier results (1)The opponent's list has changed since. vs B30%", text)
        # Each row's figure says whose win rate it is (its role="img" words), as "A won" did before slice 6.
        labels, = _run_page(["globalThis.fitWidth = () => {}; globalThis.mayStartRuns = () => true; "
                             "globalThis.walk = (n) => [n, ...(n.children || []).flatMap(walk)]; "
                             f"[deckResultParts({json.dumps(m)}, {json.dumps(s)}, 'list', {json.dumps(library)})].flat(Infinity)"
                             ".filter(Boolean).flatMap(walk).filter((n) => (n.getAttribute && n.getAttribute('class')) === "
                             "'wr wr-inline').map((n) => n.getAttribute('aria-label')).join('|')"])
        self.assertIn("A's win rate 70 percent", labels)
        self.assertIn("Not played yet against: D.", text)
        self.assertNotIn("No games yet", text)


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ReviewFixTests(unittest.TestCase):
    """The stage-2 review's fixes on the Matchups pages, run (_run_page): unusual results, which result
    stands for a pair, sorting, short names, the deck page's links and lines, and the play sheet's gate."""

    STUB = ("globalThis.mayStartRuns = () => true; globalThis.fitWidth = () => {}; "
            "globalThis.walk = (n) => [n, ...(n.children || []).flatMap(walk)]; ")

    @staticmethod
    def side(i, t, v="target", cur=True):
        return {"id": i, "version": v, "title": t, "current": cur}

    def result(self, key, a, b, value, *, engine=True, updated="2026-10-05T10:00:00", **more):
        return dict({"key": key * 64, "format": "Constructed", "sides": [a, b], "winrate": {"value": value},
                     "games": 400, "engine": {"kind": "decklab", "current": engine}, "updated": updated}, **more)

    def test_opponent_views_take_a_result_with_no_win_rate_and_prefer_planned_lists(self):
        a, b, c = (self.side("casual/a", "A"), self.side("casual/b", "B"), self.side("casual/c", "C"))
        decks = [{"id": d["id"], "title": d["title"], "version": "target"} for d in (a, b, c)]
        results = [
            # A newer result of A's play-now list, and an older one of both planned lists: the planned one stands.
            self.result("1", self.side("casual/a", "A", "owned"), b, 0.9),
            self.result("2", a, b, 0.4, engine=False, updated="2026-10-01T10:00:00"),
            # Only a play-now list against C: shown, marked and said so.
            self.result("3", self.side("casual/a", "A", "owned"), c, 0.7),
            # Every game a draw: no win rate, and the opponent views still draw.
            self.result("4", b, c, None)]
        model = f"matchupEntries({json.dumps(a)}, {json.dumps(decks)}, pairsOf({json.dumps(results)}), 'Constructed')"
        entries, labels, unknown = _run_page([
            f"(() => {{ const {{entries}}={model}; return JSON.stringify(entries.map(e=> "
            "[e.side.them.id,e.side.rate.value,e.side.href,e.olderWords])); })()",
            f"(() => {{ {self.STUB} const {{entries}}={model}; return walk(matchupOpponentLinks(entries))"
            ".filter(n=>n.tag==='a').map(n=>n.getAttribute('aria-label')).join('|'); })()",
            f"(() => {{ {self.STUB} const {{entries}}=matchupEntries({json.dumps(b)}, {json.dumps(decks)}, "
            f"pairsOf({json.dumps(results)}), 'Constructed'); const list=matchupOpponentLinks(entries); "
            "return JSON.stringify([matchupOpponentTable(entries).textContent,walk(list).filter(n=>n.tag==='a')"
            ".map(n=>n.getAttribute('aria-label'))]); })()"])
        entries = json.loads(entries)
        self.assertEqual([(row[0], row[1]) for row in entries], [("casual/c", .7), ("casual/b", .4)])
        self.assertIn("play-now", entries[0][3])
        self.assertEqual(entries[1][2], f"#/matchup?key={'2' * 64}")
        self.assertIn("play-now", labels)
        unknown_words, unknown_labels = json.loads(unknown)
        self.assertIn("?", unknown_words)
        self.assertRegex(unknown_labels[-1].lower(), r"not known|no winner")

    def test_meaningless_results_sort_last_and_say_why(self):
        a, b, c = (self.side("commander/a", "A"), self.side("commander/b", "B"), self.side("commander/c", "C"))
        decks = [{"id": d["id"], "title": d["title"], "version": "target"} for d in (a, b, c)]
        results = [dict(self.result("1", a, b, 0.89, not_meaningful=True), format="Commander"),
                   dict(self.result("2", a, c, 0.6), format="Commander")]
        pairs = f"pairsOf({json.dumps(results)})"
        listed, table, links = _run_page([
            f"(() => {{ {self.STUB} return deckMatchupList({json.dumps(decks[0])}, {json.dumps(decks)}, {pairs}, "
            "'Commander'); })()",
            f"(() => {{ const {{entries}}=matchupEntries({json.dumps(decks[0])}, {json.dumps(decks)}, {pairs}, "
            "'Commander'); return matchupOpponentTable(entries); })()",
            f"(() => {{ {self.STUB} const {{entries}}=matchupEntries({json.dumps(decks[0])}, {json.dumps(decks)}, {pairs}, "
            "'Commander'); return JSON.stringify(walk(matchupOpponentLinks(entries)).filter(n=>n.tag==='a')"
            ".map(n=>n.getAttribute('aria-label'))); })()"])
        self.assertLess(listed.index("vs C"), listed.index("vs B"))          # the real 60% before the 89% that means nothing
        self.assertLess(table.index("C"), table.index("B"))
        self.assertIn("Not meaningful", table)
        self.assertIn("not meaningful", json.loads(links)[-1].lower())
        self.assertNotIn("Earlier engine", listed)

    def test_short_names_stay_apart(self):
        decks = [{"id": "commander/a", "title": "Giada, Font of Hope: Calling All Angels"},
                 {"id": "product/b", "title": "Giada, Font of Hope: Calling All Angels (upgraded)"},
                 {"id": "casual/c", "title": "Gruul Ramp (Bloomburrow Starter Kit)"}]
        names, = _run_page([f"JSON.stringify([...shortNames({json.dumps(decks)}).values()])"])
        self.assertEqual(json.loads(names), ["Giada, Font of Hope: Calling All Angels",
                                             "Giada, Font of Hope: Calling All Angels (upgraded)", "Gruul Ramp"])

    def test_the_deck_pages_not_played_links_open_the_list_shown(self):
        m = {"results": []}
        library = {"decks": [{"id": d, "title": t, "kind": "casual", "space": "home"} for d, t in
                             (("casual/a", "A"), ("casual/b", "B"))]}
        s = {"id": "casual/a", "kind": "casual", "title": "A"}
        href, = _run_page([f"(() => {{ {self.STUB} const parts = deckResultParts({json.dumps(m)}, {json.dumps(s)}, "
                           f"'play-now list', {json.dumps(library)}, 'owned'); "
                           "return walk(parts[1]).find((n) => n.tag === 'a').getAttribute('href'); })()"])
        self.assertEqual(href, "#/matchup?a=casual%2Fa&av=owned&b=casual%2Fb&bv=target")

    def test_the_deck_page_says_once_what_an_earlier_engine_played(self):
        ai = {"cannot_play": [], "commander_unplayable": False, "team_pump": None, "pilot": None, "unknown": [],
              "problem": None, "games": 0, "other_engine_games": 34800, "other_engine_commander_unplayable": True}
        m = {"ai": ai, "cards": {"games": 0, "of": 0, "old": 0, "bad": 0, "other_engine_games": 34800}, "results": []}
        line, parts, stats = _run_page([
            f"earlierEngineLine({json.dumps(m)})",
            f"aiLimitsParts({json.dumps(ai)}, 'Gisa', {{ deckPage: true, otherSaid: true, "
            f"earlier: earlierFlags({json.dumps(m)}) }}).map((n) => n.textContent).join('|')",
            f"String(deckCardStats({json.dumps(m)}, 'list', {{ otherSaid: true }}))"])
        self.assertEqual(line, "This list's 34,800 games were all played with an earlier version of Forge's engine, "
                               "so the checks below wait for games with today's.")
        self.assertIn("Earlier games: commander never cast", parts)
        self.assertNotIn("Nothing held back", parts)                         # never an all-clear under that
        self.assertNotIn("34,800", parts)                                    # said once, in the line above
        self.assertEqual(stats, "null")

    def test_the_play_sheet_keeps_the_gate_and_the_format(self):
        script = _scripts(MATCHUP_SCRIPTS)
        sheet = _function(script, "openPlaySheet")
        refresh = sheet[sheet.index("function refresh()"):sheet.index("async function submit")]
        # A deck or run choice changed after syncRunControls disabled Start must not enable it again.
        self.assertIn("start.disabled = (data.forge || {}).ready === false || (!running && !runsAllowed());", refresh)
        # Opened from the Commander opponent view, it starts with a Commander deck; and the times are the lists' own.
        self.assertIn("playableDecks(library).find((d) => deckFormat(d) === format)", sheet)
        self.assertIn('games.setEstimates(answer.estimates || null, answer.format === "Commander")', sheet)
        self.assertIn("openPlaySheet(library, () => data, token, {}, view.format)", _function(script, "drawMatchups"))

    def test_the_run_choice_retimes_for_commander(self):
        data = {"choices": [200, 400, 800], "default_games": 400, "format": "Constructed", "workers": 16}
        before, after, served = _run_page([
            f"(() => {{ state.matchupMode = 'assess'; globalThis.c = runModeChoice({json.dumps(data)}); "
            "return c.node.textContent; })()",
            "(c.setCommander(true), c.node.textContent)",
            "(c.setEstimates({assess: [30, 45], fixed: {}}, true), c.node.textContent)"])
        self.assertNotEqual(before, after)                                   # Commander games take longer
        self.assertIn("About 30-45 minutes.", served)

    def test_a_start_in_flight_holds_the_pages_redraw(self):
        detail = _function(_scripts(MATCHUP_SCRIPTS), "redrawMatchup")
        self.assertIn("if (page.starting) { page.redrawLater = true; return; }", detail)
        play = _function(_scripts(MATCHUP_SCRIPTS), "play")
        self.assertIn("if (page.starting) return;", play)
        self.assertIn('$("#main [data-play-error]")', play)
        self.assertIn('if (typeof syncRunsPill === "function") syncRunsPill(true);', play)


@unittest.skipUnless(NODE, "Node.js isn't installed")
class RunsPillTests(unittest.TestCase):
    """The top bar's run activity (runs-pill.js; E11-S30 slice 6): one icon button while anything plays or waits,
    named for what it shows, nothing while nothing does; its details' words; and that it asks only the cheap
    ?running=1 answer, never while the page is hidden."""

    NAMES = ("core.js", *MATCHUP_SCRIPTS, "runs-pill.js")
    SETUP = ("Object.defineProperty(Node.prototype, 'style', { get() { return this._s || (this._s = {}); }, "
             "configurable: true }); globalThis.host = el('div'); document.getElementById = (id) => id === 'shell-status' ? host : null; "
             "state.profile = {id: 'matt', name: 'Matt'}; ''")

    RUN = {"key": "k", "status": "running", "link": "#/matchup?key=k", "done": 240, "total": 700, "mode": "assess",
           "eta_s": 370, "may_stop": True,
           "sides": [{"id": "casual/a", "version": "target", "title": "Gruul Ramp"},
                     {"id": "casual/b", "version": "owned", "title": "Izzet Otters"}],
           "plan": {"mode": "assess", "stage": 2, "planned": 1100, "games_before": 400, "max": 3200}}
    FIELD = {"key": "f", "status": "queued", "title": "Field run of Gruul Ramp", "done": 0, "total": 2000,
             "link": "#/deck", "sides": None, "ahead": 0, "may_stop": False}

    def test_the_activity_icon(self):
        # One 44 px button, never a pill of words over the bar (visual-design.md section 6 decision 3): its name
        # says what's going on and that it shows the progress; nothing at all while nothing plays or waits.
        label = ("(() => { const b = host.children[0]; return b ? [b.tag, b.getAttribute('class'), b.getAttribute('aria-label'), "
                 "b.getAttribute('aria-expanded'), b.textContent === ''].join(' | ') : 'none'; })()")
        one, two, waiting, idle, hidden = _run_page([
            self.SETUP,
            f"(noteRuns({json.dumps([self.RUN])}), {label})",
            f"(noteRuns({json.dumps([self.RUN, self.FIELD])}), {label})",
            f"(noteRuns({json.dumps([self.FIELD])}), {label})",
            f"(noteRuns([]), {label} + ' ' + host.hidden)",
            "(() => { const asked = []; globalThis.api = (url) => { asked.push(url); return new Promise(() => {}); }; "
            "document.visibilityState = 'hidden'; askRunsPill(); document.visibilityState = 'visible'; askRunsPill(); "
            "return asked.join(','); })()"], self.NAMES)[1:]
        self.assertEqual(one, "button | run-activity | Forge is playing: show progress | false | true")
        self.assertEqual(two, one)
        self.assertEqual(waiting, "button | run-activity is-waiting | A Forge run is waiting: show progress | false | true")
        self.assertEqual(idle, "none true")
        self.assertEqual(hidden, "/api/matchups?running=1")

    def test_the_details(self):
        # Each run playing (its status line, "game N of M" and about how long is left, a progress ring, its page and
        # Stop when the server lets this viewer stop it), the runs waiting, and the way to Matchups.
        walk = "globalThis.walk = (n) => [n, ...(n.children || []).flatMap(walk)]; "
        parts = f"runDetailsParts({json.dumps([self.RUN, self.FIELD])})"
        text, ring, stops, links = _run_page([
            self.SETUP, parts,
            f"(() => {{ {walk} const r = [{parts}].flat(Infinity).filter(Boolean).flatMap(walk).find((n) => n.getAttribute && "
            "n.getAttribute('role') === 'progressbar'); return [r.getAttribute('aria-valuenow'), r.getAttribute('aria-label')].join(' | '); })()",
            f"(() => {{ {walk} return [{parts}].flat(Infinity).filter(Boolean).flatMap(walk).filter((n) => n.tag === 'button')"
            ".map((n) => n.getAttribute('aria-label')).join(' | '); })()",
            f"(() => {{ {walk} return [{parts}].flat(Infinity).filter(Boolean).flatMap(walk).filter((n) => n.tag === 'a')"
            ".map((n) => n.getAttribute('href')).join(' '); })()"], self.NAMES)[1:]
        self.assertIn("Forge playing: Gruul Ramp vs Izzet Otters (play-now)game 640 of ~1,100 · about 6 min left", text)
        self.assertIn("WaitingField run of Gruul Rampnext", text)
        self.assertIn("Every run on Matchups", text)
        self.assertEqual(ring, "58 | Games played: 640 of ~1,100")
        self.assertEqual(stops, "Stop the Forge run: Gruul Ramp vs Izzet Otters (play-now)")
        self.assertEqual(links, "#/matchup?key=k #/matchups")
        # Alone, its Stop is just "Stop the Forge run"; before a tenth of it has played there's no time left yet.
        alone, early = _run_page([
            self.SETUP,
            f"(() => {{ {walk} return [runDetailsParts({json.dumps([self.RUN])})].flat(Infinity).filter(Boolean).flatMap(walk)"
            ".filter((n) => n.tag === 'button').map((n) => n.getAttribute('aria-label')).join(); })()",
            f"runDetailsParts({json.dumps([dict(self.RUN, done=10, plan=None, total=700)])})"], self.NAMES)[1:]
        self.assertEqual(alone, "Stop the Forge run")
        self.assertIn("game 10 of 700Open it", early)
        self.assertEqual([runLeft for runLeft in _run_page(
            ["runLeftWords(20)", "runLeftWords(370)", "runLeftWords(4800)", "runLeftWords(7200)"], self.NAMES)],
            ["under a minute", "6 min", "1 h 20 min", "2 h"])


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PageScriptTests(unittest.TestCase):
    """The page's per-card words, run (_run_page): what a reader sees, not only what the source says."""

    SENTENCE = re.compile(r"Won (\d+\.\d)% when drawn, (\d+\.\d)% when not: ([+−]?)(\d+\.\d) points "
                          r"\((.+) to (.+)\)\. (Won more when drawn|Won less when drawn|No clear difference)\.")

    @staticmethod
    def split_call(yes, no, diff, verdict="unclear", land=False, judged=True, games=400, drawn=200):
        """winSplitWords for a card drawn in drawn of games, with these win rates, difference and range."""
        row = {"land": land, "judged": judged, "verdict": verdict, "diff": diff}
        stats = {"games": games, "min_split": 30}
        yes_rate = None if yes is None else {"value": yes, "games": drawn}
        no_rate = None if no is None else {"value": no, "games": games - drawn}
        return f"winSplitWords({json.dumps(row)}, {json.dumps(stats)}, 'drawn', {json.dumps(yes_rate)}, " \
               f"{json.dumps(no_rate)}, {drawn})"

    def test_the_difference_is_the_difference_of_the_rates_shown(self):
        # Rates shown to whole percents beside an unrounded difference contradicted each other ("Won 44%
        # when drawn, 44% when not: −1 point"). Both rates now have one decimal and the difference is theirs;
        # the range is still the server's.
        diff = {"value": -0.0063, "low": -0.08, "high": 0.06}
        self.assertEqual(_run_page([self.split_call(0.4449, 0.4512, diff)]),
                         ["Won 44.5% when drawn, 45.1% when not: −0.6 points (−8 to +6). No clear difference."])
        rng = random.Random(8)
        cases = [(0.4449, 0.4512), (0.5444, 0.5716), (0.4445, 0.4515), (0.45, 0.45), (1.0, 0.0), (0.0, 0.9996)]
        cases += [(round(rng.random(), 4), round(rng.random(), 4)) for _ in range(300)]
        calls = [self.split_call(yes, no, {"value": round(yes - no, 4), "low": -0.2, "high": 0.2})
                 for yes, no in cases]
        for (yes, no), words in zip(cases, _run_page(calls), strict=True):
            with self.subTest(yes=yes, no=no):
                found = self.SENTENCE.fullmatch(words)
                self.assertIsNotNone(found, words)
                shown_yes, shown_no, sign, size = found.group(1), found.group(2), found.group(3), found.group(4)
                tenths = round(float(shown_yes) * 10) - round(float(shown_no) * 10)
                self.assertEqual((-1 if sign == "−" else 1) * round(float(size) * 10), tenths, words)
                self.assertEqual(sign, "+" if tenths > 0 else "−" if tenths < 0 else "", words)
                # Each rate is the server's to within half a tenth of a point.
                self.assertLessEqual(abs(float(shown_yes) - 100 * yes), 0.05 + 1e-9, words)
                self.assertLessEqual(abs(float(shown_no) - 100 * no), 0.05 + 1e-9, words)
                self.assertEqual(found.group(5, 6), ("−20", "+20"))
        # A verdict still comes in words, from the server's verdict.
        more = self.split_call(0.6109, 0.1778, {"value": 0.4331, "low": 0.3, "high": 0.52}, verdict="more")
        self.assertTrue(_run_page([more])[0].endswith("+43.3 points (+30 to +52). Won more when drawn."))

    def test_a_land_gets_its_win_rates_and_no_verdict(self):
        # Games without a copy of a land were mostly short of lands, or of its colour: a land's row gives its
        # two win rates and says it gets no verdict, not "Not enough games to tell" or a difference in points
        # (even from a server that judged it).
        diff = {"value": 0.4331, "low": 0.3, "high": 0.52}
        plains = self.split_call(0.6109, 0.1778, diff, verdict=None, land=True, judged=False, games=1600, drawn=1555)
        judged = self.split_call(0.6109, 0.1778, diff, verdict="more", land=True, games=1600, drawn=1555)
        every = self.split_call(0.6, None, None, verdict=None, land=True, judged=False, games=100, drawn=100)
        few = self.split_call(0.6, 0.5, diff, verdict=None, land=True, judged=False, games=40, drawn=30)
        one = self.split_call(0.6, 0.0, diff, verdict=None, land=True, judged=False, games=101, drawn=100)
        self.assertEqual(_run_page([plains, judged, every, few, one]), [
            "Won 61.1% of the 1,555 games it was drawn in, 17.8% of the 45 games without a copy. No verdict for "
            "a land.",
            "Won 61.1% of the 1,555 games it was drawn in, 17.8% of the 45 games without a copy. No verdict for "
            "a land.",
            "Drawn in every one of the 100 games, which the deck won 60.0% of. No verdict for a land.",
            "Won 60.0% of the 30 games it was drawn in, 50.0% of the 10 games without a copy. No verdict for a land.",
            "Won 60.0% of the 100 games it was drawn in, 0.0% of the 1 game without a copy. No verdict for a land."])
        # The key says once why; a spell's row is as before.
        key = _run_page(["cardStatsKey(false)"])[0]
        self.assertEqual(key.count("No win-rate verdict"), 1)
        self.assertIn("games short of lands, or of its colour", key)
        spell = self.split_call(0.6, 0.5, None, verdict=None, judged=False, games=40, drawn=30)
        self.assertTrue(_run_page([spell])[0].startswith("Not enough games to tell a win-rate difference yet"))

    def test_games_an_earlier_card_log_kept_are_said_to_be_so(self):
        # Batches whose card record is an earlier version's (cardstats' "old": version 1 counted a cast Forge's
        # AI couldn't finish as a cast) were played with the card log (their runs say "Card log on."), so the
        # page never says they were played without it: it says an earlier card log kept them, apart from the
        # games really played without one.
        def stats(games=0, bad=0, old=0, of=0, matchups=0, **more):
            return json.dumps(dict({"games": games, "bad": bad, "old": old, "of": of, "matchups": matchups,
                                    "enough": games >= 100, "min_games": 100, "min_split": 30, "rows": [],
                                    "commander": []}, **more))

        earlier = "logged by an earlier version of the card log, which counted casts differently"
        only, deck, one, also_bad, mixed, single, before = _run_page([
            f"cardStatsCoverage({stats(old=400, of=400)})",
            f"cardStatsCoverage({stats(old=400, of=400)}, true)",
            f"cardStatsCoverage({stats(old=1, of=1)})",
            f"cardStatsCoverage({stats(bad=2, old=400, of=502)})",
            f"cardStatsCoverage({stats(games=200, bad=2, old=400, of=802, matchups=2)}, true)",
            f"cardStatsCoverage({stats(games=200, old=1, of=201)})",
            # An older server's stats have no "old": as before.
            "cardStatsCoverage({games: 100, bad: 0, of: 300, enough: true})",
        ])
        self.assertEqual(only, f"No per-card numbers yet.The 400 games were {earlier}. Play more games to get some.")
        self.assertEqual(deck, f"No per-card numbers yet.This list's 400 games were {earlier}. Play more games to "
                               "get some.")
        self.assertEqual(one, f"No per-card numbers yet.The 1 game was {earlier}. Play more games to get some.")
        self.assertEqual(also_bad, f"No per-card numbers yet.400 of the 502 games were {earlier}, and the card log was "
                                   "kept for 2 more games, but each game's log failed its checks (which make sure "
                                   "every card move adds up). Play more games to get some.")
        self.assertEqual(mixed, "From 200 of this list's 802 games, across 2 matchups: 200 were played without "
                                f"the card log (before Deck Lab kept one, or while it was off); 400 were {earlier}, "
                                "so they're left out; 2 games' card logs failed their checks (which make sure "
                                "every card move adds up), so they're left out.")
        self.assertEqual(single, f"From 200 of the 201 games: 1 was {earlier}, so it's left out.")
        self.assertEqual(before, "From 100 of the 300 games: 200 were played without the card log (before Deck Lab "
                                 "kept one, or while it was off).")
        for words in (only, deck, one, also_bad, single):
            self.assertNotIn("without the card log", words)
        # The deck page: stats with only older games explain them (not "None of this list's saved games was
        # played with the card log", which is for no card record at all); the matchup page's casts table does
        # too. A matchup with no casts shows the per-card part with the same line.
        result = {"games": 400, "cards": [json.loads(stats(old=400, of=400))] * 2,
                  "casts": [[{"name": "Shock", "qty": 4, "casts": 300, "games": 250}], []]}
        sides = [{"title": "Red"}, {"title": "Green"}]
        no_casts = dict(result, casts=[[], []])
        current = {"results": [{"sides": [{"current": True}]}]}
        # deck.js's cardLink (the card names open the viewer), which these Node runs don't load.
        stub = "globalThis.cardLink = (entry) => el('span', {}, entry.name); "
        page, none, casts, alone = _run_page([
            f"deckCardStats({json.dumps(dict(current, cards=json.loads(stats(old=400, of=400))))}, 'list')",
            f"deckCardStats({json.dumps(dict(current, cards=None))}, 'list')",
            f"{stub}castsPart({json.dumps(result)}, {json.dumps(sides)})",
            f"castsPart({json.dumps(no_casts)}, {json.dumps(sides)})",
        ])
        self.assertEqual(page, f"How its cards playedNo per-card numbers yet.This list's 400 games were {earlier}. "
                               "Play more games to get some.")
        self.assertIn("None of this list's saved games was played with the card log", none)
        self.assertIn("What each deck cast", casts)
        self.assertIn(f"The 400 games were {earlier}", casts)
        self.assertIn("Shock", casts)
        self.assertEqual(alone, f"How each deck's cards playedNo per-card numbers yet.The 400 games were {earlier}. "
                                "Play more games to get some.")

    def test_the_deck_pages_lead_never_lists_a_land(self):
        # "Clear win-rate differences" lists judged rows, and a land never is: Plains "+43 points" read as
        # "add more Plains". Even a land a server judged is left out.
        def row(name, land, verdict, value):
            return {"name": name, "qty": 4, "land": land, "drawn_games": 300, "copies_drawn": 400, "cast": 300,
                    "other_casts": 0, "stuck": 10, "stuck_share": 0.025, "judged": verdict is not None,
                    "verdict": verdict, "wr_drawn": {"value": 0.5 + value / 2}, "wr_not": {"value": 0.5 - value / 2},
                    "diff": {"value": value, "low": value - 0.1, "high": value + 0.1}}
        both = {"games": 400, "min_split": 30, "commander": [],
                "rows": [row("Shock", False, "more", 0.15), row("Plains", True, "more", 0.43),
                         row("Forest", True, None, 0.26)]}
        lands_only = dict(both, rows=both["rows"][1:])
        stub = "globalThis.cardLink = (entry) => el('span', {}, entry.name); "
        lead, alone = _run_page([f"{stub}standOutParts({json.dumps(both)})",
                                 f"standOutParts({json.dumps(lands_only)})"])
        self.assertIn("Clear win-rate differences", lead)
        self.assertIn("Shock+15.0 points (+5 to +25)", lead)       # as its row in the table says it
        self.assertNotIn("Plains+", lead)
        self.assertNotIn("Forest+", lead)
        self.assertNotIn("Clear win-rate differences", alone)
        self.assertIn("Win-rate differences: too few games to tell yet", alone)

    def test_the_field_part_reads_the_answer(self):
        # field.js draws GET /api/field's answer (section 10.6's words): the headline, the rating, the chips, the
        # rows, and the play box, or the live box while a field run plays.
        opponent = {"id": "casual/izzet", "version": "target", "title": "Izzet", "kind": "casual", "card_sha": "b" * 64,
                    "key": "c" * 64, "games": 400, "rate": {"value": 0.62, "low": 0.55, "high": 0.68},
                    "lead": {"verdict": "ahead", "side": 0, "basis": "decided"}, "pred": 0.55,
                    "residual": {"r": 0.12, "z": 3.1, "p": 0.002, "flag": "strong"}, "not_meaningful": False,
                    "problem": None}
        answer = {"deck": {"id": "casual/gruul", "version": "target", "title": "Gruul", "card_sha": "a" * 64},
                  "format": "Constructed", "opponents": [opponent, dict(opponent, id="casual/elves", title="Elves",
                                                                        rate=None, games=0, lead=None, pred=None,
                                                                        residual=None)],
                  "average": {"value": 0.54, "low": 0.51, "high": 0.57, "counted": 6, "of": 9, "partial": True},
                  "rating": {"value": 0.55, "low": 0.5, "high": 0.6, "rank": 3, "rank_low": 2, "rank_high": 5,
                             "of": 10, "h_points": 3.2, "connected": 11, "dispersion": 4.0},
                  "coverage": {"with_floor": 6, "of": 9}, "last_run": None, "notes": [], "status": "done",
                  "job": None, "notice": None, "error": None,
                  "budgets": {"standard": {"games": 400, "new_games": 1200, "minutes": [25, 40]}},
                  "default_budget": "standard", "field_lists": [], "forge": {"ready": True}}
        playing = dict(answer, status="running", job={"done": 140, "total": 600, "by": "User1", "pairs": {
            "c" * 64: {"opponent": {"id": "casual/izzet", "version": "target", "title": "Izzet"}, "done": 140,
                       "total": 200, "wins": 77, "other": 3, "playing": True},
            "d" * 64: {"opponent": {"id": "casual/elves", "version": "target", "title": "Elves"}, "done": 0,
                       "total": 200, "wins": 0, "other": 0, "playing": False}}})
        draw = ('(() => {{ const ctx = {{ section: el("section"), content: el("div"), token: routeToken, '
                'id: "casual/gruul", version: "target", url: "", answer: null, budget: null, timer: 0, '
                'busy: false }}; fvDraw(ctx, {answer}); clearTimeout(ctx.timer); return ctx.content; }})()')
        style = 'Object.defineProperty(Node.prototype, "style", { get() { return this._s || (this._s = {}); } }), ""'
        _, done, live = _run_page([style, draw.format(answer=json.dumps(answer)),
                                   draw.format(answer=json.dumps(playing))],
                                  ("core.js", *MATCHUP_SCRIPTS, "field.js"))
        # The average as a hero figure (sim-ui.js), its range and the games under it; no field run note, no badge.
        self.assertIn("Against an average house deck:54%51–57% 95% range400 games", done)
        self.assertIn("Based on 6 of 9 decks; play the field to fill it in.", done)
        self.assertIn("Ranks 3rd of 10 Constructed decks (somewhere from 2nd to 5th).", done)
        self.assertIn("Going first is worth about 3 points of win rate in these games.", done)    # in "How this is worked out"
        self.assertIn("Strong against Izzet62% Does better than expected: 12 points more than its rank suggests", done)
        self.assertIn("Izzet62%55–68Ahead · 400 gamesstrong against", done)
        self.assertNotIn("No games yet", done)                       # MU-08: never a row of "No games yet"
        self.assertIn("Not played yet against: Elves.", done)
        self.assertIn("Play the field", done)
        self.assertIn("Quick lookSettle itPrecise", done)
        # The field's Settle it means what a matchup's does: until most matchups are clear.
        self.assertIn("Plays each deck until most matchups are clear: which deck is ahead, or that they're about even. "
                      "About 400 games a deck, about 25–40 minutes.", done)
        self.assertIn("only to about ±8 points of win rate", done)
        self.assertIn("140 of 600 games · Playing: Izzet (1 waiting)", live)
        self.assertIn("Started by User1", live)
        self.assertNotIn("Play the field", live)
        # No games at all: one empty state with Play (MU-08).
        empty = dict(answer, opponents=[dict(o, games=0, rate=None, lead=None, residual=None) for o in answer["opponents"]],
                     average=None, rating=None)
        none, = _run_page([style, draw.format(answer=json.dumps(empty))][1:], ("core.js", *MATCHUP_SCRIPTS, "field.js"))
        self.assertTrue(none.startswith("No games against the field yet.Play the field to see how this list does "
                                        "against the 2 other Constructed decks of the house."), none)
        self.assertEqual(none.count("Against each deck"), 0)



if __name__ == "__main__":
    unittest.main()
