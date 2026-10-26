"""Optional Planned deck swatches use only the current Shopping answer's validated metadata."""
import unittest

from decklab.tests import test_shopping_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingColorsInteractionTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js

    def run_colors_js(self, scenario):
        self.run_js("""
          state.may={admin:false,orders:true,see_inventory:['home']};
          const picture={name:'Alpha',type_line:'Creature',mana_cost:'',img:'/img/test/1/normal',img_small:'/img/test/1/small',color_identity:['R']};
          const deck=(colors, extra={})=>({id:'casual/otters',title:'Otters',colors,...extra});
          const qrow=(n,extra={})=>row('Alpha '+n,{queue_row:n,card:{...picture,name:'Alpha '+n},...extra});
          const data=(rows,extra={})=>({...empty,to_buy:rows,queue_revision:'q1',queue_decks:[],...extra});
          const density=lab=>{const query=window.matchMedia(SHOP_QUEUE_LAB);query.matches=lab;query.fire('change')};
          const entry=n=>main.querySelectorAll('[data-shop-queue]').find(node=>Number(node.getAttribute('data-shop-queue'))===n);
          const settle=async()=>{for(let i=0;i<8;i++)await Promise.resolve()};
          api=()=>{throw new Error('No extra reads')}; apiWrite=()=>{throw new Error('No writes')}; toast=()=>{};
        """ + scenario)

    def test_optional_colors_distinguish_known_colorless_from_invalid_or_absent(self):
        self.run_colors_js("""
          const colors=['G','U'], before=JSON.stringify(colors), swatch=shopDeckSwatch(deck(colors));
          assert(swatch); assert.equal(swatch.getAttribute('aria-hidden'),'true');
          const style=swatch.getAttribute('style'); assert(style.indexOf('stripe-u')<style.indexOf('stripe-g'));
          assert.equal(JSON.stringify(colors),before);
          assert(shopDeckSwatch(deck([])).getAttribute('style').includes('stripe-c'));
          for(const colors of [null,undefined,'GU',['C'],['g'],['G','bad'],[1],{},false])
            assert.equal(shopDeckSwatch(deck(colors)),null);
        """)

    def test_casual_and_lab_share_the_same_deck_link_swatch_controls_and_names(self):
        self.run_colors_js("""
          const item=qrow(1,{deck:deck(['U','G'])}), before=JSON.stringify(item);
          drawShopping(data([item])); const link=entry(1).querySelector('.shop-queue-deck'),
            swatch=link.querySelector('.deck-swatch'), trigger=entry(1).querySelector('.card-row'), button=main.querySelector('.shop-queue-edit');
          assert.equal(link.textContent,'Otters'); assert.equal(link.getAttribute('href'),'#/deck?id=casual%2Fotters&v=target');
          assert(swatch); link.focus(); density(true);
          assert(entry(1).querySelector('.shop-queue-deck')===link && link.querySelector('.deck-swatch')===swatch);
          assert(document.activeElement===link); assert(main.querySelector('.shop-queue-edit')===button);
          density(false); assert(entry(1).querySelector('.card-row')===trigger); assert.equal(viewerGroup(trigger).items.length,1);
          assert.equal(main.querySelectorAll('.deck-swatch').length,1); assert.equal(JSON.stringify(item),before);
        """)

    def test_unknown_older_or_unlinked_decks_never_borrow_card_or_library_colors(self):
        self.run_colors_js("""
          state.library=[{id:'casual/otters',title:'Otters',colors:['R']}];
          drawShopping(data([qrow(1,{deck:{id:'casual/otters',title:'Otters'}}),qrow(2,{deck:deck(null)}),
            qrow(3,{deck:null,for:'one of the home decks'}),qrow(4,{deck:deck([],{id:'casual/colorless',title:'Colorless'})})]));
          for(const n of [1,2,3]) assert.equal(entry(n).querySelector('.deck-swatch'),null);
          assert(entry(4).querySelector('.deck-swatch').getAttribute('style').includes('stripe-c'));
          assert.equal(entry(3).querySelector('.shop-queue-deck'),null);
          assert.equal(main.querySelectorAll('.deck-swatch').length,1);
          assert.equal(entry(1).querySelector('.shop-queue-deck').textContent,'Otters');
        """)

    def test_longterm_matching_reveal_keeps_one_authoritative_heading_swatch(self):
        self.run_colors_js("""
          const rows=Array.from({length:14},(_,i)=>qrow(i+1,{state:'long_term',deck:deck(['U']),listed_at:i===13?'Chosen':'Other'}));
          const view=drawShopping(data(rows)), group=main.querySelector('[data-long-key]'), swatch=group.querySelector('.deck-swatch');
          assert(swatch); assert.equal(main.querySelectorAll('[data-shop-queue]').length,12);
          const radio=main.querySelectorAll('.shop-store-radio').find(node=>node.value==='shop:Chosen');radio.checked=true;radio.fire('change');
          assert.equal(main.querySelectorAll('[data-shop-queue]').length,14); assert(group.querySelector('.deck-swatch')===swatch);
          density(true); density(false); assert.equal(main.querySelectorAll('.deck-swatch').length,1);
          assert.equal(main.querySelectorAll('[data-shop-match=true]').length,1); assert.equal(view.data.queue_revision,'q1');
        """)

    def test_added_row_uses_current_queue_choices_without_sending_colors_or_using_library_cache(self):
        self.run_colors_js("""
          const selected=deck(['G']), writes=[]; state.library=[deck(['R'])];
          const view=drawShopping(data([],{queue_decks:[selected]})), sheet=shopQueueSheet(view);
          apiWrite=async(path,body)=>{writes.push(body);return {revision:'q2',item:{name:'Alpha',quantity:1,state:'ready',for:'Otters',
            source:'magic/decks/casual/otters.md',printing:'any',set:'',collector_number:'',finish:'nonfoil',notes:''}}};
          await shopSaveQueue(view,sheet,sheet.queueError,{action:'add',values:{name:'Alpha',quantity:1}},null);
          const link=entry(1).querySelector('.shop-queue-deck'); assert(link.querySelector('.deck-swatch').getAttribute('style').includes('stripe-g'));
          assert(!link.querySelector('.deck-swatch').getAttribute('style').includes('stripe-r'));
          assert.equal(writes[0].expect,'q1'); assert(!JSON.stringify(writes[0]).includes('colors'));
          assert(view.data.to_buy[0].deck===selected); assert.equal(view.data.queue_revision,'q2');
        """)

    def test_readonly_named_rows_keep_route_and_decorative_swatch_without_write_controls(self):
        self.run_colors_js("""
          state.may.orders=false; drawShopping(data([qrow(1,{deck:deck(['W','B'])})]));
          assert.equal(main.querySelectorAll('.shop-queue-write').length,0);
          const link=entry(1).querySelector('.shop-queue-deck'); assert.equal(link.textContent,'Otters');
          assert.equal(link.querySelector('.deck-swatch').getAttribute('aria-hidden'),'true');
          assert.equal(link.querySelector('button'),null); assert.equal(entry(1).querySelectorAll('.deck-swatch').length,1);
        """)
