"""Round development over visible saved current-engine matchups, separate from experiment arms."""
from . import cardlog, development_data, engine
from .lists import _list_text, _section_cards
from .saved import _stored


def list_development(sections, kind, results=None, results_dir=None, *, keep=None, pilot=None):
    sha = _list_text(_section_cards(sections), kind)[1]
    selected = [result for result in (_stored(results_dir) if results is None else results)
                if result.get("kind") is None and any(side.get("card_sha") == sha for side in result["sides"])
                and (keep is None or keep(result))]
    pooled = development_data.pooled()
    wanted, matchups, earlier = None, 0, 0
    for result in selected:
        counted = False
        for side, info in enumerate(result["sides"]):
            if info.get("card_sha") != sha:
                continue
            if results is None:
                if wanted is None:
                    wanted = engine.side_ids(sha, kind, pilot=pilot, cards=_section_cards(sections))[engine.KIND_DECKLAB]
                if info.get("engine_id") != wanted:
                    earlier += sum(len(batch.get("games", [])) for batch in result.get("batches", []))
                    continue
            for batch in result.get("batches", []):
                record = batch.get("cards")
                if not isinstance(record, dict) or record.get("v") != cardlog.RECORD_VERSION:
                    pooled["untallied"] += len(batch.get("games", []))
                    continue
                games = record.get("games", 0)
                if type(games) is not int or games < 0:
                    continue
                data = record.get("development")
                development_data.add_side(pooled, data, side, games)
                counted = counted or bool(development_data.valid(data, games) and data["games"])
        matchups += counted
    answer = development_data.summary(pooled)
    answer.update(matchups=matchups, other_engine_games=earlier,
                  note="Simulated Forge games only. A round is two global turns, measured after that block completes; later rows omit games that ended earlier. Drawn counts exclude opening hands and count actual draws, not tutors/returns. Ranges are observed minima/maxima. Mirrors count both list appearances.")
    if not answer["games"]:
        answer["why"] = "No tallied development games yet for this list's visible current-engine matchups. Earlier and untallied games are not filled with zeros."
    elif not any(row["games"] for row in answer["rounds"]):
        answer["why"] = "Tallied games ended before a complete round could be observed."
    return answer
