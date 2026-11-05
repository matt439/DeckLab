"""Labels that follow the configured currency (E11-S53, third slice): the command lines' and the API
answers' and the pages' words for Scryfall estimates, AUD byte for byte as before, while the shops'
own AUD listings stay A$.

Run: python scripts/test_fixtures.py decklab.tests.test_currency_labels
Every setting, rate and answer is supplied here; nothing is fetched and no database is read.
"""
import contextlib
import io
import json
import subprocess
import unittest
from unittest import mock

from decklab.lib import cards, combos, config, currency, edhrec, pool, pricing_setting
from decklab.lib.api import collection_edit, variant_buying


def setting(value=None):
    settings = dict(config.DEFAULTS)
    if value is not None:
        settings["currency"] = value
    return mock.patch.object(config, "load", return_value=settings)


def printed(call, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        call(*args)
    return out.getvalue()


def pool_result(code=None):
    result = {"deck_id": "casual/test", "version": "target",
              "rows": [{"name": "Alpha", "need": 2, "owned": 1, "on_the_way": 0, "in_use_elsewhere": [], "missing": 1,
                        "aud_each": 1.2, "aud_missing": 1.2, "priced_finish": "nonfoil", "on_the_way_from": []}],
              "totals": {"cards": 1, "need": 2, "missing": 1, "aud_missing": 1.2, "unpriced": []},
              "rate": 1.42 if code is None else 0.9, "rate_date": "2026-10-30", "price_date": "2026-10-31",
              "price_error": None, "conflicts": [], "unresolved": [], "warnings": []}
    if code:
        result["currency"] = code
    return result


def edhrec_result(code=None):
    result = {"commanders": ["Alpha"], "identity": "G", "page": "", "pages": [],
              "source": {"url": "https://edhrec.example/alpha", "fetched": "2026-10-31", "decks": 10, "stale": None},
              "price_error": None, "left_out": [], "rate": 1.42 if code is None else 0.9, "rate_date": "2026-10-30",
              "price_date": "2026-10-31",
              "groups": [{"header": "Top cards", "cards": [{"name": "Beta", "inclusion": 50, "status": "to_buy",
                                                            "free": 0, "aud_each": 1.2, "in_deck": False,
                                                            "considering": False}]}]}
    if code:
        result["currency"] = code
    return result


def near_result(code=None):
    prices = {"rate": 1.42 if code is None else 0.9, "rate_date": "2026-10-30", "price_date": "2026-10-31"}
    if code:
        prices["currency"] = code
    return {"checked": True, "total": 1, "prices": prices,
            "matches": [{"names": ["Alpha", "Beta"], "missing": "Beta", "results": ["Win"], "raises_minimum": False,
                         "minimum_with": 2, "aud": 1.2, "url": "https://combos.example/1"}]}


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        pricing_setting.forget()
        currency._said.clear()

    def test_pool_aud_is_byte_for_byte_and_others_name_their_currency(self):
        aud = printed(pool._print_result, pool_result())
        self.assertIn("Missing  A$ each  A$ missing\n", aud)
        self.assertIn(", about A$1.20 to buy\n", aud)
        self.assertIn("AUD estimates: Scryfall prices of 2026-10-31, 1 USD = 1.42 AUD (ECB 2026-10-30).\n", aud)
        eur = printed(pool._print_result, pool_result("EUR"))
        self.assertIn("Missing  € each  € missing\n", eur)
        self.assertIn("1 USD = 0.9 EUR", eur)
        self.assertIn("Missing  SEK each  SEK missing\n", printed(pool._print_result, pool_result("SEK")))

    def help_text(self, code):
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with setting(code), self.assertRaises(SystemExit), contextlib.redirect_stdout(out):
            pool.main(["--help"])
        out.flush()
        return " ".join(out.buffer.getvalue().decode("utf-8").split())

    def test_pool_help_names_the_configured_currency(self):
        self.assertIn("skip the AUD estimates", self.help_text(None))
        self.assertIn("skip the EUR estimates", self.help_text("EUR"))

    def test_edhrec_lines(self):
        aud = printed(edhrec._print, edhrec_result(), False)
        self.assertIn("Prices: ~AUD, cheapest non-foil printing, 1 USD = 1.42 AUD (ECB rate of 2026-10-30), "
                      "pulled 2026-10-31\n", aud)
        self.assertIn("[to buy, ~A$1.20]", aud)
        eur = printed(edhrec._print, edhrec_result("EUR"), False)
        self.assertIn("Prices: ~EUR, cheapest non-foil printing, 1 USD = 0.9 EUR", eur)
        self.assertIn("[to buy, ~€1.20]", eur)

    def test_combos_lines(self):
        aud = printed(combos._print_near, "commander/test", near_result(), None)
        self.assertIn("add Beta ~A$1.20 (with Alpha)", aud)
        self.assertIn("AUD estimates: 1 USD = 1.42 AUD (2026-10-30), card prices of 2026-10-31.\n", aud)
        eur = printed(combos._print_near, "commander/test", near_result("EUR"), None)
        self.assertIn("add Beta ~€1.20 (with Alpha)", eur)
        self.assertIn("EUR estimates: 1 USD = 0.9 EUR", eur)


class NotEditsTests(unittest.TestCase):
    """pg_decks.NOT_EDITS_RE (the library's "last edited"): a reprice changes only Deck Lab's own lines in any
    currency, so it isn't an edit. Python's re reads the pattern as PostgreSQL's regexp_replace does here."""

    def body(self, stamp):
        import re
        from decklab.lib.inventory import pg_decks
        text = (f"# Gruul Ramp\n\n- **Status:** built\n\n## Owned vs needed\n\nPrices converted at {stamp.text()}.\n\n"
                f"| Card | Need |\n|---|---|\n| Alpha | {stamp.rate} |\n\n## Notes\n\nHand notes.\n")
        return re.sub(pg_decks.NOT_EDITS_RE, "", text)

    def test_a_reprice_in_any_currency_is_not_an_edit(self):
        from decklab.lib.decks import PriceStamp
        aud = self.body(PriceStamp(1.42, "2026-10-30", "2026-10-31"))
        self.assertEqual(aud, self.body(PriceStamp(1.45, "2026-11-01", "2026-11-02")))
        eur = self.body(PriceStamp(0.9, "2026-10-30", "2026-10-31", "EUR"))
        self.assertEqual(eur, self.body(PriceStamp(0.91, "2026-11-01", "2026-11-02", "EUR")))
        self.assertEqual(eur, aud)
        self.assertNotIn("1 USD", eur)
        self.assertIn("Hand notes.", eur)


class ApiTagTests(unittest.TestCase):
    def setUp(self):
        pricing_setting.forget()

    def prices(self, code):
        with setting(code), mock.patch.object(collection_edit, "_ready", return_value=True), \
                mock.patch.object(cards, "usd_to_aud", return_value=(0.9 if code else 1.42, "2026-10-30")), \
                mock.patch.object(cards, "price_date", return_value="2026-10-31"), \
                mock.patch.object(cards, "printing_usd", return_value=1.0):
            return collection_edit._prices([{"set": "fdn", "collector_number": "1", "finish": "nonfoil"}])

    def test_an_aud_answer_is_unchanged_and_another_is_tagged(self):
        aud = self.prices(None)
        self.assertEqual(set(aud), {"rows", "rate", "rate_date", "price_date", "price_error"})
        self.assertEqual(self.prices("EUR")["currency"], "EUR")
        self.assertEqual(currency.tag("AUD"), {})
        self.assertEqual(currency.tag_of({"rate": 1}), {})
        self.assertEqual(currency.tag_of({"currency": "EUR"}), {"currency": "EUR"})

    def test_variant_estimate_is_tagged_and_references_keep_aud(self):
        for code, expected in ((None, None), ("EUR", "EUR")):
            rows = [{"name": "Alpha", "references": []}, {"name": "Beta", "references": [{"aud": 0.5}]}]
            with setting(code), \
                    mock.patch.object(variant_buying.carddata, "_cached_rate", return_value={"rate": 0.9, "date": "2026-10-30"}), \
                    mock.patch.object(cards, "price_date", return_value="2026-10-31"), \
                    mock.patch.object(cards, "cheapest_usd", return_value=(1.0, "fdn", "1", "nonfoil")):
                variant_buying._estimates(rows)
            self.assertEqual(rows[0]["estimate"].get("currency"), expected)
            self.assertNotIn("estimate", rows[1])
            self.assertEqual(rows[1]["references"], [{"aud": 0.5}])


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

    def test_rate_words_and_answer_currency(self):
        self.run_js(r"""
          state.status = {pricing: {currency: 'EUR', symbol: '€', currency_default: false, shops: []}};
          const a = {rate: 1.4237, rate_date: '2026-10-30', price_date: '2026-10-31'};
          // A missing currency is AUD, whatever the status says (a stale status mustn't relabel an AUD answer).
          assert.equal(ansCurrency(a), 'AUD');
          assert.equal(estimateRateWords(a), "Estimates in AUD: Scryfall's cheapest non-foil printing at 1 USD = 1.4237 AUD (ECB rate of 2026-10-30), prices pulled 2026-10-31.");
          assert(estimateRateWords({...a, rate: 0.9, currency: 'EUR'}).startsWith('Estimates in EUR: ') );
          assert(estimateRateWords({...a, rate: 0.9, currency: 'EUR'}).includes('1 USD = 0.9 EUR'));
          assert.equal(moneyIn(1.5, 'AUD'), 'A$1.50');
          assert.equal(moneyIn(1.5, 'EUR'), '€1.50');
          assert.equal(moneyIn(1.5, 'SEK'), 'SEK 1.50');
          state.status = null;
        """)

    def test_collection_labels(self):
        self.run_js(r"""
          state.status = null;
          assert.equal(colSortWords('price'), '~A$ each');
          assert.equal(colSortWords('name'), 'Card');
          state.status = {pricing: {currency: 'EUR', symbol: '€', currency_default: false, shops: []}};
          assert.equal(colSortWords('price', {currency: 'EUR'}), '~€ each');
          // A kept AUD answer stays A$ after the status turns to EUR (a Settings change in another tab).
          assert.equal(colSortWords('price', {rate: 1.42}), '~A$ each');
          assert.equal(colSortWords('price', {currency: 'SEK'}), '~SEK each');
          assert.equal(ansMoney(1.5, {rate: 1.42}), 'A$1.50');
          assert.equal(ansMoney(1.5, {currency: 'EUR'}), '€1.50');
          assert.equal(ansSign(null), 'A$');
          const cv = {priceNote: el('p'), rows: [{}], prices: {rate: 0.9, rate_date: '2026-10-30', currency: 'EUR'}};
          drawColPriceNote(cv);
          assert(cv.priceNote.textContent.startsWith('~€ each is an estimate'), cv.priceNote.textContent);
          assert(cv.priceNote.textContent.includes('1 USD = 0.9 EUR'), cv.priceNote.textContent);
          state.status = null;
          cv.prices = {rate: 1.42, rate_date: '2026-10-30'};
          drawColPriceNote(cv);
          assert(cv.priceNote.textContent.startsWith('~A$ each is an estimate'), cv.priceNote.textContent);
          assert(cv.priceNote.textContent.includes('1 USD = 1.42 AUD'), cv.priceNote.textContent);
        """)

    def test_deck_and_editor_amounts_follow_their_answer_not_the_status(self):
        self.run_js(r"""
          state.status = {pricing: {currency: 'EUR', symbol: '€', currency_default: false, shops: []}};
          const audAnswer = {rate: 1.42};
          // The status says EUR, but these answers have no currency: they're AUD, and say so.
          assert.equal(edhrecMarkWords({status: 'to_buy', aud_each: 1.2}, true, audAnswer)[0], 'To buy · ~A$1.20');
          assert.equal(edhrecMarkWords({status: 'to_buy', aud_each: 1.2}, true, {currency: 'EUR'})[0], 'To buy · ~€1.20');
          const listed = {missing: 1, listed_printing: 'FIC 207', listed_aud_each: 5, aud_each: 1};
          assert.equal(listedPriceWords(listed, audAnswer), 'As listed (FIC 207): A$5.00 each');
          assert.equal(asListedWords({missing: 2, name: 'Alpha', printing: 'FIC 207', aud_missing: 9}, {currency: 'EUR'}),
            '2 Alpha (FIC 207) about €9.00');
          const side = editorEdhrecSide({edhrec: {row: {status: 'to_buy', aud_each: 2}, marks: true, answer: audAnswer}});
          assert(side.some(node => node && node.textContent === 'To buy · ~A$2.00'));
          assert.equal(searchResultSide({name: 'Alpha', aud: 3, aud_currency: 'AUD', have: 0})[0].textContent, 'A$3.00');
          assert.equal(searchResultSide({name: 'Alpha', aud: 3, aud_currency: 'EUR', have: 0})[0].textContent, '€3.00');
          const near = {checked: true, total: 1, prices: {rate: 1.42, rate_date: '2026-10-30', price_date: '2026-10-31'},
            matches: [{names: ['Alpha', 'Beta'], missing: 'Beta', results: ['Win'], aud: 1.2, url: 'https://combos.example/1'}]};
          const data = {summary: {read_only: true}, version: 'target', stats: {commander: {bracket: {near_combos: near}}}};
          assert(nearCombosPanel(data).textContent.includes('About A$1.20.'));
          state.status = null;
        """)

    def test_variant_references_stay_aud_and_the_estimate_follows(self):
        self.run_js(r"""
          state.status = {pricing: {currency: 'EUR', symbol: '€', currency_default: false, shops: []}};
          const ref = vtBuyingPrice({name: 'Alpha', references: [{aud: 0.5, shop: 'Shop', checked: '2026-10-30', printing: 'any'}]});
          assert(ref.textContent.includes('A$0.50 each at Shop'), ref.textContent);
          const est = vtBuyingPrice({name: 'Alpha', references: [], estimate: {aud: 0.45, set: 'fdn', collector_number: '1',
            finish: 'nonfoil', price_date: '2026-10-31', rate: 0.9, rate_date: '2026-10-30', currency: 'EUR'}});
          assert(est.textContent.includes('€0.45 each'), est.textContent);
          assert(est.textContent.includes('1 USD = 0.9 EUR'), est.textContent);
          const old = vtBuyingPrice({name: 'Alpha', references: [], estimate: {aud: 0.45, set: 'fdn', collector_number: '1',
            finish: 'nonfoil', price_date: '2026-10-31', rate: 1.42, rate_date: '2026-10-30'}});
          assert(old.textContent.includes('A$0.45 each') && old.textContent.includes('1 USD = 1.42 AUD'), old.textContent);
          state.status = null;
        """)

    def test_editor_note_and_near_combos_follow_the_answer(self):
        self.run_js(r"""
          const o = (extra) => ({rows: [{name: 'Alpha', missing: 1, need: 1, owned: 0, aud_each: 1.5, labels: {on_the_way: []}}],
            totals: {cards: 1, need: 1, missing: 1, aud_missing: 1.5, unpriced: []}, price_error: null,
            price_date: '2026-10-31', rate: 1.42, rate_date: '2026-10-30', ...extra});
          const audNote = ownedPreview(o({})).textContent;
          assert(audNote.includes("A$ are estimates: Scryfall's US prices of 2026-10-31 × 1 USD = 1.42 AUD"), audNote);
          assert(audNote.includes('about A$1.50 each'), audNote);
          state.status = {pricing: {currency: 'EUR', symbol: '€', currency_default: false, shops: []}};
          const eurNote = ownedPreview(o({currency: 'EUR', rate: 0.9})).textContent;
          assert(eurNote.includes('€ are estimates') && eurNote.includes('1 USD = 0.9 EUR'), eurNote);
          assert(eurNote.includes('about €1.50 each'), eurNote);
          assert(ownedPreview(o({price_error: 'offline'})).textContent.includes('No EUR estimates: offline'));
          const near = {checked: true, total: 1, prices: {rate: 0.9, rate_date: '2026-10-30', price_date: '2026-10-31', currency: 'EUR'},
            matches: [{names: ['Alpha', 'Beta'], missing: 'Beta', results: ['Win'], aud: 1.2, url: 'https://combos.example/1'}]};
          const data = {summary: {read_only: true}, version: 'target', stats: {commander: {bracket: {near_combos: near}}}};
          assert(nearCombosPanel(data).textContent.includes('1 USD = 0.9 EUR, ECB 2026-10-30'));
          delete near.prices.currency; near.prices.rate = 1.42;
          assert(nearCombosPanel(data).textContent.includes('1 USD = 1.42 AUD, ECB 2026-10-30'));
          state.status = null;
        """)

    def test_shop_and_undo_labels_stay_aud(self):
        self.run_js(r"""
          state.status = {pricing: {currency: 'EUR', symbol: '€', currency_default: false, shops: []}};
          assert.equal(ACTIVITY_UNDO_WATCHLIST_WORDS.listed_aud, 'Reference price (AUD)');
          assert.equal(shopBasketAud('12.00'), 'A$12.00');
          state.status = null;
        """)


if __name__ == "__main__":
    unittest.main()
