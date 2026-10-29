"""Loaded receipt destination evidence agrees before and after recording the frozen selection."""
import unittest

from decklab.tests import test_receipts_ui as board


@unittest.skipUnless(board.NODE, "Node.js isn't installed")
class ReceiptDestinationTests(unittest.TestCase):
    run_js = board.ReceiptBoardTests.run_js

    def test_unavailable_rows_and_basic_lands_never_become_known_storage_after_recording(self):
        self.run_js("""
          const cases=[{decks:null},{decks:[]},{decks:[null]},
            {decks:[[{id:'casual/a',title:'Bad waiting',waiting:-1}]]},
            {decks:[[{id:'casual/a',title:'Bad waiting',waiting:1.5}]]},
            {decks:[[{id:null,title:'Bad identity',waiting:1}]]},
            {decks:[[]],name:'Forest',why:'basic'}];
          for(const item of cases){
            clear(main);const d=delivery();d.components[0].rows=d.components[0].rows.slice(0,1);
            d.components[0].decks=item.decks;if(item.name)d.components[0].rows[0].name=item.name;
            const v=drawReceipt(d,routeToken),comp=v.comps[0];rcptTick(v,comp,comp.rows[0],true);
            const received=rcptReceived(v),advice=rcptDestinationAdvice(v,received);
            same(advice.map(a=>[a.kind,a.name,a.quantity,a.why]),[['unknown',item.name||'Alpha',2,item.why||'unavailable']]);
            const post=add(el('div',{}),rcptWhereTheyGo(v,received));
            assert(!post.textContent.includes('To storage'));assert.equal(post.querySelectorAll('a').length,0);
            assert(post.textContent.includes('2 \u00d7 '+(item.name||'Alpha')),post.textContent);
            assert(item.why==='basic'?/not tracked/i.test(post.textContent):/not known|unavailable/i.test(post.textContent));
            const pre=add(el('ul',{}),rcptGuidanceDestinations(v));
            assert(!pre.textContent.includes('storage'));
          }
          clear(main);const d=delivery();d.components[0].rows=d.components[0].rows.slice(0,1);d.components[0].decks=[[]];
          const v=drawReceipt(d,routeToken);rcptTick(v,v.comps[0],v.comps[0].rows[0],true);const received=rcptReceived(v);
          same(rcptDestinationAdvice(v,received).map(a=>[a.kind,a.name,a.quantity]),[['storage','Alpha',2]]);
          const pre=add(el('ul',{}),rcptGuidanceDestinations(v)),post=add(el('div',{}),rcptWhereTheyGo(v,received));
          assert(pre.textContent.includes('2 \u00d7 Alpha: storage'));assert(post.textContent.includes('To storage'));
          assert(post.textContent.includes('2 \u00d7 Alpha'));assert(!/not known|unavailable/i.test(post.textContent));
        """, draw=False)

    def test_split_and_printing_rows_share_each_deck_waiting_cap_and_pre_post_confidence(self):
        self.run_js("""
          const d=delivery(),c=d.components[0];c.checks=[];c.rows[0].quantity='3';
          c.rows[1]={...c.rows[0],collector_number:'3',quantity:'2',condition:'NM',language:'en',notes:''};
          const built={id:'casual/a',title:'Alpha Deck',status:'built',waiting:2},building={id:'casual/b',title:'Building Deck',status:'building',waiting:1};
          c.decks=[[built,building],[{...built,waiting:1},{...building}]];
          const v=drawReceipt(d,routeToken),comp=v.comps[0];rcptSplit(v,comp,comp.rows[0],1);comp.rows.forEach(r=>r.ticked=true);rcptSync(v);
          const received=rcptReceived(v),advice=rcptDestinationAdvice(v,received);
          same(advice.map(a=>[a.kind,a.name,a.quantity,a.deck?.id??null]),
            [['deck','Alpha',2,'casual/a'],['deck','Alpha',1,'casual/b'],['storage','Alpha',2,null]]);
          const pre=add(el('ul',{}),rcptGuidanceDestinations(v)),post=add(el('div',{}),rcptWhereTheyGo(v,received));
          assert(pre.textContent.includes('2 \u00d7 Alpha: Alpha Deck'));assert(pre.textContent.includes('1 \u00d7 Alpha: Building Deck'));
          assert(pre.textContent.includes('2 \u00d7 Alpha: storage'));assert(pre.textContent.includes('Black matte'));
          const panels=post.querySelectorAll('.rcpt-where');
          const deck=panels.find(p=>p.querySelector('a')?.textContent==='Alpha Deck');assert(deck.textContent.includes('2 \u00d7 Alpha'));
          assert(deck.textContent.includes('Black matte'));
          const pending=panels.find(p=>p.querySelector('a')?.textContent==='Building Deck');assert(pending.textContent.includes('1 \u00d7 Alpha'));
          const storage=panels.find(p=>p.querySelector('h3').textContent==='To storage');assert(storage.textContent.includes('2 \u00d7 Alpha'));
          assert.equal(advice.reduce((n,a)=>n+a.quantity,0),5);assert(!post.textContent.includes('not known'));
        """, draw=False)

    def test_component_caps_remain_separate_and_only_selected_checked_copies_are_projected(self):
        self.run_js("""
          const d=delivery(),first=d.components[0];first.checks=[];first.rows=first.rows.slice(0,1);first.rows[0].quantity='3';
          const deck={id:'casual/a',title:'Alpha Deck',status:'built',waiting:1};first.decks=[[deck]];
          d.components.push({...first,id:'cards-2',rows:[{...first.rows[0],quantity:'2'}],decks:[[{...deck}]]});
          d.components.push({...first,id:'later',rows:[{...first.rows[0],name:'Private untaken card',quantity:'99'}],
            decks:[[{id:'casual/private',title:'Private untaken deck',status:'built',waiting:99}]]});
          const v=drawReceipt(d,routeToken);v.comps[0].selected=true;v.comps[1].selected=true;rcptDrawBoard(v);
          rcptSplit(v,v.comps[0],v.comps[0].rows[0],1);rcptTick(v,v.comps[0],v.comps[0].rows.find(r=>r.values.quantity==='1'),true);
          rcptTick(v,v.comps[1],v.comps[1].rows[0],true);v.comps[2].rows[0].ticked=true;
          const received=rcptReceived(v),advice=rcptDestinationAdvice(v,received);
          same(advice.map(a=>[a.kind,a.quantity]),[['deck',1],['deck',1],['storage',1]]);
          assert.equal(advice.reduce((n,a)=>n+a.quantity,0),3);assert.equal(received.length,2);
          const post=add(el('div',{}),rcptWhereTheyGo(v,received));
          assert(!post.textContent.includes('Private'));assert(!post.textContent.includes('99'));
        """, draw=False)

    def test_destination_projection_and_both_renderers_read_nothing_and_mutate_no_canonical_values(self):
        self.run_js("""
          const comp=view.comps[0];comp.checks=[true];rcptTick(view,comp,comp.rows[1],true);
          state.library={decks:[{id:'casual/private',title:'Cached private deck',colors:['R']}]};
          const received=rcptReceived(view),plain=items=>items.map(c=>({id:c.c.id,kind:c.kind,intact:c.intact,
            decks:c.decks,rows:c.rows.map(r=>({orig:r.orig,values:r.values,ticked:r.ticked}))}));
          const before=JSON.stringify({data:view.data,request:rcptRequest(view),received:plain(received),board:plain(view.comps)});
          const calls=[];api=async p=>{calls.push(p);throw new Error('no reads');};apiWrite=async p=>{calls.push(p);throw new Error('no writes');};
          window.localStorage.setItem=()=>{throw new Error('no draft write from advice');};
          const advice=rcptDestinationAdvice(view,received),pre=add(el('ul',{}),rcptGuidanceDestinations(view));
          const post=add(el('div',{}),rcptWhereTheyGo(view,received));
          same(advice.map(a=>[a.kind,a.name,a.quantity]),[['storage','Beta',1]]);same(calls,[]);
          assert.equal(JSON.stringify({data:view.data,request:rcptRequest(view),received:plain(received),board:plain(view.comps)}),before);
          assert(!pre.textContent.includes('Cached private'));assert(!post.textContent.includes('Cached private'));
          assert(!pre.querySelector('.deck-swatch'));assert(!post.querySelector('.deck-swatch'));
          assert(!post.textContent.includes('Alpha'));
        """)

    def test_partial_apply_uses_reviewed_rows_and_metadata_after_later_board_edits(self):
        self.run_js("""
          const d=delivery();d.components[0].rows[0].quantity='3';d.components[0].decks=null;
          d.components.push({...d.components[0],id:'later',rows:[{...d.components[0].rows[1],name:'Unselected card',quantity:'80'}]});
          const v=drawReceipt(d,routeToken),comp=v.comps[0];comp.selected=true;comp.checks=[true];rcptDrawBoard(v);
          rcptSplit(v,comp,comp.rows[0],1);const picked=comp.rows.find(r=>r.values.quantity==='1');rcptTick(v,comp,picked,true);
          const partial={...ready,assignments:[{source:'cards',received:'cards-2',pending:'cards',received_quantity:1,pending_quantity:3}],
            totals:[['playable cards',{cards:1,added_rows:1,bumped_rows:0}]]};
          const calls=[];apiWrite=async(p,b)=>{calls.push([p,b]);return partial;};await previewDelivery(v);
          same(calls[0][1].components[0].take,[{row:2}]);assert.equal(calls[0][1].components.length,1);
          assert.equal(v.preview.received[0].rows.length,1);assert.equal(v.preview.received[0].rows[0].values.quantity,'1');
          const token=v.preview.token;let finish;apiWrite=(p,b)=>{calls.push([p,b]);return new Promise(resolve=>finish=resolve);};
          const saving=applyDelivery(v);picked.values.name='Later board mutation';picked.values.quantity='99';
          comp.rows[2].ticked=true;comp.decks=[[{id:'casual/later',title:'Later deck mutation',status:'built',waiting:99}]];
          v.comps[1].selected=true;v.comps[1].rows[0].ticked=true;
          finish({received:true,assignments:partial.assignments,remaining:[{id:'cards',kind:'cards',quantity:3}],
            totals:partial.totals,tables:{written:[],skipped:[],error:null}});await saving;
          same(calls[1],['/api/receipt/apply',{profile:'matt',preview:token}]);assert(v.done);
          const text=main.textContent;assert(text.includes('1 \u00d7 Alpha'));assert(/not known|unavailable/i.test(text));
          assert(!text.includes('To storage'));assert(!text.includes('Later board mutation'));assert(!text.includes('Later deck mutation'));
          assert(!text.includes('Beta'));assert(!text.includes('Unselected card'));
          assert(text.includes('Unticked cards are still pending'));assert.equal(v.received.length,1);
          same(rcptDestinationAdvice(v,v.received).map(a=>[a.kind,a.name,a.quantity,a.why]),[['unknown','Alpha',1,'unavailable']]);
        """, draw=False)

    def test_received_tokens_and_product_kind_choice_are_frozen_independently_of_the_board(self):
        self.run_js("""
          const d=delivery();d.components=[{id:'tokens',kind:'tokens',status:'pending',checks:[],fields:""" + board.TOKEN_FIELDS + """,
            rows:[{front:'Bird',back:'Golem',set:'tx',front_collector_number:'1',back_collector_number:'2',finish:'nonfoil',
              quantity:'4',front_details:'',back_details:'',notes:''}],pictures:[],decks:[]},
            {id:'kit',kind:'product',status:'pending',checks:[],fields:[],rows:[],product:{name:'Whole fixture'},
              items:[{name:'Alpha',set:'tst',collector_number:'1',finish:'nonfoil',quantity:'60',section:'deck'}],pictures:[],decks:[]}];
          const v=drawReceipt(d,routeToken),tokens=v.comps[0],product=v.comps[1];tokens.selected=true;product.selected=true;
          product.intact='yes';rcptDrawBoard(v);rcptTick(v,tokens,tokens.rows[0],true);
          const request=rcptRequest(v);same(request.components[1],{id:'kit',verified:false,intact:'yes'});
          const received=rcptReceived(v);tokens.rows[0].values.quantity='99';tokens.rows[0].values.front='Changed token';
          tokens.kind='cards';product.kind='cards';product.intact='no';product.rows[0].values.quantity='99';
          const advice=rcptDestinationAdvice(v,received);same(advice.map(a=>[a.kind,a.quantity??null,a.comp?.intact??null]),
            [['tokens',4,null],['product',null,'yes']]);
          const post=add(el('div',{}),rcptWhereTheyGo(v,received));
          assert(post.textContent.includes('4 token cards'));assert(post.textContent.includes('Kept as its own deck(s)'));
          assert(!post.textContent.includes('Broken up'));assert(!post.textContent.includes('99'));assert(!post.textContent.includes('Changed token'));
          assert.equal(post.querySelectorAll('a').find(a=>a.textContent.includes('Tokens')).getAttribute('href'),'#/tokens');
        """, draw=False)

    def test_unknown_whole_product_choice_is_not_rendered_as_a_broken_up_product(self):
        self.run_js("""
          const d=delivery();d.components=[{id:'kit',kind:'product',status:'pending',checks:[],fields:[],rows:[],
            product:{name:'Whole fixture'},items:[{name:'Alpha',set:'tst',collector_number:'1',finish:'nonfoil',quantity:'60',section:'deck'}],pictures:[],decks:[]}];
          const v=drawReceipt(d,routeToken),received=rcptReceived(v);
          assert.equal(received[0].intact,'');same(rcptDestinationAdvice(v,received).map(a=>a.kind),['product']);
          const pre=add(el('ul',{}),rcptGuidanceDestinations(v)),post=add(el('div',{}),rcptWhereTheyGo(v,received));
          assert(pre.textContent.includes('choose whether'));assert(!post.textContent.includes('Broken up'));
          assert(!post.textContent.includes('storage box'));assert(/not recorded|not known|choose/i.test(post.textContent));
        """, draw=False)

    def test_a_late_apply_never_places_destination_panels_into_another_profile(self):
        self.run_js("""
          const comp=view.comps[0];comp.decks=null;comp.checks=[true];rcptTick(view,comp,comp.rows[1],true);
          apiWrite=async()=>ready;await previewDelivery(view);let finish;
          apiWrite=()=>new Promise(resolve=>finish=resolve);const saving=applyDelivery(view);
          state.profile={id:'user2',name:'User2'};routeToken++;clear(main).append(el('p',{text:'Another profile'}));
          state.library={cached:true};closeReceiptSheets();finish({received:true,totals:ready.totals,tables:{written:[],skipped:[],error:null}});
          await saving;assert.equal(main.textContent,'Another profile');assert.equal(state.library,null);
          assert(!main.querySelector('.rcpt-where'));assert(!body().includes('Arrival recorded'));assert(!document.body.querySelector('dialog'));
        """)

    def test_each_deck_says_ready_to_build_or_still_to_get_from_apply_readiness(self):
        # E6-S26: apply's readiness, the refreshed tables' Planned counts after the receipt.
        self.run_js("""
          const d=delivery(),c=d.components[0];c.checks=[];c.rows=c.rows.slice(0,1);c.rows[0].quantity='4';
          const decks=[{id:'casual/a',title:'Alpha Deck',status:'building',waiting:1},{id:'casual/b',title:'Beta Deck',status:'idea',waiting:1},
            {id:'casual/c',title:'Gamma Deck',status:'built',waiting:1},{id:'casual/d',title:'Delta Deck',status:'idea',waiting:1}];
          c.decks=[decks];const v=drawReceipt(d,routeToken),comp=v.comps[0];rcptTick(v,comp,comp.rows[0],true);
          const received=rcptReceived(v);
          const readiness={'casual/a':{missing:0,coming:0},'casual/b':{missing:3,coming:2},'casual/c':{missing:0,coming:0},
            'casual/d':{missing:-1,coming:0}};
          const post=add(el('div',{}),rcptWhereTheyGo(v,received,readiness));
          const panel=(t)=>post.querySelectorAll('.rcpt-where').find(p=>p.querySelector('a')?.textContent===t);
          const a=panel('Alpha Deck').querySelector('.rcpt-where-ready')?.querySelector('a');assert.equal(a.textContent,'Ready to build');
          assert.equal(a.getAttribute('href'),'#/assembly?deck=casual%2Fa');
          assert(panel('Beta Deck').textContent.includes('Still 3 to get · 2 cards on the way'));
          assert(!panel('Beta Deck').querySelector('.rcpt-where-ready')?.querySelector('a'));
          assert(panel('Gamma Deck').querySelector('.rcpt-where-ready')?.querySelector('a').textContent.includes('Every card is here'));
          assert(!panel('Delta Deck').querySelector('.rcpt-where-ready'));     // a bad count says nothing
          const plain=add(el('div',{}),rcptWhereTheyGo(v,received,{'casual/a':{missing:0,coming:1}}));
          assert(plain.textContent.includes('Ready once 1 card arrives'));
          // No readiness (a viewer without home's inventory, or an older answer): no counts at all.
          for(const none of [undefined,{},null]){const bare=add(el('div',{}),rcptWhereTheyGo(v,received,none));
            assert(!bare.querySelector('.rcpt-where-ready'));assert(!/Ready|to get/.test(bare.textContent));}
        """, draw=False)

    def test_the_recorded_page_draws_readiness_from_the_apply_answer(self):
        self.run_js("""
          tickAll(view);apiWrite=async()=>ready;await previewDelivery(view);
          apiWrite=async()=>({received:true,totals:ready.totals,tables:{written:[{id:'casual/a',title:'Alpha Deck'}],skipped:[],error:null},
            readiness:{'casual/a':{missing:2,coming:0}}});
          await applyDelivery(view);
          assert(main.textContent.includes('Still 2 to get'),main.textContent);
        """)
