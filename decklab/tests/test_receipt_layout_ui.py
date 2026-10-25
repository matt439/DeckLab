"""Receive's presentation frame uses existing checked data and leaves recording guarded."""
import re
import unittest

from decklab.tests import test_receipts_ui as board


@unittest.skipUnless(board.NODE, "Node.js isn't installed")
class ReceiptLayoutTests(unittest.TestCase):
    run_js = board.ReceiptBoardTests.run_js

    def test_order_head_counts_selected_copies_including_splits_and_keeps_products_separate(self):
        self.run_js("""
          const d=delivery();d.components[0].rows[0].quantity='7';
          d.components.push({id:'tokens',kind:'tokens',status:'pending',checks:[],fields:""" + board.TOKEN_FIELDS + """,
            rows:[{front:'Bird',back:'',set:'tx',front_collector_number:'1',back_collector_number:'',finish:'nonfoil',
              quantity:'5',front_details:'',back_details:'',notes:'single-sided verified'}],pictures:[],decks:[]});
          d.components.push({id:'kit',kind:'product',status:'pending',checks:[],fields:[],rows:[],
            product:{name:'Fixture deck'},items:[{name:'Alpha',set:'tst',collector_number:'1',finish:'nonfoil',quantity:'60',section:'deck'}],
            pictures:[],decks:[]});
          const v=drawReceipt(d,routeToken),cards=v.comps[0],tokens=v.comps[1],product=v.comps[2];
          assert(v.headProgress.textContent.includes('Select the parts'));
          assert(main.querySelector('.rcpt-order-meta').textContent.includes('Order test'));
          const date=main.querySelector('.rcpt-order-meta').querySelector('time');
          assert.equal(date.getAttribute('datetime'),'2026-10-01');assert(date.textContent.includes('1 Oct 2026'));
          assert(main.querySelector('a').getAttribute('href').includes('shopping'));
          cards.selected=true;product.selected=true;rcptDrawBoard(v);rcptTick(v,cards,cards.rows[0],true);
          assert(v.headProgress.textContent.includes('7 of 8 card copies checked'));
          assert(v.headProgress.textContent.includes('1 whole product selected separately'));
          assert(!v.headProgress.textContent.includes('68'));
          rcptSplit(v,cards,cards.rows[0],3);cards.rows.forEach(r=>r.ticked=false);
          rcptTick(v,cards,cards.rows.find(r=>r.values.quantity==='4'),true);
          assert(v.headProgress.textContent.includes('4 of 8 card copies checked'));
          tokens.selected=true;rcptDrawBoard(v);rcptTick(v,tokens,tokens.rows[0],true);
          assert(v.headProgress.textContent.includes('9 of 13 card copies checked'));
          assert.equal(rcptProgress(v).ticked,9);assert.equal(rcptProgress(v).copies,13);
          assert.equal(v.root.querySelectorAll('.action-bar').length,1);assert.equal(v.bar.node.parentNode,v.root);
          assert(v.bar.node.isConnected);assert(v.bar.node.classList.contains('rcpt-bar'));
        """, draw=False)

    def test_destination_caps_share_a_name_across_split_printings_and_exclude_unselected_copies(self):
        self.run_js("""
          const d=delivery(),c=d.components[0];c.checks=[];
          c.rows[0].quantity='3';c.rows[1]={...c.rows[0],collector_number:'3',quantity:'2',condition:'NM',language:'en',notes:''};
          const deck={id:'casual/a',title:'Alpha Deck',status:'built',uses:2,waiting:2};c.decks=[[deck],[{...deck}]];
          d.components.push({...c,id:'later',rows:[{...c.rows[0],name:'Unticked private fixture',quantity:'99'}],
            decks:[[{id:'casual/later',title:'Unselected deck',status:'building',waiting:99}]]});
          const v=drawReceipt(d,routeToken),comp=v.comps[0];comp.selected=true;rcptDrawBoard(v);
          rcptSplit(v,comp,comp.rows[0],1);comp.rows.forEach(r=>r.ticked=true);v.comps[1].rows[0].ticked=true;
          const before=JSON.stringify({request:rcptRequest(v),data:d,values:v.comps.map(c=>c.rows.map(r=>r.values))});
          const calls=[];api=async p=>{calls.push(p);throw new Error('no reads');};apiWrite=async p=>{calls.push(p);throw new Error('no writes');};
          rcptSyncLayout(v,rcptProgress(v));
          const items=v.guidance.querySelector('.rcpt-guidance-destinations').querySelectorAll('li');
          assert.equal(items.length,2);assert(items[0].textContent.includes('2 × Alpha: Alpha Deck'));
          assert(items[1].textContent.includes('3 × Alpha: storage'));
          assert(items[0].textContent.includes('Black matte'));
          assert(!v.guidance.textContent.includes('Unselected deck'));assert(!v.guidance.textContent.includes('Unticked private fixture'));
          same(calls,[]);assert.equal(JSON.stringify({request:rcptRequest(v),data:d,values:v.comps.map(c=>c.rows.map(r=>r.values))}),before);
          assert(v.guidance.textContent.includes('loaded deck needs'));assert(v.guidance.textContent.includes('nothing is recorded before confirmation'));
          assert(!v.guidance.querySelector('.deck-swatch'));
          assert(v.guidance.querySelector('a').getAttribute('href').includes('casual%2Fa'));
        """, draw=False)

    def test_unknown_destinations_never_become_storage_but_known_empty_metadata_does(self):
        self.run_js("""
          const cases=[null,[],[null],[[{id:'casual/a',title:'Bad waiting',waiting:-1}]],
            [[{id:'casual/a',title:'Bad waiting',waiting:1.5}]],[[{id:null,title:'Bad identity',waiting:1}]]];
          for(const decks of cases){
            clear(main);const d=delivery();d.components[0].rows=d.components[0].rows.slice(0,1);d.components[0].decks=decks;
            const v=drawReceipt(d,routeToken),comp=v.comps[0];rcptTick(v,comp,comp.rows[0],true);
            const where=v.guidance.querySelector('.rcpt-guidance-where');
            assert(where.textContent.includes('destination not known'),JSON.stringify(decks));
            assert(!where.textContent.includes('storage'));assert.equal(where.querySelectorAll('a').length,0);
          }
          clear(main);const d=delivery();d.components[0].rows=d.components[0].rows.slice(0,1);d.components[0].decks=[[]];
          const v=drawReceipt(d,routeToken);rcptTick(v,v.comps[0],v.comps[0].rows[0],true);
          const where=v.guidance.querySelector('.rcpt-guidance-where');
          assert(where.textContent.includes('2 × Alpha: storage'));assert(!where.textContent.includes('destination not known'));
          clear(main);const basic=delivery();basic.components[0].rows=basic.components[0].rows.slice(0,1);
          basic.components[0].rows[0].name='Forest';basic.components[0].decks=[[]];
          const b=drawReceipt(basic,routeToken);rcptTick(b,b.comps[0],b.comps[0].rows[0],true);
          const basicWhere=b.guidance.querySelector('.rcpt-guidance-where');
          assert(basicWhere.textContent.includes('basic-land deck destinations are not tracked'));
          assert(!basicWhere.textContent.includes('storage'));
        """, draw=False)

    def test_tokens_and_whole_product_choices_are_guidance_without_row_receipts(self):
        self.run_js("""
          const d=delivery();d.components=[{id:'tokens',kind:'tokens',status:'pending',checks:[],fields:""" + board.TOKEN_FIELDS + """,
            rows:[{front:'Bird',back:'',set:'tx',front_collector_number:'1',back_collector_number:'',finish:'nonfoil',
              quantity:'4',front_details:'',back_details:'',notes:'single-sided verified'}],pictures:[],decks:[]},
            {id:'kit',kind:'product',status:'pending',checks:[],fields:[],rows:[],product:{name:'Whole fixture'},
              items:[{name:'Alpha',set:'tst',collector_number:'1',finish:'nonfoil',quantity:'60',section:'deck'}],pictures:[],decks:[]}];
          const v=drawReceipt(d,routeToken),tokens=v.comps[0],product=v.comps[1];
          tokens.selected=true;product.selected=true;rcptDrawBoard(v);rcptTick(v,tokens,tokens.rows[0],true);
          const where=()=>v.guidance.querySelector('.rcpt-guidance-where').textContent;
          assert(where().includes('4 token card copies: with your tokens'));
          assert(where().includes('choose whether to keep it together or break it up'));
          assert(!where().includes('Whole fixture (product): break up into storage'));
          product.intact='yes';rcptSync(v);assert(where().includes('keep together as its own deck(s)'));
          product.intact='no';rcptSync(v);assert(where().includes('break up into storage'));
          const request=rcptRequest(v).components.find(c=>c.id==='kit');
          same(request,{id:'kit',verified:false,intact:'no'});assert(!Object.hasOwn(request,'rows'));assert(!Object.hasOwn(request,'take'));
        """, draw=False)

    def test_read_only_and_completed_orders_never_claim_checked_progress_or_add_guidance_controls(self):
        self.run_js("""
          state.may={admin:false,receipts:false};const d=delivery();d.components[0].rows[0].quantity='7';
          const v=drawReceipt(d,routeToken);assert(v.readOnly);
          assert(v.headProgress.textContent.includes('8 card copies in this order'));
          assert(!v.headProgress.textContent.includes('checked'));assert(!main.querySelector('.rcpt-guidance'));
          assert(!main.querySelector('.action-bar'));assert(!main.querySelector('.rcpt-tick'));
          let writes=0;apiWrite=async()=>{writes++;return ready;};await previewDelivery(v);await applyDelivery(v);assert.equal(writes,0);
          clear(main);state.may=null;const done=delivery();done.components[0].status='received';done.components[0].received_on='2026-10-07';
          const finished=drawReceipt(done,routeToken);assert(finished.headProgress.textContent.includes('No pending parts'));
          assert(!main.querySelector('.rcpt-guidance'));assert(!main.querySelector('.action-bar'));
          assert(main.textContent.includes('Everything in this order has arrived'));
        """, draw=False)

    def test_the_only_action_bar_keeps_exact_preview_confirmation_and_apply_payloads(self):
        self.run_js("""
          const comp=view.comps[0];comp.checks=[true];rcptTick(view,comp,comp.rows[1],true);
          assert.equal(view.root.querySelectorAll('.action-bar').length,1);assert.equal(view.bar.node.parentNode,view.root);
          assert(view.bar.node.isConnected);assert(view.bar.node.classList.contains('rcpt-bar'));
          assert.equal(view.guidance.querySelectorAll('.btn-primary').length,0);
          const calls=[];apiWrite=async(path,b)=>{calls.push([path,b]);return ready;};
          await previewDelivery(view);assert.equal(calls.length,1);assert(!view.done);
          assert.equal(calls[0][0],'/api/receipt/preview');const sent=calls[0][1];
          assert.equal(sent.profile,'matt');assert.equal(sent.order,'test');assert.equal(sent.fingerprint,'a'.repeat(64));
          assert.equal(sent.received_on,'2026-10-08');same(sent.components[0].take,[{row:2}]);assert.equal(sent.components[0].rows.length,2);
          assert(!JSON.stringify(sent).includes('guidance'));assert(!JSON.stringify(sent).includes('Alpha Deck'));
          assert(view.previewSheet.foot.querySelectorAll('button').some(b=>b.textContent==='Record arrival'));
          const token=view.preview.token,oldGuidance=view.guidance;apiWrite=async(path,b)=>{calls.push([path,b]);return {received:true,
            totals:ready.totals,tables:{written:[],skipped:[],error:null}};};
          await applyDelivery(view);same(calls[1],['/api/receipt/apply',{profile:'matt',preview:token}]);
          assert(view.done);assert(!oldGuidance.isConnected);assert(!main.querySelector('.rcpt-guidance'));
          const success=main.textContent;rcptSyncLayout(view,{copies:999,ticked:999,blanks:999});assert.equal(main.textContent,success);
          await applyDelivery(view);assert.equal(calls.length,2);
        """)

    def test_retained_guidance_buttons_and_late_preview_cannot_cross_a_profile_or_route(self):
        self.run_js("""
          const retained=view.guidance.querySelector('.rcpt-blocker'),before=rcptRequestKey(view);
          const original=rcptGoTo;let visits=0;rcptGoTo=()=>{visits++;};retained.click();assert.equal(visits,1);
          state.profile={id:'user1',name:'User1'};retained.click();assert.equal(visits,1);assert.equal(rcptRequestKey(view),before);
          const oldHead=view.headProgress.textContent,oldAdvice=view.guidance.textContent;
          rcptSyncLayout(view,{copies:99,ticked:99,blanks:0});assert.equal(view.headProgress.textContent,oldHead);
          assert.equal(view.guidance.textContent,oldAdvice);rcptGoTo=original;state.profile={id:'matt',name:'Matt'};
          tickAll(view);let finish;apiWrite=()=>new Promise(resolve=>{finish=resolve;});const preparing=previewDelivery(view);
          state.profile={id:'user2',name:'User2'};routeToken++;clear(main).append(el('p',{text:'Another profile page'}));
          finish(ready);await preparing;assert.equal(main.textContent,'Another profile page');assert.equal(view.preview,null);
          assert(!main.querySelector('.rcpt-guidance'));assert(!body().includes('Record arrival'));
        """)

    def test_conflict_removes_stale_destination_guidance_until_authoritative_reload(self):
        self.run_js("""
          tickAll(view);assert(view.guidance.textContent.includes('Alpha Deck'));
          apiWrite=async()=>ready;await previewDelivery(view);
          apiWrite=async()=>{throw new ApiError(409,'Fixture changed');};await applyDelivery(view);
          assert(view.reloadRequired);assert.equal(view.preview,null);assert(view.primary.disabled);
          assert(view.guidance.textContent.includes('Reload it before using destination guidance'));
          assert(!view.guidance.textContent.includes('Alpha Deck'));assert(!view.guidance.querySelector('a'));
          let writes=0;apiWrite=async()=>{writes++;return ready;};await previewDelivery(view);await applyDelivery(view);assert.equal(writes,0);
        """)


    def test_guidance_clearance_tracks_the_actual_resized_record_bar(self):
        self.run_js("""
          const observers=[];
          window.ResizeObserver=class {
            constructor(callback){this.callback=callback;this.disconnected=false;observers.push(this);}
            observe(target){this.target=target;}
            disconnect(){this.disconnected=true;}
          };
          const v=drawReceipt(delivery(),routeToken),observer=observers[0];
          assert.equal(observers.length,1);assert.equal(observer.target,v.bar.node);
          v.bar.node.box.height=98.36;observer.callback();assert.equal(v.root.style['--rcpt-bar-height'],'99px');
          v.bar.node.box.height=74;observer.callback();assert.equal(v.root.style['--rcpt-bar-height'],'74px');
          v.bar.node.box.height=NaN;observer.callback();assert.equal(v.root.style['--rcpt-bar-height'],'74px');
          v.bar.node.box.height=0;observer.callback();assert.equal(v.root.style['--rcpt-bar-height'],'74px');
          v.bar.node.box.height=120;rcptSync(v);assert.equal(v.root.style['--rcpt-bar-height'],'120px');
          rcptWatchBar(v);assert.equal(observers.length,1);assert(!observer.disconnected);
        """,draw=False)

    def test_bar_observer_disconnects_when_its_receipt_is_stale_detached_or_done(self):
        self.run_js("""
          const observers=[];
          window.ResizeObserver=class {
            constructor(callback){this.callback=callback;this.disconnected=false;observers.push(this);}
            observe(target){this.target=target;}
            disconnect(){this.disconnected=true;}
          };
          for(const expire of [v=>{routeToken++;},v=>{state.profile={id:'user2'};},v=>{v.root.remove();},v=>{v.done=true;}]){
            clear(main);state.profile={id:'matt'};
            const v=drawReceipt(delivery(),routeToken),observer=observers.at(-1),before=v.root.style['--rcpt-bar-height'];
            expire(v);v.bar.node.box.height=999;observer.callback();
            assert(observer.disconnected);assert.equal(v.root.style['--rcpt-bar-height'],before);
          }
        """,draw=False)

