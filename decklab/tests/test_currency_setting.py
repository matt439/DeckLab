"""config.json's "currency" setting: the currency price estimates are in (E11-S53, second slice).

Run: python scripts/test_fixtures.py decklab.tests.test_currency_setting
Every setting, rate and deck text is supplied here; no rate is fetched and no real cache is read.
"""
import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from decklab.lib import cards, config, currency, decks, pool
from decklab.lib.api import carddata
from decklab.lib.decks import PriceStamp, TableRow, TotalRow


def setting(value=None, present=True, **more):
    settings = dict(config.DEFAULTS, **more)
    if present:
        settings["currency"] = value
    return mock.patch.object(config, "load", return_value=settings)


DECK = """# Test Deck

- **Format:** Casual 60-card, 1v1
- **Status:** idea

## Decklist

```
Deck
4 Llanowar Elves (FDN) 227
```

## Owned vs needed

Prices are **estimates in AUD**: Scryfall's cheapest paper non-foil printing (USD), converted at 1 USD = 1.4224 AUD (ECB rate of 2026-09-25), pulled 2026-09-28.

| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |
|---|---|---|---|---|---|---|
| Llanowar Elves | 4 | 2 | 2 | ~$0.40 | ~$0.80 | |
| **Total to buy** | | | **2** | | **~$0.80** | |

## Substitutes

## Notes
"""


def parse(text=DECK):
    return decks.parse_deck(text.encode(), "test-deck", "casual")


class CodeTests(unittest.TestCase):
    def setUp(self):
        currency._said.clear()
        self.addCleanup(currency._said.clear)

    def code(self, value=None, present=True):
        with setting(value, present), contextlib.redirect_stderr(io.StringIO()) as err:
            return currency.code(), err.getvalue()

    def test_unset_or_blank_is_aud_as_before(self):
        self.assertEqual(self.code(present=False), ("AUD", ""))
        self.assertEqual(self.code(None), ("AUD", ""))
        self.assertEqual(self.code("  "), ("AUD", ""))

    def test_an_ecb_code_in_any_case(self):
        self.assertEqual(self.code("eur"), ("EUR", ""))
        self.assertEqual(self.code(" GBP "), ("GBP", ""))
        self.assertEqual(self.code("USD"), ("USD", ""))

    def test_a_code_without_an_ecb_rate_stays_aud_and_is_said_once(self):
        got, said = self.code("XYZ")
        self.assertEqual(got, "AUD")
        self.assertIn("XYZ", said)
        self.assertEqual(self.code("XYZ")[1], "")
        self.assertEqual(self.code(42)[0], "AUD")

    def test_symbols_and_cells(self):
        self.assertEqual((currency.symbol("AUD"), currency.symbol("EUR"), currency.symbol("SEK")), ("A$", "€", "SEK "))
        self.assertEqual(currency.money(12.5, "GBP"), "£12.50")
        self.assertEqual(currency.cell(1234.5, "AUD"), "~$1,234.50")
        self.assertEqual((currency.cell(0.4, "EUR"), currency.cell(0.4, "CAD"), currency.cell(0.4, "SEK")),
                         ("~€0.40", "~$0.40", "~0.40"))
        self.assertEqual(decks.format_aud(0.4), "~$0.40")
        self.assertEqual(decks.format_aud(0.4, "EUR"), "~€0.40")


