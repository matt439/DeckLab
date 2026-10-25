"""The selected Receive row is view context; the existing inspector owns every edit."""
import re
import unittest

from decklab.tests import test_receipts_ui as board


@unittest.skipUnless(board.NODE, "Node.js isn't installed")
class ReceiptSelectedTests(unittest.TestCase):
    run_js = board.ReceiptBoardTests.run_js

    def test_initial_context_uses_a_current_visible_row_and_never_claims_it_was_checked(self):
        self.run_js("""
          const comp=view.comps[0],row=comp.rows[0],facts=view.selectedFacts.textContent;
          same(view.selectedRow,{comp:'cards',key:row.key});assert(facts.includes('Alpha'));
          assert(facts.includes('2 card copies'));assert(facts.includes('Not checked'));
          assert(facts.includes('Condition not recorded'));assert(facts.includes('Language not recorded'));
          assert(facts.includes('inspect to confirm what arrived'));assert(!row.ticked);assert(!view.sheet);
          assert.equal(row.open.getAttribute('aria-current'),'true');assert.equal(comp.rows[1].open.getAttribute('aria-current'),null);
          assert.equal(store.size,0);assert(!view.drafting);assert.equal(view.preview,null);
          assert.equal(view.selectedInspect.getAttribute('aria-haspopup'),'dialog');
          assert(view.root.querySelector('#'+view.selectedInspect.getAttribute('aria-describedby'))===view.selectedFacts);
          assert.equal(view.root.querySelectorAll('.action-bar').length,1);
          assert.equal(view.root.querySelectorAll('.rcpt-picture-inspect').length,2);
          assert.equal(viewerGroup(row.open).items.length,2);
        """)

    def test_inspecting_and_navigating_select_exact_rows_without_drafts_reads_or_preview_changes(self):
        self.run_js("""
          const comp=view.comps[0],request=rcptRequestKey(view),data=JSON.stringify(view.data),before=[...store.entries()];
          view.preview={key:request};const preview=view.preview,calls=[];
          api=async p=>{calls.push(p);throw new Error('no reads');};apiWrite=async p=>{calls.push(p);throw new Error('no writes');};
          comp.rows[1].open.click();assert(view.sheet.row===comp.rows[1]);
          same(view.selectedRow,{comp:'cards',key:comp.rows[1].key});assert(view.selectedFacts.textContent.includes('Beta'));
          rcptStepSheet(view,-1);assert(view.sheet.row===comp.rows[0]);assert(view.selectedFacts.textContent.includes('Alpha'));
          const next=document.body.querySelectorAll('button').find(b=>b.textContent.startsWith('Next card'));
          next.click();assert(view.sheet.row===comp.rows[1]);closeReceiptSheets();assert(!view.sheet);
          assert(view.selectedFacts.textContent.includes('Beta'));assert(document.activeElement===comp.rows[1].open);
          view.selectedInspect.click();assert(view.sheet.row===comp.rows[1]);closeReceiptSheets();
          assert.equal(rcptRequestKey(view),request);assert(view.preview===preview);same([...store.entries()],before);
          assert.equal(JSON.stringify(view.data),data);same(calls,[]);assert(!view.drafting);
        """)

    def test_edits_ticks_and_summary_action_identity_follow_current_values_and_fresh_close_focus(self):
        self.run_js("""
          const comp=view.comps[0],row=comp.rows[0],action=view.selectedInspect;
          action.focus();action.click();assert(view.sheet.row===row);
          const condition=document.body.querySelectorAll('[role="group"]').find(n=>n.getAttribute('aria-label')==='Condition');
          condition.querySelectorAll('button').find(b=>b.textContent==='LP').click();
          const language=document.body.querySelectorAll('select').find(n=>n.getAttribute('aria-label')==='Language');
          language.value='ja';language.fire('change');
          assert(view.selectedFacts.textContent.includes('Lightly played'));assert(view.selectedFacts.textContent.includes('Japanese'));
          assert(view.selectedInspect===action);const old=row.open;
          rcptTick(view,comp,row,true);assert(view.selectedFacts.textContent.includes('Checked'));
          assert(!view.selectedFacts.textContent.includes('Not checked'));assert(row.open!==old);
          assert.equal(row.open.getAttribute('aria-current'),'true');
          view.layout='list';rcptRefreshAll(view);const fresh=row.open;assert(fresh!==old);closeReceiptSheets();
          assert(document.activeElement===fresh);assert(fresh.isConnected);assert(view.selectedInspect===action);
          assert.equal(view.root.querySelectorAll('.card-row').length,2);
          assert.equal(viewerGroup(fresh).items.length,2);
        """)

    def test_split_parts_have_distinct_keys_and_merge_undo_keeps_exact_live_context(self):
        self.run_js("""
          const comp=view.comps[0],first=comp.rows[0];rcptOpenSheet(view,comp,first);rcptSplit(view,comp,first,1);
          const part=comp.rows[1];assert.equal(part.orig,first.orig);assert.notEqual(part.key,first.key);
          assert(view.sheet.row===part);same(view.selectedRow,{comp:'cards',key:part.key});
          assert(view.selectedFacts.textContent.includes('Part 2 of 2; still pending'));
          rcptTick(view,comp,part,true);assert(view.selectedFacts.textContent.includes('1 card copy'));
          assert(view.selectedFacts.textContent.includes('Checked'));
          first.values={...part.values};let undo=null;showToast=(text,opts)=>{undo=opts.undo;};
          await rcptMerge(view,comp,part);assert(view.sheet.row===first);assert.equal(comp.rows.length,2);
          same(view.selectedRow,{comp:'cards',key:first.key});assert(view.selectedFacts.textContent.includes('2 card copies'));
          assert(!view.selectedFacts.textContent.includes('Part 2'));assert(undo);undo();
          assert.equal(comp.rows.length,3);assert(comp.rows[1]===part);assert(view.sheet.row===first);
          rcptSelectRow(view,comp,part);same(view.selectedRow,{comp:'cards',key:part.key});
          assert(view.selectedFacts.textContent.includes('Part 2 of 2'));assert.equal(rcptQty(first)+rcptQty(part),2);
        """)

    def test_hidden_selection_is_explicit_and_reopens_only_its_exact_current_row(self):
        self.run_js("""
          const comp=view.comps[0],row=comp.rows[0];rcptSelectRow(view,comp,row);rcptSetFilter(view,'ticked');
          assert(row.tile.hidden);same(view.selectedRow,{comp:'cards',key:row.key});
          assert(view.selectedFacts.textContent.includes('Hidden by the current view'));assert(!view.selectedInspect.hidden);
          const request=rcptRequestKey(view);view.selectedInspect.click();
          assert.equal(view.filter,'all');assert(!row.tile.hidden);assert(view.sheet.row===row);
          assert.equal(rcptRequestKey(view),request);closeReceiptSheets();assert(document.activeElement===row.open);
          rcptSetFilter(view,'ticked');view.selectedRow=null;rcptSyncSelected(view);
          assert(view.selectedInspect.hidden);assert(view.selectedFacts.textContent.includes('visible row'));
          assert(!view.selectedFacts.textContent.includes('Alpha'));rcptSetFilter(view,'all');
          same(view.selectedRow,{comp:'cards',key:row.key});assert(!view.selectedInspect.hidden);
          rcptTick(view,comp,comp.rows[1],true);rcptSetFilter(view,'ticked');view.selectedRow=null;rcptSyncSelected(view);
          assert(row.tile.hidden);assert(!comp.rows[1].tile.hidden);
          same(view.selectedRow,{comp:'cards',key:comp.rows[1].key});assert(view.selectedFacts.textContent.includes('Beta'));
        """)

    def test_off_parts_and_replaced_draft_rows_never_reuse_original_indexes(self):
        self.run_js("""
          const d=delivery();d.components.push({...d.components[0],id:'later',rows:[{...d.components[0].rows[0],name:'Later card'}],
            pictures:[],decks:[]});const v=drawReceipt(d,routeToken),first=v.comps[0],later=v.comps[1];
          assert.equal(v.selectedRow,null);assert(v.selectedInspect.hidden);first.selected=true;rcptDrawBoard(v);rcptChanged(v);
          const old=first.rows[0],originalKey=old.key;rcptSelectRow(v,first,old);rcptTick(v,first,old,true);
          const draft=rcptLoadDraft(v);rcptApplyDraft(v,draft);const fresh=first.rows[0];
          assert.notEqual(fresh.key,originalKey);assert.equal(fresh.orig,old.orig);
          assert.equal(rcptCurrentRow(v,{comp:first.c.id,key:originalKey}),null);
          same(v.selectedRow,{comp:'cards',key:fresh.key});v.selectedInspect.click();assert(v.sheet.row===fresh);closeReceiptSheets();
          later.selected=true;first.selected=false;rcptDrawBoard(v);rcptChanged(v);
          assert(v.selectedFacts.textContent.includes('Later card'));assert(!v.selectedFacts.textContent.includes('Alpha'));
          same(v.selectedRow,{comp:'later',key:later.rows[0].key});
          rcptSelectRow(v,first,fresh);assert.equal(v.selectedRow.comp,'later');
          later.selected=false;rcptDrawBoard(v);rcptChanged(v);assert.equal(v.selectedRow,null);assert(v.selectedInspect.hidden);
        """, draw=False)

    def test_missing_runtime_key_refuses_retained_action_instead_of_opening_a_sibling(self):
        self.run_js("""
          const comp=view.comps[0],row=comp.rows[0],action=view.selectedInspect;
          rcptSplit(view,comp,row,1);const part=comp.rows[1];rcptSelectRow(view,comp,part);
          comp.rows=comp.rows.filter(r=>r!==part);const request=rcptRequestKey(view),draft=[...store.entries()];
          action.click();assert(!view.sheet);assert.equal(rcptRequestKey(view),request);same([...store.entries()],draft);
          rcptSyncSelected(view);assert.equal(view.selectedRow.key,row.key);assert.notEqual(view.selectedRow.key,part.key);
          assert.equal(row.orig,part.orig);assert(!view.selectedFacts.textContent.includes('Part 2'));
        """)

    def test_busy_done_reload_permission_route_profile_and_detached_guards_refuse_summary_actions(self):
        self.run_js("""
          const action=view.selectedInspect,comp=view.comps[0],request=rcptRequestKey(view),draft=[...store.entries()];
          const cases=[()=>view.busy=true,()=>view.done=true,()=>view.reloadRequired=true,()=>state.may={receipts:false},
            ()=>routeToken++,()=>state.profile={id:'other'},()=>view.root.remove()];
          for(const change of cases){
            view.busy=false;view.done=false;view.reloadRequired=false;state.may=null;state.profile={id:'matt'};
            view.token=routeToken;if(!view.root.isConnected)main.append(view.root);rcptSyncSelected(view);
            change();action.click();assert(!view.sheet);assert.equal(rcptRequestKey(view),request);
            same([...store.entries()],draft);assert(!comp.rows.some(r=>r.ticked));
            rcptSyncSelected(view);if(!view.busy){assert(view.selectedSummary.hidden);assert(!view.selectedFacts.textContent);}
            else assert(action.disabled);
          }
        """)

    def test_products_read_only_and_completed_orders_add_no_row_editor_or_false_selection(self):
        self.run_js("""
          const d=delivery();d.components=[{id:'kit',kind:'product',status:'pending',checks:[],fields:[],rows:[],
            product:{name:'Fixture product'},items:[{name:'Unchosen product card',quantity:'60'}],pictures:[],decks:[]}];
          const product=drawReceipt(d,routeToken);assert.equal(product.selectedRow,null);assert(product.selectedInspect.hidden);
          assert(product.selectedFacts.textContent.includes('Whole products keep their own choices'));
          assert(!product.selectedFacts.textContent.includes('Unchosen product card'));assert(!product.sheet);
          state.may={receipts:false};const readOnly=drawReceipt(delivery(),routeToken);
          assert(readOnly.readOnly);assert(!readOnly.root.querySelector('.rcpt-selected-summary'));assert(!readOnly.selectedRow);
          state.may=null;const done=delivery();done.components[0].status='received';const completed=drawReceipt(done,routeToken);
          assert(!completed.root.querySelector('.rcpt-selected-summary'));assert(!completed.sheet);
        """, draw=False)

    def test_unknown_token_pairing_is_described_without_a_row_check_or_inferred_reverse(self):
        self.run_js("""
          const d=delivery();d.components=[{id:'tokens',kind:'tokens',status:'pending',checks:['Inspect the physical pairing'],
            fields:""" + board.TOKEN_FIELDS + """,rows:[{front:'Bird',back:'',set:'tx',front_collector_number:'1',
              back_collector_number:'',finish:'nonfoil',quantity:'3',front_details:'1/1; flying',back_details:'',
              notes:'reverse face unconfirmed'}],pictures:[],decks:[]}];
          const v=drawReceipt(d,routeToken),comp=v.comps[0],row=comp.rows[0],request=rcptRequestKey(v);
          assert(v.selectedFacts.textContent.includes('3 token card copies'));assert(v.selectedFacts.textContent.includes('Reverse not confirmed'));
          assert(!v.selectedFacts.textContent.includes('Single-sided verified'));assert.equal(v.selectedSummary.querySelectorAll('input').length,0);
          assert.equal(comp.checks[0],false);v.selectedInspect.click();assert(v.sheet.row===row);closeReceiptSheets();
          assert.equal(rcptRequestKey(v),request);assert.equal(comp.checks[0],false);assert(!row.ticked);assert.equal(row.values.back,'');
          row.values.back='Golem';row.values.notes='pairing confirmed';rcptRowChanged(v,comp,row);
          assert(v.selectedFacts.textContent.includes('Bird // Golem'));assert(v.selectedFacts.textContent.includes('Reverse recorded'));
        """, draw=False)


class ReceiptSelectedCssTests(unittest.TestCase):
    def test_summary_wraps_has_words_below_lab_and_uses_existing_interactive_nodes(self):
        css = (board.WEB / 'receipts.css').read_text(encoding='utf-8')
        js = (board.WEB / 'receipt-layout.js').read_text(encoding='utf-8')
        self.assertIn('.rcpt-selected-facts', css)
        self.assertRegex(css, r'\.rcpt-selected-name\s*\{[^}]*overflow-wrap:\s*anywhere')
        self.assertRegex(css, r'@media \(max-width:\s*999px\)\s*\{\s*\.rcpt-selected-code\s*\{\s*display:\s*none')
        summary = js[js.index('function rcptSyncSelected'):js.index('/** Classify only')]
        self.assertNotRegex(summary, r'\b(?:api|apiWrite|rcptChanged|rcptSaveDraft|viewerItem|cardTile|rcptCardFields|rcptTokenFields)\s*\(')
