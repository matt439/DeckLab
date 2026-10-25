"""Compact receipt List rows retain native checking, guarded inspection and canonical receipt scope."""
import re
import unittest

from decklab.tests import test_receipts_ui as board


@unittest.skipUnless(board.NODE, "Node.js isn't installed")
class ReceiptCompactTests(unittest.TestCase):
    run_js = board.ReceiptBoardTests.run_js

    def test_shared_compact_option_is_opt_in_and_keeps_default_card_rows_and_picture_preference(self):
        self.run_js("""
          const plain=cardRow(alphaCard,{qty:2,meta:'Ordinary metadata'});
          const compact=cardRow(alphaCard,{qty:2,meta:'Compact metadata',compact:true});
          assert.equal(plain.getAttribute('class'),'card-row');assert(compact.getAttribute('class').includes('card-row-compact'));
          assert.equal(plain.tag,'button');assert.equal(compact.tag,'button');
          assert.equal(plain.querySelector('.thumb').getAttribute('width'),'40');
          assert.equal(plain.querySelector('.thumb').getAttribute('height'),'56');assert(plain.textContent.includes('Ordinary metadata'));
          assert.equal(view.layout,'pictures');assert(view.comps[0].rows[0].tile.getAttribute('class').includes('card-tile'));
          assert.equal(view.comps[0].rows[0].tile.querySelector('.rcpt-tick').tag,'button');
          assert.equal(view.comps[0].rows[0].tile.querySelector('.rcpt-tick').getAttribute('aria-pressed'),'false');
        """)

    def test_native_change_ticks_once_and_the_separate_inspection_button_contains_no_controls(self):
        self.run_js("""
          view.layout='list';rcptRefreshAll(view);const comp=view.comps[0],row=comp.rows[0],input=row.tile.querySelector('.rcpt-tick');
          assert.equal(input.tag,'input');assert.equal(input.getAttribute('type'),'checkbox');
          assert.equal(input.getAttribute('aria-pressed'),null);assert(input.getAttribute('aria-label').includes('Alpha'));
          assert.equal(input.parentNode.tag,'label');assert.equal(row.tile.children[0],input.parentNode);
          assert(!input.parentNode.contains(row.open));assert(!row.open.contains(input));
          for(const tag of ['input','button','select','textarea','a'])assert.equal(row.open.querySelectorAll(tag).length,0);
          assert.equal(row.tile.querySelectorAll('.rcpt-tick').length,1);
          const original=rcptTick;let calls=0;rcptTick=(...args)=>{calls++;return original(...args);};
          input.click();assert.equal(calls,0,'the DOM double does not perform native default activation');
          input.checked=true;input.fire('change');assert.equal(calls,1);assert(row.ticked);assert(!view.sheet);
          assert.notEqual(row.tile.querySelector('.rcpt-tick').getAttribute('checked'),null);
          row.open.click();assert(view.sheet);assert.equal(view.sheet.row,row);assert.equal(calls,1);
          closeReceiptSheets();assert.equal(document.activeElement,row.open);
          const current=row.tile.querySelector('.rcpt-tick');current.checked=false;current.fire('change');
          assert.equal(calls,2);assert(!row.ticked);assert.equal(row.tile.querySelector('.rcpt-tick').getAttribute('checked'),null);
        """)

    def test_native_check_under_todo_moves_focus_to_the_next_input_then_show_all(self):
        self.run_js("""
          view.layout='list';view.filter='todo';rcptRefreshAll(view);const comp=view.comps[0];
          const first=comp.rows[0].tile.querySelector('.rcpt-tick');first.focus();first.checked=true;first.fire('change');
          assert(comp.rows[0].tile.hidden);const next=comp.rows[1].tile.querySelector('.rcpt-tick');
          assert.equal(document.activeElement,next);assert.equal(next.tag,'input');
          next.checked=true;next.fire('change');assert(comp.rows[1].tile.hidden);
          const show=comp.grid.querySelector('.rcpt-none').querySelector('button');assert.equal(document.activeElement,show);
          show.click();assert.equal(view.filter,'all');assert(comp.rows.every(r=>!r.tile.hidden));
          assert(comp.rows.every(r=>r.tile.querySelector('.rcpt-tick').getAttribute('checked')!==null));
        """)

    def test_stale_native_changes_cannot_mutate_rows_drafts_or_send_requests(self):
        self.run_js("""
          const expires=[v=>{receiptBusy(v,true);},v=>{state.profile={id:'user2'};},v=>{routeToken++;},
            v=>{state.may={admin:false,receipts:false};},v=>{v.done=true;}];
          for(const expire of expires){
            clear(main);state.profile={id:'matt'};state.may=null;const v=drawReceipt(delivery(),routeToken);
            v.layout='list';rcptRefreshAll(v);const row=v.comps[0].rows[0],input=row.tile.querySelector('.rcpt-tick');
            const before=rcptRequestKey(v),notes=row.values.notes,key='decklab.receipt:matt:test:'+'a'.repeat(64);
            const draft=window.localStorage.getItem(key);expire(v);let writes=0;apiWrite=async()=>{writes++;return ready;};
            input.checked=true;input.fire('change');row.open.click();await previewDelivery(v);await applyDelivery(v);
            assert(!row.ticked);assert.equal(input.checked,false);assert.equal(row.values.notes,notes);assert.equal(rcptRequestKey(v),before);
            assert.equal(window.localStorage.getItem(key),draft);assert.equal(writes,0);assert(!v.sheet);
          }
        """,draw=False)

    def test_read_only_off_parts_products_and_pictures_keep_their_existing_interactions(self):
        self.run_js("""
          local.set('receiptLayout','list');const d=delivery();d.components.push({...d.components[0],id:'later'});
          const v=drawReceipt(d,routeToken);assert(v.comps.every(c=>!c.selected));
          assert.equal(main.querySelectorAll('.rcpt-tick').length,0);
          assert(v.comps.every(c=>c.rows.every(r=>r.tile.querySelectorAll('input').length===0)));
          const before=rcptRequestKey(v);v.comps[0].rows[0].open.click();assert.equal(inspections.length,1);assert(!v.sheet);
          assert.equal(rcptRequestKey(v),before);
          clear(main);state.may={admin:false,receipts:false};const readonly=drawReceipt(delivery(),routeToken);
          assert(readonly.readOnly);assert(main.querySelectorAll('.card-tile').length>0);assert(!main.querySelector('.rcpt-tick'));
          clear(main);state.may=null;const p=delivery();p.components=[{id:'kit',kind:'product',status:'pending',checks:[],fields:[],rows:[],
            product:{name:'Whole fixture'},items:[{name:'Alpha',set:'tst',collector_number:'1',finish:'nonfoil',quantity:'60',section:'deck'}],pictures:[],decks:[]}];
          const product=drawReceipt(p,routeToken);assert.equal(product.layout,'list');assert(!main.querySelector('.rcpt-row'));
          assert(main.querySelectorAll('.card-tile').length>0);assert(!main.querySelector('.rcpt-tick'));
          clear(main);local.set('receiptLayout','pictures');const pictures=drawReceipt(delivery(),routeToken);
          const tick=pictures.comps[0].rows[0].tile.querySelector('.rcpt-tick');assert.equal(tick.tag,'button');
          tick.click();assert(pictures.comps[0].rows[0].ticked);assert.equal(pictures.comps[0].rows[0].tile.querySelector('.rcpt-tick').getAttribute('aria-pressed'),'true');
        """,draw=False)

    def test_layout_changes_leave_canonical_rows_and_partial_receipt_draft_scope_unchanged(self):
        self.run_js("""
          const comp=view.comps[0],canonical=JSON.stringify(comp.rows.map(r=>r.values)),before=rcptRequestKey(view);
          const key='decklab.receipt:matt:test:'+'a'.repeat(64);let writes=0;apiWrite=async()=>{writes++;return ready;};
          comp.layoutButtons.find(b=>b.getAttribute('data-layout')==='list').click();
          assert.equal(local.get('receiptLayout'),'list');assert.equal(rcptRequestKey(view),before);
          assert.equal(JSON.stringify(comp.rows.map(r=>r.values)),canonical);assert.equal(window.localStorage.getItem(key),null);
          const input=comp.rows[1].tile.querySelector('.rcpt-tick');input.checked=true;input.fire('change');
          const selected=rcptRequest(view).components[0];same(selected.take,[{row:2}]);
          same(selected.rows.map(r=>[r.name,r.quantity,r.condition,r.language]),[['Alpha','2','',''],['Beta','1','NM','en']]);
          const draft=window.localStorage.getItem(key);assert(draft);const request=rcptRequestKey(view);
          comp.layoutButtons.find(b=>b.getAttribute('data-layout')==='pictures').click();
          assert.equal(rcptRequestKey(view),request);assert.equal(window.localStorage.getItem(key),draft);assert.equal(writes,0);
          comp.layoutButtons.find(b=>b.getAttribute('data-layout')==='list').click();
          assert.notEqual(comp.rows[1].tile.querySelector('.rcpt-tick').getAttribute('checked'),null);
          assert.equal(JSON.stringify(comp.rows.map(r=>r.values)),canonical);
        """)

    def test_all_card_attention_reasons_stay_under_the_name_and_unknown_details_remain_honest(self):
        self.run_js("""
          view.layout='list';const comp=view.comps[0],row=comp.rows[0];
          row.values.finish='foil';row.values.notes='Inspect signed card';
          row.pic={...comp.pictures[0],exact:false,why:'not recorded'};rcptRefreshAll(view);
          same(rcptAttention(view,comp,row),['condition or language not set','a note','default picture','edited']);
          const name=row.open.querySelector('.name'),attention=row.open.querySelector('.rcpt-row-attention');
          assert(name.contains(attention));assert.equal(attention.querySelectorAll('.status').length,4);
          for(const text of ['Condition or language ?','Check note','Check printing','Edited'])assert(attention.textContent.includes(text));
          assert(row.open.getAttribute('aria-label').includes('Needs attention'));
          const details=row.open.querySelector('.rcpt-row-details');assert(!name.contains(details));
          assert(details.textContent.includes('TST 1'));assert(details.textContent.includes('Foil'));
          assert(details.textContent.includes('Condition not recorded'));assert(details.textContent.includes('Language not recorded'));
          assert.equal(details.getAttribute('id'),`rcpt-row-details-${row.key}`);
          for(const control of [row.open,row.tile.querySelector('.rcpt-tick')]){
            same(control.getAttribute('aria-describedby').split(/\\s+/),[details.getAttribute('id')]);
            assert.equal(document.getElementById(details.getAttribute('id')),details);
          }
          const dashes=details.querySelectorAll('[aria-hidden=true]').filter(n=>n.textContent==='\u2014');assert.equal(dashes.length,2);
          for(const hidden of details.querySelectorAll('.sr-only'))assert.equal(hidden.getAttribute('aria-label'),null);
          row.values.set='';row.values.collector_number='';const before=rcptRequestKey(view);rcptRefreshAll(view);
          assert(row.open.querySelector('.rcpt-row-details').textContent.includes('Printing not recorded'));
          assert.equal(rcptRequestKey(view),before);
        """)

    def test_token_back_attention_and_pending_split_identity_survive_native_checking(self):
        self.run_js("""
          local.set('receiptLayout','list');const d=delivery();d.components=[{id:'tokens',kind:'tokens',status:'pending',checks:[],fields:""" + board.TOKEN_FIELDS + """,
            rows:[{front:'Bird',back:'',set:'tx',front_collector_number:'1',back_collector_number:'',finish:'nonfoil',
              quantity:'3',front_details:'1/1; flying',back_details:'',notes:'pairing unverified'}],pictures:[],decks:[]}];
          const v=drawReceipt(d,routeToken),comp=v.comps[0];rcptSplit(v,comp,comp.rows[0],1);
          assert.equal(comp.rows.length,2);assert.equal(comp.rows[0].orig,comp.rows[1].orig);
          assert.notEqual(comp.rows[0].key,comp.rows[1].key);
          for(const [i,row] of comp.rows.entries()){
            assert.equal(row.tile.getAttribute('data-row'),String(row.key));
            const name=row.open.querySelector('.name');assert(name.querySelector('.rcpt-row-attention').textContent.includes('Back not said yet'));
            assert(name.querySelector('.rcpt-row-part').textContent.includes(`Part ${i+1} of 2`));
            const detailId=`rcpt-row-details-${row.key}`,partId=`rcpt-row-part-${row.key}`;
            for(const control of [row.open,row.tile.querySelector('.rcpt-tick')]){
              same(control.getAttribute('aria-describedby').split(/\\s+/),[detailId,partId]);
              assert.equal(document.getElementById(detailId),row.open.querySelector('.rcpt-row-details'));
              assert.equal(document.getElementById(partId),name.querySelector('.rcpt-row-part'));
              assert(/still pending/i.test(document.getElementById(partId).textContent));
            }
          }
          const one=comp.rows.find(r=>r.values.quantity==='1'),input=one.tile.querySelector('.rcpt-tick');input.checked=true;input.fire('change');
          const pending=comp.rows.find(r=>!r.ticked);assert(pending.tile.getAttribute('class').includes('is-pending-split'));
          assert(/still pending/i.test(pending.open.querySelector('.rcpt-row-part').textContent));
          assert(pending.open.querySelector('.rcpt-pending-swatch'));assert(!one.open.querySelector('.rcpt-pending-swatch'));
          assert(!one.tile.getAttribute('class').includes('is-pending-split'));
          const sent=rcptRequest(v).components[0];same(sent.take,[{row:2}]);
          same(sent.rows.map(r=>[r.front,r.back,r.quantity]),[['Bird','','2'],['Bird','','1']]);
          assert(rcptClientBlockers(v).some(b=>b.text.includes('back')));
        """,draw=False)