class RateTests(unittest.TestCase):
    RESPONSE = {"amount": 1.0, "base": "USD", "date": "2026-10-30", "rates": {"EUR": 0.9}}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for patcher in (mock.patch.object(cards, "FX_FILE", self.tmp / "fx.json"),
                        mock.patch.object(cards, "_fx", None), mock.patch.object(cards, "_fx_tried_on", None),
                        mock.patch.object(cards, "_fx_tried_at", None), mock.patch.object(cards, "_fx_code", "AUD")):
            patcher.start()
            self.addCleanup(patcher.stop)
        # An AUD rate cached already: another currency must never read it.
        cards._write_json(self.tmp / "fx.json", {"rate": 1.42, "date": "2026-10-29", "fetched_on": date.today().isoformat()})

    def test_aud_still_uses_fx_json_without_fetching(self):
        with setting(), mock.patch.object(cards, "_get_json") as get:
            self.assertEqual(cards.usd_to_aud(), (1.42, "2026-10-29"))
        get.assert_not_called()
        self.assertEqual(cards.fx_file(), self.tmp / "fx.json")

    def test_another_currency_fetches_its_own_rate_into_its_own_file(self):
        with setting("EUR"), mock.patch.object(cards, "_get_json", return_value=self.RESPONSE) as get:
            self.assertEqual(cards.usd_to_aud(), (0.9, "2026-10-30"))
            self.assertEqual(cards.usd_to_aud(), (0.9, "2026-10-30"))
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args[0][0], "https://api.frankfurter.dev/v1/latest?from=USD&to=EUR")
        saved = json.loads((self.tmp / "fx-eur.json").read_text(encoding="utf-8"))
        self.assertEqual((saved["rate"], saved["to"]), (0.9, "EUR"))
        self.assertEqual(json.loads((self.tmp / "fx.json").read_text(encoding="utf-8"))["rate"], 1.42)
        with setting(), mock.patch.object(cards, "_get_json") as get:       # back to AUD: its own rate again
            self.assertEqual(cards.usd_to_aud(), (1.42, "2026-10-29"))
        get.assert_not_called()

    def test_offline_without_its_own_cache_names_the_currency(self):
        with setting("GBP"), mock.patch.object(cards, "_get_json", side_effect=OSError("offline")):
            with self.assertRaisesRegex(RuntimeError, "No USD->GBP rate"):
                cards.usd_to_aud()

    def test_usd_is_one_and_never_fetched(self):
        with setting("USD"), mock.patch.object(cards, "_get_json") as get:
            self.assertEqual(cards.usd_to_aud(), (1.0, date.today().isoformat()))
        get.assert_not_called()

    def test_a_price_label_names_the_currency(self):
        price = cards.Price("Llanowar Elves", 0.36, 0.4, 0.9, "2026-10-30", "2026-10-31", "fdn", "227",
                            currency="EUR")
        self.assertEqual(price.label(), "~€0.36 est. (US$0.40, FDN 227, Scryfall 2026-10-31; 1 USD = 0.9 EUR, ECB 2026-10-30)")
        aud = cards.Price("Llanowar Elves", 0.57, 0.4, 1.42, "2026-10-30", "2026-10-31", "fdn", "227")
        self.assertEqual(aud.label(), "~A$0.57 est. (US$0.40, FDN 227, Scryfall 2026-10-31; 1 USD = 1.42 AUD, ECB 2026-10-30)")