class ReceiptLayoutCssTests(unittest.TestCase):
    def test_lab_aside_has_452px_only_at_lab_width_and_scrolls_without_hiding_the_action_bar(self):
        css = re.sub(r"/\*.*?\*/", "", (board.WEB / "receipts.css").read_text(encoding="utf-8"), flags=re.S)
        start = re.search(r"@media\s*\(min-width:\s*1000px\)\s*\{", css)
        self.assertIsNotNone(start)
        depth, end = 1, start.end()
        while depth and end < len(css):
            depth += (css[end] == "{") - (css[end] == "}")
            end += 1
        lab = css[start.end():end - 1]
        self.assertRegex(lab, r"\.rcpt-layout-frame\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+452px")
        self.assertNotIn("452px", css[:start.start()] + css[end:])
        aside = re.search(r"\.rcpt-guidance\s*\{([^}]+)\}", lab).group(1)
        self.assertIn("position: sticky", aside)
        self.assertIn("overflow-y: auto", aside)
        self.assertIn("overscroll-behavior: contain", aside)
        self.assertRegex(aside, r"scroll-margin-bottom:[^;]+--rcpt-bar-height")
        self.assertRegex(aside, r"max-height:\s*calc\(100dvh[^;]+--bar-h")
        self.assertRegex(css, r"\.rcpt-layout-frame\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)")
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            if ".rcpt-bar" in selector:
                self.assertNotRegex(body, r"display:\s*none|visibility:\s*hidden")