def lab_rules(css):
    blocks = []
    for start in re.finditer(r"@media\s*\(min-width:\s*1000px\)\s*\{", css):
        depth, end = 1, start.end()
        while depth and end < len(css):
            depth += (css[end] == "{") - (css[end] == "}")
            end += 1
        blocks.append(css[start.end():end - 1])
    assert blocks, "The compact rules need the lab-width boundary"
    return "\n".join(blocks)


class ReceiptCompactCssTests(unittest.TestCase):
    def test_lab_rows_compose_a_44px_floor_keep_attention_wrapping_and_leave_shared_defaults_alone(self):
        shared = re.sub(r"/\*.*?\*/", "", (board.WEB / "cards-ui.css").read_text(encoding="utf-8"), flags=re.S)
        receipt = re.sub(r"/\*.*?\*/", "", (board.WEB / "receipts.css").read_text(encoding="utf-8"), flags=re.S)
        default = re.search(r"\.card-row\s*\{([^}]+)\}", shared).group(1)
        self.assertIn("min-height: 60px", default)
        shared_lab, receipt_lab = lab_rules(shared), lab_rules(receipt)
        self.assertRegex(shared_lab, r"\.card-row-compact\s*\{[^}]*min-height:\s*44px")
        self.assertRegex(shared_lab, r"\.card-row-compact \.thumb[^}]*width:\s*24px;\s*height:\s*34px")
        self.assertRegex(receipt_lab, r"\.rcpt-row\s*\{[^}]*grid-template-columns:\s*40px\s+minmax\(0,\s*1fr\)")
        self.assertRegex(receipt_lab, r"\.rcpt-row\s*>\s*\.card-row-compact\s*\{[^}]*min-height:\s*43px")
        self.assertRegex(receipt, r"\.rcpt-row\s*\{[^}]*border-bottom:\s*1px solid")
        self.assertRegex(receipt, r"\.rcpt-tick-cell\s*\{[^}]*min-height:\s*44px")
        self.assertRegex(receipt, r"\.rcpt-tick-cell\s*>\s*input\s*\{[^}]*width:\s*18px;\s*height:\s*18px")
        self.assertNotRegex(receipt_lab, r"grid-template-columns:\s*repeat\(auto-fill,\s*minmax\(420px")
        attention = re.search(r"\.rcpt-row-attention\s*\{([^}]+)\}", receipt_lab).group(1)
        self.assertIn("display: flex", attention)
        self.assertIn("flex-wrap: wrap", attention)
        self.assertRegex(receipt_lab, r"\.rcpt-row-attention \.status\s*\{[^}]*white-space:\s*normal")
        self.assertIn("overflow-wrap: anywhere", receipt_lab)
        self.assertRegex(receipt, r"@media[^\{]*\(pointer:\s*coarse\)[^\{]*\{\s*\.rcpt-row\s*\{[^}]*44px")
        self.assertRegex(receipt, r"@media[^\{]*\(pointer:\s*coarse\)[\s\S]*?\.rcpt-row\s*>\s*\.card-row-compact\s*\{[^}]*min-height:\s*44px")
        self.assertRegex(receipt_lab, r"\.rcpt-row\.is-pending-split\s*\{[^}]*dashed var\(--accent-line\)")
        self.assertIn("repeating-linear-gradient", receipt_lab)
        self.assertNotRegex(receipt_lab, r"\.rcpt-row\.is-ticked[^}]*background")