class DeckTableTests(unittest.TestCase):
    def test_an_aud_table_reads_as_before_and_renders_byte_for_byte(self):
        deck = parse()
        self.assertEqual((deck.table_currency, deck.prices), ("AUD", PriceStamp(1.4224, "2026-09-25", "2026-09-28")))
        self.assertEqual(decks.render_deck_file(deck), DECK)
        decks.set_table(deck, deck.rows, deck.total, PriceStamp(1.43, "2026-10-01", "2026-10-02"))
        self.assertEqual(decks.render_deck_file(deck),
                         DECK.replace("1 USD = 1.4224 AUD (ECB rate of 2026-09-25), pulled 2026-09-28",
                                      "1 USD = 1.43 AUD (ECB rate of 2026-10-01), pulled 2026-10-02"))

    def test_repricing_in_another_currency_renames_the_header_and_the_stamp(self):
        deck = parse()
        rows = [TableRow("Llanowar Elves", 4, 2, 2, "~€0.36", "~€0.72")]
        decks.set_table(deck, rows, TotalRow(2, "~€0.72"), PriceStamp(0.9, "2026-10-30", "2026-10-31", "EUR"))
        text = decks.render_deck_file(deck)
        self.assertIn("| Card | Need | Owned | Missing | ~EUR each | ~EUR missing | Notes |", text)
        self.assertIn("converted at 1 USD = 0.9 EUR (ECB rate of 2026-10-30), pulled 2026-10-31.", text)
        self.assertNotIn("~AUD", text)
        again = parse(text)
        self.assertEqual((again.table_currency, again.prices),
                         ("EUR", PriceStamp(0.9, "2026-10-30", "2026-10-31", "EUR")))
        self.assertEqual(decks.render_deck_file(again), text)
        decks.set_table(again, again.rows, again.total)         # a refresh without prices keeps it all
        self.assertEqual(decks.render_deck_file(again), text)

    def test_a_new_table_in_another_currency_gets_its_note(self):
        text = DECK.replace(DECK[DECK.index("Prices are"):DECK.index("| Card")], "")
        deck = parse(text)
        self.assertIn("prices_insert", deck.spans)
        decks.set_table(deck, deck.rows, deck.total, PriceStamp(0.79, "2026-10-30", "2026-10-31", "GBP"))
        out = decks.render_deck_file(deck)
        self.assertIn("Prices are **estimates in GBP**: Scryfall's cheapest paper non-foil printing (USD), converted at "
                      "1 USD = 0.79 GBP (ECB rate of 2026-10-30), pulled 2026-10-31.", out)
        self.assertIn("~GBP each", out)

    def test_new_deck_text_names_the_currency(self):
        text = decks.new_deck_text("New", "casual", [("Status", "idea")], {}, currency="EUR")
        self.assertIn("| ~EUR each | ~EUR missing |", text)
        self.assertEqual(parse(text).table_currency, "EUR")
        self.assertIn(decks.TABLE_HEADER, decks.new_deck_text("New", "casual", [("Status", "idea")], {}))

    def test_a_header_with_mixed_or_odd_currencies_isnt_the_table(self):
        for header in ("| Card | Need | Owned | Missing | ~EUR each | ~AUD missing | Notes |",
                       "| Card | Need | Owned | Missing | ~eur each | ~eur missing | Notes |"):
            deck = parse(DECK.replace(decks.TABLE_HEADER, header))
            self.assertIsNone(deck.rows)
            self.assertIsNone(deck.table_currency)

    def test_repricing_still_refuses_a_rate_worded_otherwise_naming_the_currency(self):
        text = DECK.replace("converted at 1 USD = 1.4224 AUD (ECB rate of 2026-09-25), pulled 2026-09-28.",
                            "converted at USD 1 = AUD 1.4224 (ECB, 2026-09-25).")
        deck = parse(text)
        self.assertIn("prices_other", deck.spans)
        decks.set_table(deck, deck.rows, deck.total)
        self.assertEqual(decks.render_deck_file(deck), text)
        decks.set_table(deck, deck.rows, deck.total, PriceStamp(0.9, "2026-10-30", "2026-10-31", "EUR"))
        with self.assertRaisesRegex(decks.DeckFileError,
                                    r"reword it as '1 USD = \{rate\} EUR \(ECB rate of \{rate_date\}\), pulled"):
            decks.render_deck_file(deck)

    def test_pool_table_rows_write_cells_and_stamp_in_the_result_currency(self):
        result = {"rate": 0.9, "rate_date": "2026-10-30", "price_date": "2026-10-31", "currency": "EUR",
                  "rows": [{"name": "Llanowar Elves", "need": 4, "missing": 2, "aud_each": 0.36, "aud_missing": 0.72,
                            "priced_finish": "nonfoil", "on_the_way_from": [], "used_by": []}],
                  "totals": {"missing": 2, "aud_missing": 0.72, "unpriced": []}}
        with mock.patch.object(pool, "_labels", return_value=()):
            rows, total, stamp = pool.table_rows(result)
            self.assertEqual((rows[0].aud_each, rows[0].aud_missing, total.aud_missing), ("~€0.36", "~€0.72", "~€0.72"))
            self.assertEqual(stamp, PriceStamp(0.9, "2026-10-30", "2026-10-31", "EUR"))
            del result["currency"]                                    # AUD: as before
            rows, total, stamp = pool.table_rows(result)
            self.assertEqual((rows[0].aud_each, stamp.currency), ("~$0.36", "AUD"))


