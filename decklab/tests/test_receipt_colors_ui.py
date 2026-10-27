"""Receipt destination swatches decorate only explicit Planned identity from loaded metadata."""
import unittest

from decklab.tests import test_receipts_ui as board


@unittest.skipUnless(board.NODE, "Node.js isn't installed")
class ReceiptColorsTests(unittest.TestCase):
    run_js = board.ReceiptBoardTests.run_js

    def test_strict_optional_identity_keeps_links_and_words_without_cache_or_card_color_fallback(self):
        self.run_js("""
          state.library={decks:[{id:'casual/a',title:'Cached deck',colors:['R']}]};let reads=0,writes=0;
          api=async()=>{reads++;throw new Error('No swatch reads');};apiWrite=async()=>{writes++;throw new Error('No swatch writes');};
          const valid=[['G'],['G','U'],[],['W','U','B','R','G']];
          for(const colors of valid){
            const deck={id:'casual/a',title:'Fixture <deck>',colors},before=JSON.stringify(deck),swatch=rcptDeckSwatch(deck);
            assert(swatch);assert.equal(swatch.getAttribute('class'),'deck-swatch');assert.equal(swatch.getAttribute('aria-hidden'),'true');
            assert.equal(swatch.textContent,'');assert.equal(swatch.getAttribute('style'),deckColourPieces(colors).swatch().getAttribute('style'));
            const link=rcptDeckLink(deck);assert.equal(link.tag,'a');assert.equal(link.getAttribute('href'),'#/deck?id=casual%2Fa&v=target');
            assert.equal(link.textContent,'Fixture <deck>');assert.equal(link.querySelectorAll('.deck-swatch').length,1);
            assert.equal(link.querySelector('span').getAttribute('aria-hidden'),'true');assert.equal(link.querySelector('deck'),null);
            assert.equal(JSON.stringify(deck),before);
          }
          const malformed=[undefined,null,'G',{},['g'],['C'],['GU'],['G','G'],['W','U','B','R','G','W'],['G',null],['G',1],new Array(1)];
          for(const colors of malformed){
            const deck={id:'casual/a',title:'Unknown identity',colors};assert.equal(rcptDeckSwatch(deck),null);
            const link=rcptDeckLink(deck);assert.equal(link.textContent,'Unknown identity');assert.equal(link.getAttribute('href'),'#/deck?id=casual%2Fa&v=target');
            assert(!link.querySelector('.deck-swatch'));assert(!link.textContent.includes('Colourless'));
          }
          assert.equal(reads,0);assert.equal(writes,0);
        """)

    def test_pre_and_frozen_post_keep_destination_quantities_unknowns_basics_tokens_and_whole_products(self):
        self.run_js("""
          const d=delivery(),c=d.components[0];c.checks=[];c.rows[0].quantity='3';c.rows[1].quantity='2';
          c.rows.push({...c.rows[1],name:'Forest',quantity:'4'},{...c.rows[1],name:'Gamma',quantity:'5'});
          const green={id:'casual/a',title:'Green Deck',status:'built',uses:3,waiting:2,colors:['G']};
          c.decks=[[green],[],[],null];
          d.components.push({...c,id:'later',rows:[{...c.rows[0],name:'Untaken card',quantity:'99'}],
            decks:[[{id:'casual/private',title:'Untaken deck',status:'built',uses:99,waiting:99,colors:['R']}]]});
          d.components.push({id:'tokens',kind:'tokens',status:'pending',checks:[],fields:""" + board.TOKEN_FIELDS + """,
            rows:[{front:'Bird',back:'Golem',set:'tx',front_collector_number:'1',back_collector_number:'2',finish:'nonfoil',quantity:'4',
              front_details:'',back_details:'',notes:''}],pictures:[],decks:[]});
          d.components.push({id:'kit',kind:'product',status:'pending',checks:[],fields:[],rows:[],product:{name:'Whole fixture'},
            items:[{name:'Alpha',set:'tst',collector_number:'1',finish:'nonfoil',quantity:'60',section:'deck'}],pictures:[],decks:[]});
          const v=drawReceipt(d,routeToken);for(const i of [0,2,3])v.comps[i].selected=true;v.comps[3].intact='yes';rcptDrawBoard(v);
          for(const part of [v.comps[0],v.comps[2]])for(const row of part.rows)rcptTick(v,part,row,true);
          v.comps[1].rows[0].ticked=true;const received=rcptReceived(v),advice=rcptDestinationAdvice(v,received);
          same(advice.map(a=>[a.kind,a.name??null,a.quantity??null,a.why??null]),
            [['deck','Alpha',2,null],['storage','Alpha',1,null],['storage','Beta',2,null],['unknown','Forest',4,'basic'],
              ['unknown','Gamma',5,'unavailable'],['tokens',null,4,null],['product',null,null,null]]);
          assert.equal(advice[0].deck,green);const pre=add(el('ul',{}),rcptGuidanceDestinations(v));
          assert.equal(pre.querySelectorAll('.deck-swatch').length,1);assert(pre.textContent.includes('2 \u00d7 Alpha: Green Deck'));
          v.comps[0].decks=[[{...green,title:'Later deck',colors:['R'],waiting:99}]];
          v.comps[0].rows[0].values.quantity='99';v.comps[3].intact='no';
          const post=add(el('div',{}),rcptWhereTheyGo(v,received));assert.equal(post.querySelectorAll('.deck-swatch').length,1);
          const link=post.querySelectorAll('a').find(a=>a.textContent==='Green Deck');assert(link);
          assert.equal(link.querySelector('.deck-swatch').getAttribute('style'),pre.querySelector('.deck-swatch').getAttribute('style'));
          assert.equal(link.getAttribute('href'),'#/deck?id=casual%2Fa&v=target');
          for(const words of ['2 \u00d7 Alpha','1 \u00d7 Alpha','2 \u00d7 Beta','4 \u00d7 Forest','5 \u00d7 Gamma','4 token cards','Kept as its own deck(s)'])assert(post.textContent.includes(words),post.textContent);
          assert(post.querySelector('.rcpt-where-basics'));assert(post.querySelector('.rcpt-where-unknown'));
          for(const words of ['Later deck','Untaken deck','Untaken card','99','Broken up'])assert(!post.textContent.includes(words));
          assert.equal(rcptDestinationAdvice(v,received)[0].deck,green);
        """,draw=False)

    def test_named_row_chips_stay_plain_phrasing_and_inspection_keeps_target_links_and_names(self):
        self.run_js("""
          const d=delivery(),c=d.components[0];
          const mixed={id:'casual/a',title:'Alpha Deck',status:'built',uses:2,waiting:1,colors:['G','U']};
          const colorless={id:'casual/c',title:'Colorless Deck',status:'building',uses:2,waiting:0,colors:[]};
          const unknown={id:'casual/unknown',title:'Unknown Deck',status:'built',uses:1,waiting:0,colors:['g']};
          c.decks=[[mixed],[colorless,unknown]];const v=drawReceipt(d,routeToken),comp=v.comps[0];
          const first=comp.rows[0],second=comp.rows[1],label=first.tile.querySelector('.card-tile');
          assert.equal(label.tag,'label');assert.equal(label.querySelectorAll('a').length,0);assert.equal(label.querySelectorAll('button').length,0);
          const waiting=label.querySelectorAll('.chip').find(n=>n.textContent==='For Alpha Deck \u00d71');assert(waiting);
          assert.equal(waiting.tag,'span');assert(waiting.querySelector('.deck-swatch'));
          const chips=second.tile.querySelectorAll('.rcpt-deck-chip');assert.equal(chips.length,1);
          assert.equal(chips[0].textContent,'In 2 decks: Colorless Deck \u00d72, Unknown Deck \u00d71');
          assert.equal(chips[0].getAttribute('title'),'Colorless Deck lists 2\\nUnknown Deck lists 1');
          assert(!chips[0].querySelector('.deck-swatch'));assert.equal(first.tile.querySelectorAll('input').length,1);
          assert.equal(first.tile.querySelector('.rcpt-tick').getAttribute('aria-label'),'Check off 2 copies of Alpha');
          first.open.click();assert(v.sheet);let links=v.sheet.sheet.body.querySelector('.rcpt-decks').querySelectorAll('a');
          assert.equal(links.length,1);assert.equal(links[0].textContent,'Alpha Deck');assert.equal(links[0].getAttribute('href'),'#/deck?id=casual%2Fa&v=target');
          assert(links[0].querySelector('.deck-swatch'));assert(!first.ticked);closeReceiptSheets();second.open.click();
          links=v.sheet.sheet.body.querySelector('.rcpt-decks').querySelectorAll('a');assert.equal(links.length,2);
          assert(links.find(a=>a.textContent==='Colorless Deck').querySelector('.deck-swatch'));
          assert(!links.find(a=>a.textContent==='Unknown Deck').querySelector('.deck-swatch'));assert(!second.ticked);
        """,draw=False)

    def test_a_row_several_decks_wait_for_is_one_chip_and_inspect_names_them(self):
        self.run_js("""
          const d=delivery(),c=d.components[0];
          const deck=(id,title,waiting)=>({id:'casual/'+id,title,status:'built',uses:4,waiting,colors:['B']});
          c.decks=[[deck('a','Alpha Deck',1)],[deck('b','Mono-Black Midrange',3),deck('c','Orzhov Removal: Midrange',2),deck('z','Zombies',1)]];
          const v=drawReceipt(d,routeToken),row=v.comps[0].rows[1];
          const chips=row.tile.querySelectorAll('.rcpt-deck-chip');assert.equal(chips.length,1);
          assert(chips[0].getAttribute('class').includes('chip-info'));
          assert(chips[0].textContent.startsWith('For 3 decks'));assert(chips[0].textContent.includes('Orzhov Removal \u00d72'));
          assert.equal(chips[0].getAttribute('title').split('\\n').length,3);
          row.open.click();assert.equal(v.sheet.sheet.body.querySelector('.rcpt-decks').querySelectorAll('a').length,3);
        """,draw=False)

    def test_decoration_never_changes_canonical_rows_draft_or_preview_and_performs_no_new_requests(self):
        self.run_js("""
          const d=delivery();d.components[0].decks[0][0].colors=['G'];
          d.components[0].decks[1]=[{id:'casual/b',title:'Blue Green Deck',status:'building',uses:1,waiting:1,colors:['U','G']}];
          const v=drawReceipt(d,routeToken),comp=v.comps[0];comp.checks=[true];rcptTick(v,comp,comp.rows[1],true);
          const key='decklab.receipt:matt:test:'+'a'.repeat(64),draft=window.localStorage.getItem(key),request=rcptRequestKey(v);
          const data=JSON.stringify(v.data),rows=JSON.stringify(comp.rows.map(r=>r.values));let reads=0;const writes=[];
          api=async()=>{reads++;throw new Error('No new reads');};apiWrite=async(path,payload)=>{writes.push([path,payload]);return ready;};
          rcptRefreshAll(v);rcptSyncLayout(v,rcptProgress(v));const frozen=rcptReceived(v);
          add(el('ul',{}),rcptGuidanceDestinations(v));add(el('div',{}),rcptWhereTheyGo(v,frozen));
          comp.rows[1].open.click();closeReceiptSheets();assert.equal(reads,0);assert.equal(writes.length,0);
          assert.equal(rcptRequestKey(v),request);assert.equal(JSON.stringify(v.data),data);assert.equal(JSON.stringify(comp.rows.map(r=>r.values)),rows);
          assert.equal(window.localStorage.getItem(key),draft);await previewDelivery(v);assert(v.preview);
          assert.equal(writes.length,1);assert.equal(writes[0][0],'/api/receipt/preview');same(writes[0][1].components[0].take,[{row:2}]);
          assert(writes[0][1].components[0].rows.every(r=>!Object.hasOwn(r,'colors')));
          const preview=v.preview;rcptSetFilter(v,'ticked');rcptRefreshAll(v);rcptSyncLayout(v,rcptProgress(v));
          assert.equal(v.preview,preview);assert.equal(v.preview.key,request);assert.equal(rcptRequestKey(v),request);
          assert.equal(JSON.stringify(v.data),data);assert.equal(reads,0);assert.equal(writes.length,1);
        """,draw=False)


if __name__ == "__main__":
    unittest.main()
