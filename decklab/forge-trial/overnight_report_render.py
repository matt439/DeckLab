"""Markdown rendering for the combined-run report, from its collected evidence.

Data collection and report writing stay in overnight_report.py. Optional pods rendering is read
through the gates module's existing loader; no renderer imports the report facade.
"""
import json
import time

from overnight_report_gates import _pods


def _pilot_markdown(pil, sens):
    lines = []
    if pil and pil.get("arms"):
        lines += ["", "## Pilot experiments (D2d-p2)", "",
                  "Recommendations follow CONTRACT-W3.md section 12.4 (the mirror test clear of 50 %, no reference "
                  "pair clearly negative, speed at least 1/1.5 of the control's, the hybrid AI's 1/3). Adoption is "
                  "the owner's, and needs a targeted replay of the matchups the deck plays.", "",
                  "| Experiment | Arm | Recommendation | Mirror (arm side) | Reference pairs (paired Δ) | Slowdown | Why |",
                  "|---|---|---|---|---|---|---|"]
        for r in pil["arms"]:
            mirror = "; ".join(f"{_pct(m.get('value'))} ({_pct(m.get('low'))}-{_pct(m.get('high'))}, "
                               f"{m.get('games')} games)" for m in r["mirror"]) or "-"
            refs = "; ".join(f"{' v '.join(x['pair'])}: {_pts(x.get('delta'))} ({_pts(x.get('low'))} to "
                             f"{_pts(x.get('high'))})" + (" clearly negative" if x.get("clearly_negative") else "")
                             for x in r["references"]) or "-"
            slow = f"{r['slowdown']:.2f}x" if r.get("slowdown") is not None else "-"
            rec = {"adopt": "adopt", "dont_adopt": "don't adopt", "more_games": "more games"}.get(
                r["recommendation"], "evidence only")
            if r["recommendation"] == "more_games" and r.get("games_per_pair"):
                rec += f" (about {r['games_per_pair']:,} a pair)"
            lines.append(f"| {r['experiment']} | {r['arm']} | {rec} | {mirror} | {refs} | {slow} | "
                         f"{' '.join(r['why'])} |")
        adopt = [f"{r['arm']} ({r['experiment']})" for r in pil["arms"] if r["recommendation"] == "adopt"]
        lines += ["", "Adoption candidates: " + (", ".join(adopt) if adopt else "none.")]
        h = pil.get("hybrid")
        if isinstance(h, dict):
            lines += ["", f"The hybrid AI: slowdown {h.get('slowdown') if h.get('slowdown') is None else round(h['slowdown'], 2)}"
                          f" (its mirror plays at {h.get('limit')} or less); the mirror: {h.get('mirror')}."
                      + (f" Failed: {'; '.join(h['failed'])}." if h.get("failed") else "")]
    if sens:
        lines += ["", "## Pilot sensitivity (D2e)", "",
                  f"Pairings: {sens['pairings']}. Spearman of the ratings, (a) Default against (b) every experiment "
                  f"override set: {'-' if sens['spearman'] is None else f'{sens['spearman']:.3f}'}"
                  + ("" if sens["rankings_hold"] is None else
                     (" (rankings hold)" if sens["rankings_hold"] else
                      " (under 0.9: show bands, plan G3)")) + "."]
        for arm, flips in sens["flips"].items():
            lines.append(f"Flips under ({arm}) (BH-10 % discoveries): "
                         + ("; ".join(f"{' v '.join(f['pair'])} {_pts(f.get('delta'))}" for f in flips) or "none") + ".")
        if sens["flips"].get("b") or sens["rankings_hold"] is False:
            lines.append("With flips or a Spearman under 0.9, the report recommends showing bands (plan G3).")
        if sens["spread"]:
            cols = [c for c in ("a", "b", "c") if c in sens["ratings"]]
            lines += ["", "| Deck | " + " | ".join(f"Rating ({c})" for c in cols) + " | Spread |",
                      "|---|" + "---|" * (len(cols) + 1)]
            for deck, spread in sens["spread"].items():
                vals = " | ".join(f"{sens['ratings'][c][deck]:+.2f}" if deck in sens["ratings"][c] else "-"
                                  for c in cols)
                lines.append(f"| {deck} | {vals} | {'-' if spread is None else f'{spread:.2f}'} |")
    return lines


def _pct(x):
    return "-" if x is None else f"{100 * x:.1f} %"


def _pts(x):
    return "-" if x is None else f"{100 * x:+.1f} pts"