class StatusTests(unittest.TestCase):
    def test_pricing_names_the_currency_and_the_shops(self):
        with setting("EUR", shops=["gamesportal"]):
            self.assertEqual(carddata.pricing(), {"currency": "EUR", "symbol": "€", "currency_default": False,
                                                  "shops": [{"key": "gamesportal", "name": "Games Portal"}]})
        with setting(present=False, shops=[]):
            self.assertEqual(carddata.pricing(), {"currency": "AUD", "symbol": "A$", "currency_default": True,
                                                  "shops": []})

    def test_the_cached_rate_is_the_configured_currencys(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        cards._write_json(tmp / "fx.json", {"rate": 1.42, "date": "2026-10-29"})
        with mock.patch.object(cards, "FX_FILE", tmp / "fx.json"):
            with setting():
                self.assertEqual(carddata._cached_rate(), {"rate": 1.42, "date": "2026-10-29"})
            with setting("EUR"):
                self.assertIsNone(carddata._cached_rate())
                cards._write_json(tmp / "fx-eur.json", {"rate": 0.9, "date": "2026-10-30", "to": "EUR"})
                self.assertEqual(carddata._cached_rate(), {"rate": 0.9, "date": "2026-10-30"})
            with setting("USD"):
                self.assertEqual(carddata._cached_rate(), {"rate": 1.0, "date": date.today().isoformat()})

    def test_an_unreadable_config_still_answers_status(self):
        # /api/status answers without config.json (the footer still shows), in the default currency.
        with mock.patch.object(config, "load", side_effect=ValueError("broken")):
            self.assertEqual(currency.code(), "AUD")
            answer = carddata.status()
        self.assertIsNone(answer["pricing"])
        self.assertIn("fx", answer)


try:
    from decklab.tests.test_deck_page_ui import PAGE
    from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB
except ImportError:         # pragma: no cover
    NODE = None


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PageTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), PAGE + code, True, None]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_amounts_and_settings_follow_the_status_pricing(self):
        self.run_js(r"""
          state.status = null;
          assert.equal(aud(1.5), 'A$1.50');
          assert.equal(pricingWords(undefined), '');
          state.status = {pricing: {currency: 'EUR', symbol: '€', currency_default: false,
            shops: [{key: 'gamesportal', name: 'Games Portal'}]}};
          assert.equal(aud(1.5), '€1.50');
          // A shop's own listing is its AUD, never relabelled (review of 2026-11-05).
          assert.equal(listedAud(1.5), 'A$1.50');
          assert.equal(shopBasketAud('12.00'), 'A$12.00');
          assert(shopPrice({listed_aud: '0.50', listed_at: 'Ronin Games'}).startsWith('A$0.50'));
          const words = pricingWords(state.status.pricing);
          for (const text of ['estimates in EUR', 'Price-check shops: Games Portal', 'config.json'])
            assert(words.includes(text), words);
          const off = pricingWords({currency: 'AUD', symbol: 'A$', currency_default: true, shops: []});
          assert(off.includes('in AUD (the default)') && off.includes('none (the nightly shop check is off)'), off);
          assert.equal(footerLine({cards: {ready: true, price_date: '2026-10-31'}, fx: {rate: 0.9}}),
            'Prices 2026-10-31 · 1 USD = 0.9 EUR');
          state.status = null;
        """)

    def test_the_deck_price_note_names_the_api_currency(self):
        self.run_js(r"""
          state.status = {pricing: {currency: 'EUR', symbol: '€', currency_default: false, shops: []}};
          const owned = {rows: [{name: 'Alpha', need: 2, missing: 1, owned: 1, available: 1, aud_each: 2, aud_missing: 2,
              labels: {on_the_way: [], in_use: []}}],
            totals: {cards: 1, need: 2, missing: 1, aud_missing: 2, unpriced: []}, currency: 'EUR',
            price_error: null, price_date: '2026-10-31', rate: 0.9, rate_date: '2026-10-30',
            conflicts: [], unresolved: [], warnings: []};
          state.cards = new Map([['Alpha', card('Alpha', 'Creature', 1)]]);
          const section = ownedSection({owned, table: null, summary: makePage().summary});
          for (const text of ['€ prices are estimates', '1 USD = 0.9 EUR', 'about €2.00', '~EUR missing'])
            assert(section.textContent.includes(text), text);
          assert(!section.textContent.includes('AUD missing'), section.textContent);
          state.status = null;
        """)
