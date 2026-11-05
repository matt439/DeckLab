"""The listed printing's price beside the cheapest one, for a deck's live owned-vs-needed rows (E5-S31).

Every live A$ figure prices a card at its cheapest paper printing (cards.price_aud, AGENTS.md: default
to the cheapest printing). A decklist line may name a printing and finish, such as
"1 Y'shtola, Night's Blessed (FIC) 207 *F*", that costs far more. pool.compare calls annotate() for a Planned list only (listed=True: the deck
page's target list and the editor's Planned list; never the Play-now list, swaps, precons or the saved
table), so a missing row also says what the copies would cost as listed; the cheapest figures stay the
default.

Only the missing copies count (owned and on-the-way copies are never priced). A name is annotated only
when every line of it in the list names the same printing (set, number and finish) and that printing
is this card; a name listed in several printings, or with a line naming none, keeps only the cheapest
price. Nothing here changes a deck's text, its saved table or the table's rendering: the fields exist
only in the live answer.

A row's difference is material when the listed copies would cost at least MATERIAL_AUD more and at
least MATERIAL_RATIO times the cheapest estimate (an unpriced cheapest row with a priced listing counts
as material once the listing reaches MATERIAL_AUD). Only then does the answer carry totals.as_listed
(the material rows) and totals.aud_missing_as_listed. That total prices every missing copy: each
annotated row at its listed price whether material or not (so a row unpriced at the cheapest but priced
as listed adds its listing, and the total can exceed aud_missing by more than the as_listed rows), an
annotated row whose listing has no price and every other row at the cheapest. The deck page's banner
shows that total ("About A$X in all as listed") only when more than one row is material.
"""

from decklab.lib import cards

MATERIAL_AUD = 5.0          # at least A$5 more for the row's missing copies...
MATERIAL_RATIO = 1.5        # ...and at least 50% more than the cheapest estimate


def _label(set_code, number, finish):
    """"FIC 207 foil" (the finish only when it isn't non-foil), as pool._printing_label words it."""
    return f"{set_code.upper()} {number}" + ("" if finish == "nonfoil" else f" {finish}")


def listed_printings(sections, canonical):
    """{exact name: (set, number, finish)} for each name whose every line names one and the same
    printing. canonical(name) gives a line's exact name (pool._canonical's)."""
    seen = {}
    for lines in sections.values():
        for line in lines:
            name = canonical(line.name)
            key = (line.set.lower(), str(line.number), line.finish or "nonfoil") if line.set and line.number else None
            seen[name] = key if seen.get(name, key) == key else None
    return {name: key for name, key in seen.items() if key is not None}


def material(cheapest, listed):
    """Whether listed (A$ for the missing copies as listed) is materially more than cheapest (or None)."""
    if listed is None:
        return False
    if cheapest is None:
        return listed >= MATERIAL_AUD
    return listed - cheapest >= MATERIAL_AUD and listed >= cheapest * MATERIAL_RATIO


def annotate(rows, totals, sections, canonical, rate, code=None):
    """Add listed_printing, listed_finish, listed_aud_each, listed_aud_missing and listed_material to
    each missing row whose list names a printing other than the priced one, and, when any row is
    material, totals.as_listed (the material rows, dearest first: name, printing, finish, missing,
    aud_each, aud_missing) and totals.aud_missing_as_listed (the missing copies with each annotated
    row at its listed price, unpriced listings at the cheapest). rate: (AUD per USD, its date); code:
    the currency it is in (pool.compare's one read of the setting)."""
    listed = listed_printings(sections, canonical)
    differences = []
    for row in rows:
        printing = listed.get(row["name"])
        if not row["missing"] or printing is None:
            continue
        set_code, number, finish = printing
        printed = cards.printing_card(set_code, number)
        if not printed or printed["name"] != row["name"]:
            continue
        label = _label(set_code, number, finish)
        if label == row.get("priced_printing"):
            continue
        price = cards.price_aud_printing(set_code, number, finish, rate=rate, code=code)
        each = price.aud if price else None
        cost = round(each * row["missing"], 2) if each is not None else None
        row.update(listed_printing=label, listed_finish=finish, listed_aud_each=each,
                   listed_aud_missing=cost, listed_material=material(row.get("aud_missing"), cost))
        if row["listed_material"]:
            differences.append({"name": row["name"], "printing": label, "finish": finish,
                                "missing": row["missing"], "aud_each": each, "aud_missing": cost})
    if differences:
        differences.sort(key=lambda d: (-d["aud_missing"], d["name"]))
        totals["as_listed"] = differences
        totals["aud_missing_as_listed"] = round(sum(
            r["listed_aud_missing"] if r.get("listed_aud_missing") is not None else (r["aud_missing"] or 0)
            for r in rows if r["missing"]), 2)
    return rows