def _markdown(found):
    lines = [f"# Combined run report" + (" (smoke)" if found.get("smoke") else ""), "",
             f"**Verdict: {found['verdict']}**" + (f" ({found['why']})" if found["why"] else ""), ""]
    if found["not_built"]:
        lines += ["Not built tonight (their items were skipped and their time given to the soak filler): "
                  + ", ".join(found["not_built"]) + ". The gates that needed them are marked "
                  "\"not built tonight\" (INCOMPLETE), never FAIL.", ""]
    lines += ["## Merge gates", "", "| Gate | | Status | Detail |", "|---|---|---|---|"]
    for name, g in found["gates"].items():
        lines.append(f"| {name} | {g['title']} | {g['status']} | {g['detail'] or ''} |")
    lines += ["", "## What ran", "", "| Item | Status | Note |", "|---|---|---|"]
    for k, v in found["items"].items():
        lines.append(f"| {k} | {v.get('status')} | {v.get('note') or ''} |")
    for n, s in enumerate(found.get("sessions") or [], 1):
        lines.append("")
        lines.append(f"Session {n}: active {s.get('active_s', 0) / 60:.0f} min, paused {s.get('paused_s', 0) / 60:.0f} "
                     f"min, soak {s.get('soak_s', 0) / 60:.0f} min ({s.get('soak_server_s', 0) / 60:.0f} on the "
                     f"server's pool), restarts {s.get('restarts', 0)}, exit {s.get('exit')}"
                     + (f", deadline {time.strftime('%Y-%m-%d %H:%M', time.localtime(s['deadline_epoch']))}"
                        if s.get("deadline_epoch") else "")
                     + (", the controller gave up and the end ran on its own" if s.get("gave_up") else "") + ".")
    if found.get("sleep_gaps"):
        lines += ["", f"Sleep or suspension gaps in the monitor (over 5 s): {len(found['sleep_gaps'])}, the longest "
                      f"{max(g[1] for g in found['sleep_gaps'])} s."]
    if found.get("timing"):
        lines += ["", "## Timing (B legs)", "", "Against B2's warm rate (the mean of its rounds 1-2) for the same "
                  "workload.", "", "| Leg | Round | Workload | Games | Games a minute | x B2 warm | Median ms | "
                  "AI timeouts | Clock stops | Recycled |", "|---|---|---|---|---|---|---|---|---|---|"]
        for t in found["timing"]:
            lines.append(f"| {t['leg']} | {t['round']} | {t['workload']} | {t['games']} | {t['games_per_min']} | "
                         f"{_cell(t.get('vs_b2_warm'))} | {t['median_ms']} | {_cell(t.get('ai_timeout_games'))} | "
                         f"{_cell(t.get('clock_stops'))} | {_cell(t.get('recycled'))} |")
    if found.get("drill"):
        lines += ["", "## The drill (--smoke)", "", "```", json.dumps(found["drill"], indent=1), "```"]
    if found.get("foreign_java"):
        lines += ["", "Foreign java.exe seen (reported, never killed): "
                  + ", ".join(str(f.get("pid")) for f in found["foreign_java"])]
    for key, title in (("pilots", "Pilot experiments"), ("sensitivity", "Pilot sensitivity")):
        if isinstance(found.get(key), dict) and "error" in found[key]:
            lines += ["", f"{title}: the report couldn't work them out ({found[key]['error']})."]
    try:                             # a bad pilot table never costs REPORT.md
        lines += _pilot_markdown(*(f if isinstance(f, dict) and "error" not in f else None
                                   for f in (found.get("pilots"), found.get("sensitivity"))))
    except Exception as e:
        lines += ["", f"Pilot experiments: the report couldn't show them ({type(e).__name__}: {e}); "
                      "report.json has the numbers."]
    if "m7" in found:
        try:                         # a bad M7 table never costs REPORT.md
            lines += _m7_markdown(found["m7"])
        except Exception as e:
            lines += ["", f"M7: the report couldn't show it ({type(e).__name__}: {e}); report.json has the numbers."]
    try:                             # a bad pods section never costs REPORT.md
        lines += _pods().markdown(found.get("out") or ".")
    except Exception as e:          # an optional section that can't be written is said, never a crash
        lines += ["", f"(The 4-player pods' section couldn't be written: {type(e).__name__}: {e}.)"]
    lines += ["", "## Gate numbers", "", "```", json.dumps({k: v["numbers"] for k, v in found["gates"].items()
                                                              if v["numbers"]}, indent=1), "```"]
    lines += _sections_markdown(found)
    return "\n".join(lines) + "\n"


