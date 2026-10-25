"""Ticked is a saved view preference, independent of receipt selection and exact preview scope."""
import unittest

from decklab.tests import test_receipts_ui as board


@unittest.skipUnless(board.NODE, "Node.js isn't installed")
class ReceiptTickedTests(unittest.TestCase):
    run_js = board.ReceiptBoardTests.run_js

    def test_filter_order_attention_counts_and_fresh_empty_view_do_not_create_a_draft(self):
        self.run_js("""
          const comp=view.comps[0],key='decklab.receipt:matt:test:'+'a'.repeat(64);
          same(comp.filterButtons.map(b=>b.getAttribute('data-filter')),['all','todo','attention','ticked']);
          same(comp.filterButtons.map(b=>[b.children[0].textContent,b.children[1].textContent]),
            [['All','All'],['Not checked','To do'],['Needs attention (2 rows)','Attention (2 rows)'],['Ticked','Ticked']]);
          const canonical=JSON.stringify(comp.rows.map(r=>r.values)),request=rcptRequestKey(view),layout=view.layout;
          let writes=0;apiWrite=async()=>{writes++;return ready;};
          comp.filterButtons[3].click();assert.equal(view.filter,'ticked');assert(comp.rows.every(r=>r.tile.hidden));
          assert.equal(comp.filterButtons[3].getAttribute('aria-pressed'),'true');
          const empty=comp.grid.querySelector('.rcpt-none');assert.equal(empty.querySelector('p').textContent,'Nothing here is checked yet.');
          assert.equal(empty.querySelector('button').textContent,'Show all');empty.querySelector('button').click();
          assert.equal(view.filter,'all');assert(comp.rows.every(r=>!r.tile.hidden));assert.equal(view.layout,layout);
          assert.equal(JSON.stringify(comp.rows.map(r=>r.values)),canonical);assert.equal(rcptRequestKey(view),request);
          assert.equal(window.localStorage.getItem(key),null);assert(!view.drafting);assert.equal(writes,0);
          // The view predicate describes checked rows even while their component is switched off.
          comp.selected=false;comp.rows[0].ticked=true;rcptSetFilter(view,'ticked');
          assert(!comp.rows[0].tile.hidden);assert(comp.rows[1].tile.hidden);
          assert(rcptShown(view,comp,comp.rows[0]));assert(!rcptShown(view,comp,comp.rows[1]));
          assert.equal(rcptRequest(view).components.length,0);assert.equal(window.localStorage.getItem(key),null);
          const oldAll=comp.filterButtons[0];clear(main);local.set('receiptLayout','list');
          const current=drawReceipt(delivery(),routeToken),currentComp=current.comps[0];
          const layoutState=currentComp.layoutButtons.map(b=>b.getAttribute('aria-pressed'));
          oldAll.click();assert.equal(view.filter,'ticked');assert.equal(current.filter,'all');
          same(currentComp.layoutButtons.map(b=>b.getAttribute('aria-pressed')),layoutState);
          assert.equal(current.layout,'list');assert.equal(window.localStorage.getItem(key),null);
          current.done=true;currentComp.filterButtons[3].click();assert.equal(current.filter,'all');
          assert.equal(window.localStorage.getItem(key),null);
        """)

    def test_view_changes_preserve_a_valid_preview_native_checked_state_and_existing_draft_content(self):
        self.run_js("""
          view.layout='list';rcptRefreshAll(view);const comp=view.comps[0],row=comp.rows[1];
          rcptTick(view,comp,row,true);comp.checks=comp.checks.map(()=>true);rcptChanged(view);
          let calls=0;apiWrite=async()=>{calls++;return ready;};await previewDelivery(view);assert(view.preview);
          const preview=view.preview,seq=view.seq,request=rcptRequestKey(view),canonical=JSON.stringify(comp.rows.map(r=>r.values));
          const key='decklab.receipt:matt:test:'+'a'.repeat(64),before=JSON.parse(window.localStorage.getItem(key));
          const changed=rcptChanged;let changes=0;rcptChanged=(...args)=>{changes++;return changed(...args);};
          for(const filter of ['ticked','todo','attention','all']){
            comp.filterButtons.find(b=>b.getAttribute('data-filter')===filter).click();
            assert.equal(view.preview,preview);assert.equal(view.seq,seq);assert.equal(rcptRequestKey(view),request);
            assert.equal(JSON.stringify(comp.rows.map(r=>r.values)),canonical);assert(row.ticked);assert(!comp.rows[0].ticked);
            assert.notEqual(row.tile.querySelector('.rcpt-tick').getAttribute('checked'),null);
            assert.equal(comp.rows[0].tile.querySelector('.rcpt-tick').getAttribute('checked'),null);
            const saved=JSON.parse(window.localStorage.getItem(key));assert.equal(saved.filter,filter);
            delete saved.filter;const original={...before};delete original.filter;same(saved,original);
          }
          assert.equal(changes,0);assert.equal(calls,1);assert.equal(view.layout,'list');
          assert.equal(view.preview.key,request);assert.equal(view.preview.token,ready.preview);
        """)

    def test_hidden_rows_stay_in_bulk_and_exact_preview_scope_but_unselected_components_do_not(self):
        self.run_js("""
          const data=delivery();data.components[0].rows[0].quantity='8';
          data.components.push({...delivery().components[0],id:'later'});const v=drawReceipt(data,routeToken);
          const comp=v.comps[0],other=v.comps[1];comp.selected=true;other.selected=false;
          rcptTick(v,comp,comp.rows[1],true);rcptTick(v,other,other.rows[0],true);
          comp.checks=comp.checks.map(()=>true);rcptSetFilter(v,'ticked');
          assert(comp.rows[0].tile.hidden);assert(!comp.rows[1].tile.hidden);
          assert(!other.rows[0].tile.hidden);assert(other.rows[1].tile.hidden);
          assert.equal(comp.fillButton.textContent,'Apply to 1 row');rcptFillBlanks(v,comp,'LP','ja');
          assert.equal(comp.rows[0].values.condition,'LP');assert.equal(comp.rows[0].values.language,'ja');
          assert.equal(other.rows[0].values.condition,'');assert.equal(other.rows[0].values.language,'');
          const before=rcptRequest(v);assert.equal(before.components.length,1);assert.equal(before.components[0].id,'cards');
          same(before.components[0].take,[{row:2}]);
          same(before.components[0].rows.map(r=>[r.quantity,r.condition,r.language]),[['8','LP','ja'],['1','NM','en']]);
          const calls=[];apiWrite=async(path,payload)=>{calls.push([path,payload]);return ready;};
          await previewDelivery(v);assert.equal(calls.length,1);assert.equal(calls[0][0],'/api/receipt/preview');
          same(calls[0][1].components,before.components);assert(v.preview);
          const preview=v.preview;comp.filterButtons[1].click();assert(comp.rows[1].tile.hidden);
          assert.equal(v.preview,preview);same(v.preview.received.map(c=>[c.c.id,c.rows.map(r=>[r.values.name,r.values.quantity])]),
            [['cards',[['Beta','1']]]]);same(rcptRequest(v),before);
        """,draw=False)

    def test_unticking_in_list_and_pictures_moves_to_the_next_checked_row_then_show_all(self):
        self.run_js("""
          for(const layout of ['list','pictures']){
            clear(main);const v=drawReceipt(delivery(),routeToken),comp=v.comps[0];v.layout=layout;
            for(const row of comp.rows)rcptTick(v,comp,row,true);rcptSetFilter(v,'ticked');
            const untick=row=>{const control=row.tile.querySelector('.rcpt-tick');control.focus();
              if(layout==='list'){assert.equal(control.tag,'input');control.checked=false;control.fire('change');}
              else{assert.equal(control.tag,'button');control.click();}};
            untick(comp.rows[0]);assert(!comp.rows[0].ticked);assert(comp.rows[0].tile.hidden);
            assert.equal(document.activeElement,comp.rows[1].tile.querySelector('.rcpt-tick'));
            untick(comp.rows[1]);assert(comp.rows.every(r=>!r.ticked&&r.tile.hidden));
            const empty=comp.grid.querySelector('.rcpt-none'),show=empty.querySelector('button');
            assert.equal(empty.querySelector('p').textContent,'Nothing here is checked yet.');assert.equal(document.activeElement,show);
            show.click();assert.equal(v.filter,'all');assert(comp.rows.every(r=>!r.tile.hidden));
            for(const row of comp.rows){const control=row.tile.querySelector('.rcpt-tick');
              if(layout==='list')assert.equal(control.getAttribute('checked'),null);
              else assert.equal(control.getAttribute('aria-pressed'),'false');}
            assert.equal(v.layout,layout);same(rcptRequest(v).components[0].take,[]);
          }
        """,draw=False)

    def test_optional_draft_filter_accepts_only_known_values_without_changing_layout_or_receipt_content(self):
        self.run_js("""
          local.set('receiptLayout','list');const source=drawReceipt(delivery(),routeToken),comp=source.comps[0];
          rcptTick(source,comp,comp.rows[1],true);const request=rcptRequest(source);
          const key='decklab.receipt:matt:test:'+'a'.repeat(64),base=JSON.parse(window.localStorage.getItem(key));
          const cases=[['all','all'],['todo','todo'],['attention','attention'],['ticked','ticked'],
            [undefined,'all'],[null,'all'],['unknown','all'],['TICKED','all'],[{},'all'],[['ticked'],'all'],[1,'all']];
          for(const [value,expected]of cases){
            const draft=JSON.parse(JSON.stringify(base));if(value===undefined)delete draft.filter;else draft.filter=value;
            window.localStorage.setItem(key,JSON.stringify(draft));clear(main);const resumed=drawReceipt(delivery(),routeToken);
            assert.equal(resumed.filter,'all');assert.equal(resumed.layout,'list');assert(!resumed.comps[0].rows[1].ticked);
            const offer=main.querySelector('.rcpt-resume-box');assert(offer);offer.querySelector('button').click();
            assert.equal(resumed.filter,expected);assert.equal(resumed.layout,'list');assert(resumed.comps[0].rows[1].ticked);
            same(rcptRequest(resumed),request);assert.equal(JSON.parse(window.localStorage.getItem(key)).filter,expected);
            const selected=resumed.comps[0].filterButtons.filter(b=>b.getAttribute('aria-pressed')==='true');
            assert.equal(selected.length,1);assert.equal(selected[0].getAttribute('data-filter'),expected);
            if(expected==='ticked'){
              const part=resumed.comps[0],hidden=part.rows[0];assert(hidden.tile.hidden);
              rcptGoTo(resumed,{text:'Inspect this card',comp:part,row:hidden});
              assert.equal(resumed.filter,'all');assert.equal(JSON.parse(window.localStorage.getItem(key)).filter,'all');
              assert.equal(resumed.sheet.row,hidden);same(rcptRequest(resumed),request);closeReceiptSheets();
            }
          }
        """,draw=False)


if __name__ == "__main__":
    unittest.main()
