"""Receipt Pictures use one native label without consuming inspection, scope or guarded editing."""
import re
import unittest

from decklab.tests import test_receipts_ui as board


@unittest.skipUnless(board.NODE, "Node.js isn't installed")
class ReceiptPicturesTests(unittest.TestCase):
    run_js = board.ReceiptBoardTests.run_js

    def test_native_label_checks_once_and_keeps_inspection_sibling_and_shared_defaults(self):
        self.run_js("""
          const comp=view.comps[0],row=comp.rows[0],label=row.tile.querySelector('.card-tile'),input=row.tile.querySelector('.rcpt-tick');
          assert(row.tile.getAttribute('class').includes('rcpt-check-tile'));assert.equal(label.tag,'label');
          assert.equal(input.tag,'input');assert.equal(input.getAttribute('type'),'checkbox');assert(label.contains(input));
          assert.equal(input.getAttribute('aria-pressed'),null);assert(input.getAttribute('aria-label').includes('Alpha'));
          assert(input.getAttribute('aria-label').includes('2'));assert(input.getAttribute('aria-label').length<90);
          assert.equal(row.tile.querySelectorAll('input').length,1);assert.equal(label.querySelector('.card-tile-open').tag,'span');
          for(const tag of ['button','a','select','textarea','div','label'])assert.equal(label.querySelectorAll(tag).length,0);
          assert.equal(row.open.tag,'button');assert(row.open.getAttribute('class').includes('rcpt-picture-inspect'));
          assert(!label.contains(row.open));assert.equal(label.parentNode,row.open.parentNode);
          assert.equal((label.events.get('click')||[]).length,0);assert.equal((label.querySelector('.card-tile-open').events.get('click')||[]).length,0);
          const tick=rcptTick;let calls=0;rcptTick=(...args)=>{calls++;return tick(...args);};
          label.click();label.querySelector('.card-tile-open').click();assert.equal(calls,0,'the DOM double has no native label activation');
          input.checked=true;input.fire('change');assert.equal(calls,1);assert(row.ticked);assert(!view.sheet);
          assert.notEqual(row.tile.querySelector('.rcpt-tick').getAttribute('checked'),null);
          const done=row.tile.querySelector('.rcpt-picture-done');assert(done);assert.equal(done.tag,'span');
          assert.equal(done.getAttribute('aria-hidden'),'true');assert.equal((done.events.get('click')||[]).length,0);
          assert.equal(row.tile.querySelectorAll('.rcpt-tick').length,1);assert.equal(row.tile.querySelectorAll('.rcpt-picture-done').length,1);
          const checked=row.tile.querySelector('.rcpt-tick');checked.checked=false;checked.fire('change');
          assert.equal(calls,2);assert(!row.tile.querySelector('.rcpt-picture-done'));
          const plain=cardTile(alphaCard,{state:el('button',{type:'button',class:'fixture-state',text:'State'})});
          assert.equal(plain.tag,'div');assert.equal(plain.querySelector('.card-tile-open').tag,'button');
          assert.equal(plain.querySelector('.fixture-state').tag,'button');assert(!plain.querySelector('input'));
          assert(!plain.querySelector('.card-tile-open').contains(plain.querySelector('.fixture-state')));
          // Off parts, readers and whole products retain their existing viewer-only tile contract.
          clear(main);const offData=delivery();offData.components.push({...delivery().components[0],id:'later'});
          const off=drawReceipt(offData,routeToken);assert(off.comps.every(c=>!c.selected));assert(!main.querySelector('.rcpt-tick'));
          off.comps[0].rows[0].open.click();assert.equal(inspections.length,1);assert(!off.sheet);
          clear(main);state.may={admin:false,receipts:false};const reader=drawReceipt(delivery(),routeToken);
          assert(reader.readOnly);assert(!main.querySelector('.rcpt-tick'));assert(!main.querySelector('.rcpt-picture-inspect'));
          assert(main.querySelector('.card-tile'));state.may=null;clear(main);
          const d=delivery();d.components=[{id:'kit',kind:'product',status:'pending',checks:[],fields:[],rows:[],
            product:{name:'Whole fixture'},items:[{name:'Alpha',set:'tst',collector_number:'1',finish:'nonfoil',quantity:'60',section:'deck'}],pictures:[],decks:[]}];
          const product=drawReceipt(d,routeToken);assert(main.querySelector('.card-tile'));assert(!main.querySelector('.rcpt-tick'));
          assert(!main.querySelector('.rcpt-picture-inspect'));same(rcptRequest(product).components,[{id:'kit',verified:false}]);
        """)

    def test_inspect_and_viewer_never_check_or_change_the_reviewed_partial_request_and_close_focus_is_fresh(self):
        self.run_js("""
          const comp=view.comps[0],row=comp.rows[1];comp.checks=comp.checks.map(()=>true);
          const input=row.tile.querySelector('.rcpt-tick');input.checked=true;input.fire('change');
          const calls=[];apiWrite=async(path,payload)=>{calls.push([path,payload]);return ready;};
          await previewDelivery(view);assert(view.preview);closeReceiptSheets();
          const preview=view.preview,request=rcptRequestKey(view),rows=JSON.stringify(comp.rows.map(r=>r.values));
          const key='decklab.receipt:matt:test:'+'a'.repeat(64),draft=window.localStorage.getItem(key),oldOpen=row.open;
          oldOpen.click();assert(view.sheet);assert.equal(view.sheet.row,row);assert(row.ticked);assert(!comp.rows[0].ticked);
          let viewer=null;openCardViewer=(items,start,opts)=>{viewer={items,start,opts};};
          const picture=document.body.querySelector('.rcpt-sheet-pic');picture.click();assert(viewer);
          assert.equal(viewer.items.length,2);assert.equal(viewer.start,1);assert.equal(viewer.opts.trigger,picture);
          assert.equal(viewer.items[0].card.name,'Alpha');assert.equal(viewer.items[1].card.name,'Beta');
          rcptRefreshTile(view,comp,row);assert.notEqual(row.open,oldOpen);closeReceiptSheets();
          assert.equal(document.activeElement,row.open);assert(row.open.isConnected);assert.equal(view.preview,preview);
          assert.equal(rcptRequestKey(view),request);assert.equal(JSON.stringify(comp.rows.map(r=>r.values)),rows);
          assert.equal(window.localStorage.getItem(key),draft);assert.equal(calls.length,1);
          same(calls[0][1].components[0].take,[{row:2}]);assert.equal(calls[0][1].components[0].rows.length,2);
          view.layout='list';rcptRefreshAll(view);assert.equal(row.tile.querySelector('.rcpt-tick').tag,'input');
          assert(row.tile.getAttribute('class').includes('rcpt-row'));assert(!row.tile.querySelector('.rcpt-picture-inspect'));
          assert.equal(rcptRequestKey(view),request);assert.equal(view.preview,preview);
        """)

    def test_native_picture_checks_and_unchecks_follow_todo_and_ticked_focus_without_changing_layout(self):
        self.run_js("""
          const comp=view.comps[0];rcptSetFilter(view,'todo');
          const change=(row,value)=>{const input=row.tile.querySelector('.rcpt-tick');input.focus();input.checked=value;input.fire('change');};
          change(comp.rows[0],true);assert(comp.rows[0].tile.hidden);
          assert.equal(document.activeElement,comp.rows[1].tile.querySelector('.rcpt-tick'));
          change(comp.rows[1],true);assert(comp.rows[1].tile.hidden);
          let show=comp.grid.querySelector('.rcpt-none').querySelector('button');assert.equal(document.activeElement,show);show.click();
          assert.equal(view.filter,'all');assert(comp.rows.every(r=>r.ticked&&!r.tile.hidden));rcptSetFilter(view,'ticked');
          change(comp.rows[0],false);assert(comp.rows[0].tile.hidden);
          assert.equal(document.activeElement,comp.rows[1].tile.querySelector('.rcpt-tick'));
          change(comp.rows[1],false);show=comp.grid.querySelector('.rcpt-none').querySelector('button');
          assert.equal(document.activeElement,show);assert.equal(comp.grid.querySelector('.rcpt-none').querySelector('p').textContent,'Nothing here is checked yet.');
          show.click();assert(comp.rows.every(r=>!r.ticked&&!r.tile.hidden));assert.equal(view.layout,'pictures');
          same(rcptRequest(view).components[0].take,[]);
        """)

    def test_denied_native_changes_restore_accepted_state_without_drafts_writes_or_inspection(self):
        self.run_js("""
          const expire=[v=>receiptBusy(v,true),v=>{state.profile={id:'user2'};},v=>{routeToken++;},
            v=>{state.may={admin:false,receipts:false};},v=>{v.done=true;},v=>{v.reloadRequired=true;}];
          for(const end of expire){
            clear(main);state.profile={id:'matt'};state.may=null;const v=drawReceipt(delivery(),routeToken),row=v.comps[0].rows[0];
            const input=row.tile.querySelector('.rcpt-tick'),request=rcptRequestKey(v),values=JSON.stringify(row.values);
            const key='decklab.receipt:matt:test:'+'a'.repeat(64),draft=window.localStorage.getItem(key);let writes=0;
            apiWrite=async()=>{writes++;return ready;};end(v);input.checked=true;input.fire('change');row.open.click();
            await previewDelivery(v);await applyDelivery(v);assert(!row.ticked);assert.equal(input.checked,false);assert(!v.sheet);
            assert.equal(rcptRequestKey(v),request);assert.equal(JSON.stringify(row.values),values);
            assert.equal(window.localStorage.getItem(key),draft);assert.equal(writes,0);
          }
          clear(main);state.profile={id:'matt'};state.may=null;const v=drawReceipt(delivery(),routeToken),comp=v.comps[0],row=comp.rows[0];
          const captured=row.tile.querySelector('.rcpt-tick'),inspect=row.open,values=JSON.stringify(row.values);
          comp.selected=false;rcptDrawGrid(v,comp);captured.checked=true;captured.fire('change');inspect.click();
          assert(!row.ticked);assert.equal(captured.checked,false);assert(!v.sheet);assert(!row.tile.querySelector('.rcpt-tick'));
          assert.equal(JSON.stringify(row.values),values);same(rcptRequest(v).components,[]);
        """,draw=False)

    def test_unknown_attention_and_token_split_descriptions_resolve_and_keep_one_check_per_part(self):
        self.run_js("""
          const descriptions=control=>{const ids=(control.getAttribute('aria-describedby')||'').split(/\\s+/).filter(Boolean);
            assert(ids.length);return ids.map(id=>{const node=document.getElementById(id);assert(node,`Missing description ${id}`);return node.textContent;}).join(' ');};
          const comp=view.comps[0],row=comp.rows[0];row.values.finish='foil';row.values.notes='Inspect signed card';
          row.pic={...comp.pictures[0],exact:false,why:'not recorded'};rcptRefreshAll(view);
          for(const control of [row.open,row.tile.querySelector('.rcpt-tick')]){
            const text=descriptions(control);assert(text.includes('Condition not recorded'));assert(text.includes('Language not recorded'));
            for(const words of rcptAttention(view,comp,row))assert(text.includes(words),text);
          }
          const canonical=rcptRequestKey(view);row.open.click();assert(view.sheet);closeReceiptSheets();assert.equal(rcptRequestKey(view),canonical);
          row.pic={card:{...alphaCard,img:null,img_small:null},exact:false,why:'no picture'};rcptRefreshAll(view);
          const missing=row.tile.querySelector('.rcpt-tick');missing.checked=true;missing.fire('change');
          assert(row.ticked);assert(!row.tile.querySelector('.rcpt-picture-done'));assert(row.tile.textContent.includes('Alpha'));
          clear(main);const d=delivery();d.components=[{id:'tokens',kind:'tokens',status:'pending',checks:[],fields:""" + board.TOKEN_FIELDS + """,
            rows:[{front:'Bird',back:'Golem',set:'tx',front_collector_number:'1',back_collector_number:'2',finish:'nonfoil',quantity:'3',
              front_details:'1/1; flying',back_details:'3/3',notes:'reverse face unconfirmed'}],
            pictures:[{img:'/img/tx/1/normal',img_small:'/img/tx/1/small',back_img:'/img/tx/2/normal',back_img_small:'/img/tx/2/small',exact:true,why:null}],decks:[]}];
          const v=drawReceipt(d,routeToken),tokens=v.comps[0];rcptSplit(v,tokens,tokens.rows[0],1);
          const ids=new Set();for(const [index,part] of tokens.rows.entries()){
            assert.equal(part.tile.getAttribute('data-row'),String(part.key));assert.equal(part.tile.querySelectorAll('.rcpt-tick').length,1);
            const label=part.tile.querySelector('.card-tile');assert.equal(label.tag,'label');assert(!label.querySelector('button'));
            assert(label.querySelector('.card-tile-back'));assert.equal(label.querySelector('.card-tile-back').getAttribute('src'),'/img/tx/2/small');
            for(const control of [part.open,part.tile.querySelector('.rcpt-tick')]){
              const text=descriptions(control);assert(text.includes('back not confirmed'));assert(text.includes(`Part ${index+1} of 2`));assert(/still pending/i.test(text));
              for(const id of control.getAttribute('aria-describedby').split(/\\s+/))ids.add(id);
            }
            assert(part.tile.querySelector('.rcpt-pending-swatch'));
          }
          assert.equal(tokens.rows[0].orig,tokens.rows[1].orig);assert.notEqual(tokens.rows[0].key,tokens.rows[1].key);
          assert(ids.size>=4);const one=tokens.rows.find(r=>r.values.quantity==='1'),input=one.tile.querySelector('.rcpt-tick');
          input.checked=true;input.fire('change');assert(!one.tile.querySelector('.rcpt-pending-swatch'));
          const pending=tokens.rows.find(r=>!r.ticked);assert(pending.tile.querySelector('.rcpt-pending-swatch'));
          assert(/still pending/i.test(descriptions(pending.tile.querySelector('.rcpt-tick'))));
          const sent=rcptRequest(v).components[0];same(sent.take,[{row:2}]);
          same(sent.rows.map(r=>[r.front,r.back,r.quantity]),[['Bird','Golem','2'],['Bird','Golem','1']]);
          assert(rcptClientBlockers(v).some(b=>b.text.includes('back')));
        """)