# ============================================================ M7 (D4b): Forge against published human win rates

# Spearman's rho a two-sided test needs for p < 0.05, by the number of values (exact tables)
SPEARMAN_05 = {5: 1.0, 6: 0.886, 7: 0.786, 8: 0.738, 9: 0.700, 10: 0.648}


def _m7_markdown(m7):
    """The report's M7 section (P3; never a gate)."""
    lines = ["", "## External check (M7, D4b; P3, never a gate)", ""]
    if not m7 or not m7.get("ran"):
        return lines + [f"M7 didn't run: {(m7 or {}).get('why') or 'no result'}."]
    src = m7.get("source") or {}
    names = m7.get("names") or {}

    def num(v, f="{:.2f}"):
        return "n/a" if v is None else f.format(v)

    lines += [f"Forge played {m7['pairs_played']} of {m7['pairs']} pairs of {len(m7['decks'])} Pauper decks "
              f"({m7.get('games_per_pair')} games a pair, game 1 only, no sideboards), against "
              f"[{src.get('name', 'the published matrix')}]({src.get('url', '')}) (fetched {src.get('fetched')}; "
              f"{src.get('window', '')}).", "",
              f"- **Deck strength:** Spearman of the Bradley-Terry ratings, Forge against human: "
              f"**{num(m7['deck_spearman'])}** over {m7['decks_rated']} decks"
              + (f" (with {m7['decks_rated']} decks, |rho| has to reach {SPEARMAN_05[m7['decks_rated']]} for "
                 f"p < 0.05, two-sided)." if m7["decks_rated"] in SPEARMAN_05 else "."),
              f"- **Matchups:** the favourite agrees in {m7['sign_agree']} of {m7['sign_decided']} published "
              f"matchups (sign test p = {num(m7['sign_p'])}); Spearman of the cells (each both ways round): "
              f"{num(m7['cell_spearman'])}.", "",
              "| Deck | Forge BT | Human BT |", "|---|---|---|"]
    for d in sorted(m7["decks"], key=lambda i: -(m7["bt_forge"].get(i) or 0)):
        lines.append(f"| {names.get(d, d)} | {num(m7['bt_forge'].get(d))} | {num(m7['bt_human'].get(d))} |")
    lines += ["", "| Matchup | Human (matches) | Forge | Same favourite |", "|---|---|---|---|"]
    for c in m7["cells"]:
        if c["forge"] is None or c["human"] == 0.5 or c["forge"] == 0.5:
            same = ""
        else:
            same = "yes" if (c["human"] > 0.5) == (c["forge"] > 0.5) else "no"
        lines.append(f"| {names.get(c['a'], c['a'])} vs {names.get(c['b'], c['b'])} | {c['human']:.0%} ({c['n']}) | "
                     f"{num(c['forge'], '{:.0%}')} | {same} |")
    if m7.get("errors"):
        lines += ["", "Pairs not played: " + "; ".join(f"{e['a']} vs {e['b']} ({e.get('error') or e.get('skipped')})"
                                                     for e in m7["errors"])]
    lines += ["", "**Caveat.** The human numbers are best-of-three match results between strong human pilots "
              "(with sideboards in games 2 and 3), from small samples (5-23 matches a cell; the source puts about "
              "+-20 points on even its best cells), in that period's metagame, with each archetype's lists "
              "pooled. Forge plays one fixed list per archetype, game 1 only, with its own AI piloting both "
              "sides, and its AI is known to play combo and reactive (counterspell) decks worse than aggro. With "
              "human samples this small, a low correlation can't separate Forge's pilots from noise in the "
              "human numbers; a high one is evidence that Forge's deck rankings carry over to human play, in "
              "this format at least."]
    return lines


def _cell(x):
    return "" if x is None else str(x)


def _pct_cell(x):
    return "" if x is None else f"{x * 100:.0f} %"


def _section_error(found, name):
    part = found.get(name)
    return isinstance(part, dict) and "error" in part and len(part) == 1


