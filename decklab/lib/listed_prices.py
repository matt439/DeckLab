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

annotate_owned() (E2-S30) is the same comparison for the copies the space has: a row whose list names
one printing, and whose card the space owns or awaits, also says whether the space has that printing
or only another (own_printing "listed" or "other", own_printing_label, own_printing_more,
own_printing_on_the_way). It is a quiet note for whoever may see the space's inventory, never a
warning: it changes no count, and it says nothing about which deck holds a copy or whether one is
free (the counts are the space's whole collection and pending orders, pool.printing_counts). A card
the deck's own Printings in box record names gets none, since that record already says what is there.
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


FINISHES = ("nonfoil", "foil", "etched")


def _copies(counts, key):
    """(copies in the collection, copies on the way) of one printing in pool.printing_counts()."""
    found = counts.get(key) or {}
    return found.get("owned", 0), found.get("on_the_way", 0)


def annotate_owned(rows, sections, canonical, counts, recorded=()):
    """Add own_printing ("listed": the space has the printing the list names; "other": only other
    printings), own_printing_label (that printing, or for "other" the other printing it has most
    copies of, as "FDN 227" or "FDN 227 foil"), own_printing_more (how many further other printings
    it has; 0 for "listed") and own_printing_on_the_way (True when the copies named are only on the
    way, none in the collection yet) to each row with copies owned or on the way whose every line
    names one and the same printing of this card. counts: pool.printing_counts() of the deck's
    space; recorded: the names the deck's own Printings in box record names, which get no note.
    A row whose copies' printings can't be told (none of the card's printings is counted) gets none.
    Nothing else on a row changes."""
    listed = listed_printings(sections, canonical)
    recorded = set(recorded)
    for row in rows:
        name = row["name"]
        printing = listed.get(name)
        if printing is None or not row.get("owned") or name in recorded:
            continue
        if callable(counts):            # a function giving the counts: read only once a row could have a note
            counts = counts()
        set_code, number, finish = printing
        printed = cards.printing_card(set_code, number)
        if not printed or printed["name"] != name:
            continue
        here, coming = _copies(counts, printing)
        if here or coming:
            row.update(own_printing="listed", own_printing_label=_label(*printing), own_printing_more=0,
                       own_printing_on_the_way=not here)
            continue
        others = []
        for other_set, other_number in (cards.card(name) or {}).get("printings", []):
            for other_finish in FINISHES:
                key = (str(other_set).lower(), str(other_number), other_finish)
                here, coming = _copies(counts, key)
                if key != printing and (here or coming):
                    others.append((-here, -coming, key))
        if not others:
            continue
        others.sort()
        in_hand = [other for other in others if other[0]] or others     # the collection's before incoming ones
        row.update(own_printing="other", own_printing_label=_label(*in_hand[0][2]),
                   own_printing_more=len(in_hand) - 1, own_printing_on_the_way=not in_hand[0][0])
    return rows


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