class ReceiptPicturesCssTests(unittest.TestCase):
    def test_picture_checkbox_targets_and_focus_are_native_without_changing_list_or_other_tiles(self):
        shared = re.sub(r"/\*.*?\*/", "", (board.WEB / "cards-ui.css").read_text(encoding="utf-8"), flags=re.S)
        receipt = re.sub(r"/\*.*?\*/", "", (board.WEB / "receipts.css").read_text(encoding="utf-8"), flags=re.S)
        self.assertIn("button.card-tile-open:focus-visible", shared)
        self.assertRegex(receipt, r"\.rcpt-picture-tick\s*\{[^}]*appearance:\s*auto;[^}]*width:\s*28px;\s*height:\s*28px;[^}]*accent-color:\s*var\(--accent\)")
        self.assertRegex(receipt, r"\.rcpt-grid\s+\.rcpt-picture-label\s*>\s*\.card-tile-state\s*\{[^}]*min-width:\s*52px;\s*min-height:\s*52px")
        self.assertRegex(receipt, r"\.rcpt-picture-inspect\s*\{[^}]*min-height:\s*44px")
        self.assertRegex(receipt, r"@media[^\{]*\(min-width:\s*1000px\)[^\{]*\{\s*\.rcpt-grid\s+\.rcpt-picture-label\s*>\s*\.card-tile-state\s*\{[^}]*min-width:\s*44px;\s*min-height:\s*44px")
        self.assertRegex(receipt, r"@media[^\{]*\(min-width:\s*1000px\)[^\{]*\{[^}]*\}\s*\.rcpt-picture-tick\s*\{\s*width:\s*18px;\s*height:\s*18px")
        pending = re.search(r"\.rcpt-check-tile\.is-pending-split\s*>\s*\.rcpt-picture-label\s*\{[^}]*dashed var\(--accent-line\)", receipt)
        focus = re.search(r"\.rcpt-check-tile\s*>\s*\.rcpt-picture-label:focus-within\s*\{[^}]*3px solid var\(--focus\)", receipt)
        self.assertIsNotNone(pending)
        self.assertIsNotNone(focus)
        self.assertGreater(focus.start(), pending.start())
        self.assertRegex(receipt, r"\.rcpt-picture-pending\s+\.rcpt-pending-swatch\s*\{[^}]*repeating-linear-gradient")
        self.assertRegex(receipt, r"\.rcpt-tick-cell\s*\{[^}]*min-height:\s*44px")
        self.assertRegex(receipt, r"\.rcpt-picture-label\s+\.rcpt-picture-done\s*\{\s*display:\s*none")
        casual = receipt.index("@media (max-width: 999px)")
        self.assertGreater(casual, receipt.index("filter: brightness(.7)"))
        self.assertRegex(receipt[casual:], r"\.rcpt-grid\s+\.rcpt-picture-label\.is-ticked\s+\.card-tile-back\s*\{\s*opacity:\s*\.42;\s*filter:\s*none")
        self.assertRegex(receipt[casual:], r"\.card-tile-pic:has\(> :is\(\.card-tile-img, \.card-tile-back\)\)\s*>\s*\.rcpt-picture-done\s*\{[^}]*width:\s*40px;\s*height:\s*40px;[^}]*pointer-events:\s*none")


if __name__ == "__main__":
    unittest.main()
