"""Saved Shopping metadata gets P1 presentation without implying live prices, stock or physical printings."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingMetadataInteractionTests(unittest.TestCase):
    def run_js(self, scenario):
        setup = """
          clear(main); state.profile={id:'user1'}; state.profiles=[state.profile];
          state.may={admin:false,orders:true,see_inventory:['home']}; location.hash='#/shopping';
          const empty={orders:[],checks:[],warnings:[],queue_revision:'q1',to_buy:[]};
          const card=name=>({name,type_line:'Creature',mana_cost:'',img:'/img/test/1/normal',img_small:'/img/test/1/small'});
          const row=(name,extra={})=>({name,quantity:1,state:'ready',for:'',printing:'any',set:'',collector_number:'',finish:'',
            listed_aud:'',listed_at:'',checked:'',in_stock:'',notes:'',card:card(name),deck:null,queue_row:1,...extra});
          const entry=()=>main.querySelector('[data-shop-queue]');
          const density=lab=>{const query=window.matchMedia(SHOP_QUEUE_LAB);query.matches=lab;query.fire('change')};
          const now=new Date('2026-10-25T12:00:00').getTime();
          api=()=>{throw new Error('Must not read')}; apiWrite=()=>{throw new Error('Must not write')}; toast=()=>{};
        """
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), setup + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_valid_saved_calendar_days_use_shared_freshness_without_losing_exact_dates(self):
        self.run_js("""
          for(const [date,kind] of [['2026-10-25','fresh'],['2026-10-01','aging'],['2025-10-24','stale']]) {
            const node=shopChecked(date,{now}), badge=node.querySelector('.fresh'); assert(badge);
            assert(badge.getAttribute('class').includes('is-'+kind)); assert.equal(badge.getAttribute('role'),'img');
            assert.equal(node.tag,'time'); assert.equal(node.getAttribute('datetime'),date);
            assert.equal(node.getAttribute('title'),'Recorded check date: '+date);
            assert(badge.getAttribute('aria-label').includes('Checked'));
            assert(!badge.textContent.includes('retest')); assert(!badge.textContent.includes('check again'));
            const compact=shopChecked(date,{compact:true,now}); assert.equal(compact.textContent,date);
            assert.equal(compact.querySelector('.fresh'),null); assert.equal(compact.getAttribute('datetime'),date);
          }
          assert.equal(shopCheckDay('2024-02-29').getDate(),29);
        """)

    def test_unknown_invalid_and_future_dates_never_get_a_fabricated_age_badge(self):
        self.run_js("""
          for(const value of ['',null,'2026-02-30','2026-13-01','yesterday','2026-10-26']) {
            const node=shopChecked(value,{now}); assert.equal(node.querySelector('.fresh'),null);
            if(value) assert(node.textContent.includes(value)); else assert.equal(node.textContent,'Check date not recorded');
          }
          assert.equal(shopCheckDay('2026-02-30'),null); assert.equal(shopCheckDay('2026-2-01'),null);
          const future=shopChecked('2026-10-26',{now}); assert.equal(future.getAttribute('datetime'),'2026-10-26');
          assert(!future.textContent.includes('today')); assert.equal(future.textContent,'Recorded check date: 2026-10-26');
          const bad=shopChecked('not a day',{compact:true,now}); assert.equal(bad.getAttribute('datetime'),null);
          assert.equal(bad.textContent,'not a day');
        """)

    def test_casual_exact_printing_and_neutral_finish_keep_full_requested_facts_spoken_once(self):
        self.run_js("""
          for(const finish of ['foil','etched','nonfoil','']) {
            const item=row('Alpha',{printing:'exact',set:'fdn',collector_number:'123',finish});
            const before=JSON.stringify(item), meta=shopPrintingMeta(item), visual=meta.querySelector('.shop-printing-visual');
            assert.equal(visual.getAttribute('aria-hidden'),'true');
            assert.equal(meta.querySelector('.sr-only').textContent,shopPrintingIntent(item));
            assert(visual.querySelector('.shop-exact-tag').textContent.includes('EXACT FDN'));
            assert(visual.textContent.includes('123'));
            const chip=visual.querySelector('.chip-foil'); assert.equal(Boolean(chip),['foil','etched'].includes(finish));
            if(chip) assert(chip.getAttribute('class').includes('chip-plain'));
            if(finish==='nonfoil') assert(visual.textContent.includes('Nonfoil'));
            assert.equal(JSON.stringify(item),before);
          }
          const any=shopPrintingMeta(row('Any',{finish:'foil'})); assert(any.textContent.includes('Any printing'));
          assert.equal(any.querySelector('.shop-exact-tag'),null);
          assert(shopPrintingMeta(row('Older',{finish:'unrecognised finish'})).querySelector('.shop-printing-visual').textContent.includes('unrecognised finish'));
        """)

    def test_queue_buttons_have_concise_names_and_viewer_caption_keeps_full_saved_evidence(self):
        self.run_js("""
          const item=row('Alpha',{quantity:2,for:'Otters',state:'deferred',printing:'exact',set:'fdn',collector_number:'7',finish:'foil',
            listed_at:'Shop',checked:'2026-10-24',in_stock:'no',notes:'Compare the saved printing before ordering'});
          drawShopping({...empty,to_buy:[item]}); const trigger=entry().querySelector('.card-row');
          assert.equal(trigger.getAttribute('aria-label'),'Alpha, 2 copies');
          const group=viewerGroup(trigger), caption=group.items[0].caption;
          for(const text of ['For Otters','Deferred','Requested printing: Exact: FDN 7 foil','Reference price not recorded',
            'Recorded check date: 2026-10-24','Out of stock when checked',item.notes]) assert(caption.includes(text));
          assert(entry().querySelector('.shop-queue-research').querySelector('.fresh'));
          assert(!trigger.getAttribute('aria-label').includes('Shop'));
          assert(!main.textContent.includes('live stock available')); assert.equal(group.items.length,1);
        """)

    def test_zero_reference_price_is_retained_and_date_is_not_borrowed_from_other_metadata(self):
        self.run_js("""
          const priced=row('Alpha',{listed_aud:'0',listed_at:'Shop',checked:'',in_stock:'yes',reprints:{cache_date:'2026-10-24'}});
          const reference=shopReference(priced); assert(reference.textContent.includes('Reference price A$0.00 at Shop'));
          assert(reference.textContent.includes('Check date not recorded')); assert.equal(reference.querySelector('.fresh'),null);
          const research=shopQueueResearch(row('Beta',{checked:'2026-10-24',listed_aud:'',in_stock:''}));
          assert(research.querySelector('.fresh')); assert(research.textContent.includes('Reference price not recorded'));
          assert(research.textContent.includes('Stock not recorded')); assert(!research.textContent.includes('A$'));
        """)

    def test_density_changes_keep_viewer_controls_intent_and_raw_lab_date(self):
        self.run_js("""
          const item=row('Alpha',{finish:'etched',checked:'2026-10-24',notes:'Keep this note'}), before=JSON.stringify(item);
          const view=drawShopping({...empty,to_buy:[item]}), trigger=entry().querySelector('.card-row'),
            button=main.querySelector('.shop-queue-edit'), chip=trigger.querySelector('.chip-foil');
          density(true); assert(entry().querySelector('.card-row')===trigger); assert(main.querySelector('.shop-queue-edit')===button);
          assert.equal(entry().querySelector('.shop-q-checked').textContent,'2026-10-24');
          assert.equal(entry().querySelector('.shop-q-checked').querySelector('time').getAttribute('datetime'),'2026-10-24');
          density(false); assert(trigger.querySelector('.chip-foil')===chip);
          assert.equal(trigger.getAttribute('aria-label'),'Alpha, 1 copy'); assert.equal(viewerGroup(trigger).items.length,1);
          assert.equal(JSON.stringify(item),before); assert.equal(view.data.queue_revision,'q1');
        """)

    def test_readonly_unknown_rows_keep_metadata_without_new_actions_colors_or_reads(self):
        self.run_js("""
          state.may.orders=false;
          drawShopping({...empty,to_buy:[row('Unknown',{card:null,finish:'foil',checked:'2026-10-24',deck:{id:'casual/visible',title:'Visible'}})]});
          assert.equal(main.querySelectorAll('.shop-queue-write').length,0);
          assert.equal(main.querySelectorAll('[data-viewer]').length,0);
          assert(entry().querySelector('.chip-foil')); assert(entry().querySelector('.fresh'));
          assert.equal(main.querySelector('.deck-swatch'),null);
          assert.equal(main.querySelector('.shop-queue-deck').getAttribute('href'),'#/deck?id=casual%2Fvisible&v=target');
        """)