def _sections_markdown(found):
    """Section 8's parts 6-15 (beyond the gates, the items and the timing table)."""
    lines = []
    g = found.get("gates") or {}
    soak = (g.get("MG7") or {}).get("numbers") or {}
    mem = (g.get("MG10") or {}).get("numbers") or {}
    drift = ((g.get("MG11") or {}).get("numbers") or {}).get("medians")
    lines += ["", "## Soak (section 7)", "",
              f"Probes: {_cell(soak.get('probes'))} in the best session over {_cell(soak.get('span_h'))} h; Constructed "
              f"{_cell(soak.get('constructed'))} games ({_cell(soak.get('failed'))} failed, {_cell(soak.get('unsure'))} "
              f"unsure, {_cell(soak.get('excused'))} excused); Commander {_cell(soak.get('commander'))} games (paired "
              f"estimate {_cell(soak.get('commander_est'))}, low end {_cell(soak.get('commander_low'))}).", "",
              f"Drift medians (ms a game): {drift if drift else 'not enough clean probes'}.", "",
              f"Memory in D: smoothed p99 {_cell(mem.get('ws_p99_mb'))} MB, instantaneous peak "
              f"{_cell(mem.get('ws_peak_mb'))} MB; heap growth {mem.get('heap_growth')}; heap-limit recycles "
              f"{mem.get('heap_limit')}."]
    diag = found.get("diagnostics")
    if diag and not _section_error(found, "diagnostics"):
        lines += ["", "## Fail-fast diagnostics (section 6 C)", "",
                  f"Failed gates: {', '.join(diag.get('failed_gates') or []) or 'none recorded'}. Not run: "
                  f"{diag.get('not_run')}.", ""]
        for name, run in (diag.get("runs") or {}).items():
            lines.append(f"- {name}: {run.get('status')}" + (f", exit codes {run.get('codes')}" if run.get("codes")
                                                               else "") + (f" ({run['note']})" if run.get("note")
                                                                           else ""))
        lines.append(f"- C1 at 100: {diag.get('c1_kinds')}; C2 at 400: failed chunks {diag.get('c2_failed_chunks')}, "
                     f"unsure {diag.get('c2_unsure')}")
    rep = found.get("replay") or {}
    if rep and not _section_error(found, "replay"):
        mg8 = rep.get("mg8") or {}
        lines += ["", "## Replay (D1, E1, E2)", "",
                  f"D1 {rep['d1']['status']}. Planned at A3: {rep.get('planned_matchups')} matchups, "
                  f"{_cell(rep.get('planned_games'))} games. Still missing at E1: {rep.get('still_missing')} matchups. "
                  f"Staged v2 results: {_cell(mg8.get('v2_results'))}, {_cell(mg8.get('games'))} games, "
                  f"{_cell(mg8.get('failed_games'))} in failed chunks; failed matchups {rep.get('failed_matchups')}; "
                  f"stale at E2: {rep.get('stale')}."]
        if rep.get("v2_v1"):
            lines += ["", "| Matchup | v1 balanced | v2 balanced |", "|---|---|---|"]
            lines += [f"| {r['key']} | {r['v1']} | {r['v2']} |" for r in rep["v2_v1"]]
    ad = found.get("adaptive") or {}
    if ad.get("rows"):
        lines += ["", "## Adaptive savings (D3c)", "", "| Pair | Mode | Games | Outcome | Decision | Wall s |",
                  "|---|---|---|---|---|---|"]
        lines += [f"| {r['pair']} | {r['mode']} | {_cell(r.get('games'))} | {_cell(r.get('outcome') or r.get('error'))}"
                  f" | {_cell(r.get('decision'))} | {_cell(r.get('wall_s'))} |" for r in ad["rows"]]
    fv = found.get("field") or {}
    if fv and not _section_error(found, "field"):
        lines += ["", "## Field view (D3)", "",
                  f"Reference (D3a-ref) {fv['ref']['status']}; through the page's API (D3a-api) {fv['api']['status']}"
                  + (f", wall {fv['wall_s']} s, {fv.get('games')} games" if fv.get("wall_s") is not None else "")
                  + f"; Commander (D3b) {fv['d3b']['status']}."]
        rating = fv.get("rating") or {}
        if rating:
            lines.append(f"Rating {rating.get('value')} ({rating.get('low')} to {rating.get('high')}), rank "
                         f"{rating.get('rank')} ({rating.get('rank_low')}-{rating.get('rank_high')} of {rating.get('of')}).")
        if fv.get("residual_flags"):
            lines.append("Residual flags: " + ", ".join(str(x) for x in fv["residual_flags"]) + ".")
        cmp_ = fv.get("compare") or {}
        if cmp_.get("rows"):
            lines += ["", f"Adaptive against reference: Spearman {cmp_.get('spearman')}.", "",
                      "| Opponent | Adaptive | Reference | Games | z |", "|---|---|---|---|---|"]
            lines += [f"| {r['opponent']} | {r['adaptive']} | {r['reference']} | {_cell(r.get('games'))} | {r['z']} |"
                      for r in cmp_["rows"]]
    m4 = found.get("m4") or {}
    if m4 and not _section_error(found, "m4"):
        lines += ["", "## M4 pairing (D2a)", "",
                  f"CRN variants {m4['crn']['status']}, Fiery and shared seeds {m4['m4']['status']}, the "
                  f"three-opponent variant test {m4['field']['status']}."]
        rows = [(n, o) for n, run in enumerate(m4.get("crn_runs") or [], 1) for o in run["opponents"]]
        if rows:
            lines += ["", "| Variant | Opponent | Games | Paired delta (range) | Unpaired range | rho | same | "
                      "Saved |", "|---|---|---|---|---|---|---|---|"]
            lines += [f"| {n} | {o['opponent']} | {o['games']} | {o['delta']} ({o['low']} to {o['high']}) | "
                      f"{o['unpaired_low']} to {o['unpaired_high']} | {o['rho']} | {o['same']} | "
                      f"{_pct_cell(o['saved_share'])} |"
                      for n, o in rows]
        for run in m4.get("field_runs") or []:
            lines.append(f"Three-opponent variant test: {run.get('words') or run.get('verdict')} "
                         f"({run.get('looks')} looks).")
        for t in m4.get("m4_tables") or []:
            lines += _experiment_table(t)
    ex = found.get("experiments") or {}
    if ex and not _section_error(found, "experiments"):
        lines += ["", "## Experiments (D2b-D2e)", ""]
        for lad in ex.get("ladders") or []:
            lines.append(f"- Ladders {lad['id']}: {lad['status']}" + (f" ({lad['note']})" if lad.get("note") else ""))
            for n, rung in enumerate(lad.get("rungs") or [], 1):
                for o in rung["opponents"]:
                    lines.append(f"  - rung {n} v {o['opponent']}: paired delta {o['delta']} ({o['low']} to "
                                 f"{o['high']}), {rung.get('words') or rung.get('verdict')}")
        for e in ex.get("experiments") or []:
            lines.append(f"- {e['id']}: {e['status']}" + (f" ({e['note']})" if e.get("note") else ""))
        for e in ex.get("experiments") or []:
            for t in e.get("tables") or []:
                lines += _experiment_table(t)
        lines += ["", "Adoption candidates: " + (", ".join(f"{a['arm']} ({a['experiment']})" for a in ex["adopt"])
                                                 if ex.get("adopt") else "none") + "."]
    off = found.get("offline")
    if off:
        lines += ["", "## Offline checks (E3)", "",
                  f"{_cell(off.get('games'))} staged v2 games; AI-timeout games {_cell(off.get('ai_timeout_games'))} "
                  f"({_cell(off.get('ai_timeouts_per_1000'))} per 1,000); recycles {off.get('recycled')}; card data "
                  f"unchanged since A1: {off.get('card_data_unchanged')}; early numbers: {off.get('early_numbers')}."]
    opt = [o for o in found.get("optional") or [] if isinstance(o, dict) and o.get("status") not in (None,)]
    if opt:
        lines += ["", "## Optional: M6 and M7", ""]
        for o in opt:
            nums = ", ".join(f"{k} {v}" for k, v in list(o["numbers"].items())[:12])
            lines.append(f"- {o['title']} ({o['id']}): {o['status']}" + (f" ({o['note']})" if o.get("note") else "")
                         + (f"; {nums}" if nums else ""))
    clean = found.get("clean")
    lines += ["", "## Cleanup", ""]
    if clean:
        lines.append(f"Leftovers at the end {clean.get('leftovers')}; run-owned java.exe {clean.get('own_java')}; "
                     f"slots held by the run {clean.get('own_slots')}; test servers {clean.get('test_servers') or {}}; "
                     f"forge logs deleted {clean.get('logs_deleted')}.")
    else:
        lines.append("E4 didn't run.")
    lines += ["", "## Next steps", ""] + [f"- {x}" for x in found.get("next_steps") or []]
    return lines


def _experiment_table(t):
    if not t.get("arms"):
        return []
    return ["", f"Experiment {t['experiment']}:", "",
            "| Arm | Kind | Pairs | Matchup (pooled) | Slowdown | AI timeouts | Recommendation |",
            "|---|---|---|---|---|---|---|"] + [
        f"| {a['arm']} | {a['kind']} | {a['pairs']} | {a['matchup']} | {a['slowdown']} | {a['timeouts']} | "
        f"{a['recommendation']} |" for a in t["arms"]]
