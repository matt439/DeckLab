"""One canonical arrival check moves between its proved row and component fallback.

Real page functions with deterministic DOM/API doubles; no browser or data writes.
"""
import unittest

from decklab.tests import test_receipt_check_targets_ui as support
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ReceiptInlineChecksUiTests(unittest.TestCase):
    def run_js(self, scenario):
        support.ReceiptCheckTargetUiTests.run_js(self, r'''
          const changeCheck=(comp,index,checked)=>{const input=comp.checkBoxes[index];input.checked=checked;input.fire('change');return input;};
          const onlyCanonical=(comp,inputs=comp.checkBoxes)=>{
            const found=canonicalChecks(comp);assert.equal(found.length,comp.c.checks.length);
            assert.equal(new Set(found).size,found.length);
            for(const input of inputs)assert.equal(found.filter(node=>node===input).length,1);
          };
          const firstTarget=()=>{const d=targeted();d.components[0].check_targets[0]={row:1,row_sha256:'b'.repeat(64)};return d;};
          const noNestedControls=comp=>{
            comp.checkBoxes.forEach((input,index)=>{
              assert(comp.checkLabels[index].contains(input));assert.equal(input.parentNode,comp.checkLabels[index]);
              for(let node=comp.checkLabels[index].parentNode;node&&node!==comp.section;node=node.parentNode)
                assert(!['label','button'].includes(node.tag),'Canonical check must not nest in another control');
            });
          };
        ''' + scenario)

    def test_targeted_control_moves_inline_once_while_general_check_stays_in_component_panel(self):
        self.run_js(r'''
          const v=draw(),c=v.comps[0],inputs=[...c.checkBoxes],labels=[...c.checkLabels];
          assert(c.checkPanel.contains(c.checkFallback));assert(c.rows[1].checkHost);
          assert(c.rows[1].tile.querySelector('.rcpt-row-checks').contains(inputs[0]));assert(c.rows[1].checkHost.contains(labels[0]));
          assert(c.checkFallback.contains(inputs[1]));assert(!c.checkFallback.contains(inputs[0]));
          assert(!c.rows[0].tile.contains(inputs[0]));onlyCanonical(c,inputs);noNestedControls(c);
          assert.equal(c.section.querySelectorAll('.rcpt-check').length,2);assert.equal(inputs[0].checked,false);
        ''')

    def test_inline_check_updates_only_shared_check_and_never_receives_or_changes_card_copies(self):
        self.run_js(r'''
          let writes=0;apiWrite=async()=>{writes++;};const v=draw(),c=v.comps[0],inputs=[...c.checkBoxes];
          const before=JSON.stringify(c.rows.map(row=>row.values)),tickStates=c.rows.map(row=>row.ticked);
          changeCheck(c,0,true);assert.equal(c.checks[0],true);assert.equal(c.checks[1],false);
          assert.equal(JSON.stringify(c.rows.map(row=>row.values)),before);same(c.rows.map(row=>row.ticked),tickStates);
          assert.equal(rcptProgress(v).ticked,0);assert.equal(writes,0);onlyCanonical(c,inputs);
          assert(c.rows[1].checkHost.contains(inputs[0]));changeCheck(c,0,false);assert.equal(c.checks[0],false);
        ''')

    def test_targeted_fallback_shows_same_original_scope_caption_and_hides_it_again_inline(self):
        self.run_js(r'''
          const v=draw(),c=v.comps[0],input=c.checkBoxes[0],scope=c.checkScopes[0],general=c.checkScopes[1];
          const described=input.getAttribute('aria-describedby');
          assert.equal(scope.getAttribute('class'),'sr-only');assert.equal(general.getAttribute('class'),'sr-only');
          rcptSetFilter(v,'ticked');assert(c.checkFallback.contains(input));
          assert.equal(c.checkScopes[0],scope);assert.equal(scope.getAttribute('class'),'rcpt-check-scope');
          assert(scope.textContent.includes('Row 2: 1 x Alpha'));assert(scope.textContent.includes('TST 2'));
          assert.equal(input.getAttribute('aria-describedby'),described);assert.equal(scope.id,described);
          assert.equal(general.getAttribute('class'),'sr-only');assert.equal(c.checkScopes[1],general);
          rcptSetFilter(v,'all');assert(c.rows[1].checkHost.contains(input));
          assert.equal(c.checkScopes[0],scope);assert.equal(scope.getAttribute('class'),'sr-only');
          assert.equal(general.getAttribute('class'),'sr-only');onlyCanonical(c);noNestedControls(c);
          c.selected=false;rcptDrawGrid(v,c);assert(c.checkFallback.contains(input));
          assert.equal(scope.getAttribute('class'),'rcpt-check-scope');assert.equal(general.getAttribute('class'),'sr-only');
        ''')

    def test_checks_still_gate_whole_component_when_only_another_original_row_arrived(self):
        self.run_js(r'''
          const v=draw(),c=v.comps[0];rcptTick(v,c,c.rows[0],true);
          assert(!c.rows[1].ticked);assert.equal(rcptRequest(v).components[0].verified,false);
          assert(rcptClientBlockers(v).some(item=>item.text==='Check not ticked: Check exact art'));
          changeCheck(c,0,true);assert.equal(rcptRequest(v).components[0].verified,false);changeCheck(c,1,true);
          const sent=rcptRequest(v).components[0];assert.equal(sent.verified,true);same(sent.take,[{row:1}]);
          assert(!JSON.stringify(sent).includes('check_targets'));assert(!JSON.stringify(sent).includes('row_sha256'));
          assert(!JSON.stringify(sent).includes('checkHost'));assert(!c.rows[1].ticked);
        ''')

    def test_attention_filter_parks_newly_hidden_target_and_restores_same_checkbox_focus(self):
        self.run_js(r'''
          const v=draw(),c=v.comps[0],inputs=[...c.checkBoxes],check=inputs[0];c.pictures.forEach(picture=>picture.exact=true);
          rcptSetFilter(v,'attention');assert(!c.rows[1].tile.hidden);assert(c.rows[1].checkHost.contains(check));
          check.focus();changeCheck(c,0,true);assert(c.rows[1].tile.hidden);assert(c.checkFallback.contains(check));
          assert.equal(document.activeElement,check);onlyCanonical(c,inputs);
          changeCheck(c,0,false);assert(!c.rows[1].tile.hidden);assert(c.rows[1].checkHost.contains(check));
          assert.equal(document.activeElement,check);onlyCanonical(c,inputs);noNestedControls(c);
        ''')

    def test_ticked_filter_moves_same_focused_check_between_fallback_and_visible_target(self):
        self.run_js(r'''
          const v=draw(),c=v.comps[0],check=c.checkBoxes[0],inputs=[...c.checkBoxes];rcptSetFilter(v,'ticked');
          assert(c.rows[1].tile.hidden);assert(c.checkFallback.contains(check));check.focus();
          rcptTick(v,c,c.rows[1],true);assert(!c.rows[1].tile.hidden);assert(c.rows[1].checkHost.contains(check));assert.equal(document.activeElement,check);
          rcptTick(v,c,c.rows[1],false);assert(c.rows[1].tile.hidden);assert(c.checkFallback.contains(check));assert.equal(document.activeElement,check);
          assert.equal(c.checks[0],false);onlyCanonical(c,inputs);
        ''')

    def test_pictures_and_list_keep_one_identical_control_path_at_each_supplied_width(self):
        self.run_js(r'''
          const v=draw(),c=v.comps[0],inputs=[...c.checkBoxes],labels=[...c.checkLabels];
          for(const width of [320,820,1920])for(const layout of ['pictures','list']){
            window.innerWidth=width;v.layout=layout;rcptRefreshAll(v);onlyCanonical(c,inputs);
            assert(c.rows[1].checkHost.contains(inputs[0]));assert(c.checkFallback.contains(inputs[1]));
            assert.equal(c.checkLabels[0],labels[0]);assert.equal(c.checkLabels[1],labels[1]);noNestedControls(c);
          }
        ''')

    def test_unselected_component_keeps_controls_in_fallback_and_rejects_changes_until_selected(self):
        self.run_js(r'''
          const d=targeted();d.components.push({...d.components[0],id:'cards-2',checks:[],check_targets:[],
            rows:d.components[0].rows.map(row=>({...row})),pictures:[...d.components[0].pictures]});
          const v=draw(d),c=v.comps[0],inputs=[...c.checkBoxes],arrived=c.section.querySelector('.rcpt-arrived').querySelector('input');
          assert.equal(c.selected,false);assert(c.checkFallback.contains(inputs[0]));changeCheck(c,0,true);assert.equal(c.checks[0],false);assert.equal(inputs[0].checked,false);
          arrived.checked=true;arrived.fire('change');assert(c.selected);assert(c.rows[1].checkHost.contains(inputs[0]));changeCheck(c,0,true);assert(c.checks[0]);
          arrived.checked=false;arrived.fire('change');assert(c.checkFallback.contains(inputs[0]));changeCheck(c,0,false);
          assert.equal(c.checks[0],true);assert.equal(inputs[0].checked,true);onlyCanonical(c,inputs);
        ''')

    def test_actual_split_merge_and_undo_keep_same_labels_only_on_first_visible_original_piece(self):
        self.run_js(r'''
          const v=draw(firstTarget()),c=v.comps[0],inputs=[...c.checkBoxes],labels=[...c.checkLabels];
          rcptSplit(v,c,c.rows[0],1);let parts=c.rows.filter(row=>row.orig===0);assert.equal(parts.length,2);
          assert(parts[0].checkHost.contains(inputs[0]));assert(!parts[1].tile.querySelector('.rcpt-row-checks').contains(inputs[0]));
          assert.equal(parts[1].tile.querySelector('.rcpt-row-checks').querySelector('input'),null);onlyCanonical(c,inputs);
          await rcptMerge(v,c,parts[0]);assert.equal(c.rows.length,2);assert(c.rows[0].checkHost.contains(inputs[0]));onlyCanonical(c,inputs);
          document.querySelector('#toast-undo').querySelector('button').click();parts=c.rows.filter(row=>row.orig===0);assert.equal(parts.length,2);
          assert(parts[0].checkHost.contains(inputs[0]));assert(!parts[1].tile.contains(inputs[0]));assert.equal(c.checkLabels[0],labels[0]);onlyCanonical(c,inputs);
        ''')

    def test_filtering_first_split_piece_moves_control_to_next_visible_piece_without_duplicate(self):
        self.run_js(r'''
          const v=draw(firstTarget()),c=v.comps[0];rcptSplit(v,c,c.rows[0],1);const parts=c.rows.filter(row=>row.orig===0),check=c.checkBoxes[0];
          check.focus();rcptTick(v,c,parts[0],true);rcptSetFilter(v,'todo');assert(parts[0].tile.hidden);assert(!parts[1].tile.hidden);
          assert(parts[1].checkHost.contains(check));assert(!parts[0].tile.contains(check));assert.equal(document.activeElement,check);onlyCanonical(c);
          rcptSetFilter(v,'all');assert(parts[0].checkHost.contains(check));assert(!parts[1].tile.contains(check));assert.equal(document.activeElement,check);
        ''')

    def test_selected_summary_inspector_and_other_split_strips_never_clone_verification_controls(self):
        self.run_js(r'''
          const v=draw(firstTarget()),c=v.comps[0],inputs=[...c.checkBoxes];rcptSplit(v,c,c.rows[0],1);const parts=c.rows.filter(row=>row.orig===0);
          rcptOpenSheet(v,c,parts[1]);const staticStrip=v.sheet.sheet.body.querySelector('.rcpt-row-checks');assert(staticStrip);assert.equal(staticStrip.querySelector('input'),null);
          const selectedStrip=v.selectedFacts.querySelector('.rcpt-row-checks');assert(selectedStrip);assert.equal(selectedStrip.querySelector('input'),null);
          assert.equal(parts[1].tile.querySelector('.rcpt-row-checks').querySelector('input'),null);onlyCanonical(c,inputs);noNestedControls(c);
          v.sheet.sheet.close();assert(parts[0].checkHost.contains(inputs[0]));onlyCanonical(c,inputs);
        ''')

    def test_draft_resume_reuses_new_controller_nodes_across_full_board_rebuild_without_saving_authority(self):
        self.run_js(r'''
          const v=draw(firstTarget()),c=v.comps[0];rcptSplit(v,c,c.rows[0],1);changeCheck(c,0,true);rcptChanged(v);
          const raw=[...store.values()].find(value=>value.includes('"comps"'));assert(raw);const draft=JSON.parse(raw);
          for(const key of ['checkHost','checkBoxes','checkLabels','check_targets','row_sha256','payload_sha256'])assert(!raw.includes(key));
          const next=draw(firstTarget()),fresh=next.comps[0],inputs=[...fresh.checkBoxes],labels=[...fresh.checkLabels];
          rcptApplyDraft(next,draft);assert.equal(fresh.rows.length,3);assert(fresh.checks[0]);assert.equal(fresh.checkBoxes[0],inputs[0]);
          assert.equal(fresh.checkLabels[0],labels[0]);assert(fresh.rows[0].checkHost.contains(inputs[0]));onlyCanonical(fresh,inputs);
          assert(fresh.rows.filter(row=>row.orig===0).every(row=>row.tile.querySelector('.rcpt-row-checks').textContent.includes('Row 1: 2 x Alpha')));
        ''')

    def test_stale_detached_profile_route_busy_or_reload_events_cannot_change_saved_check_state(self):
        self.run_js(r'''
          for(const mode of ['detached','retired','profile','route','busy','reload']){
            state.profile={id:'matt',name:'Matt'};state.may=null;const v=draw(),c=v.comps[0],check=c.checkBoxes[0];
            if(mode==='detached')check.remove();if(mode==='retired')draw();if(mode==='profile')state.profile={id:'user1',name:'User1'};
            if(mode==='route')routeToken++;if(mode==='busy')v.busy=true;if(mode==='reload')v.reloadRequired=true;
            check.checked=true;check.fire('change');assert.equal(c.checks[0],false,mode);assert.equal(check.checked,false,mode);
            assert(c.rows.every(row=>!row.ticked));assert.equal(c.rows[0].values.quantity,'2');assert.equal(c.rows[1].values.quantity,'1');
          }
        ''')

    def test_malformed_or_legacy_target_proof_keeps_both_canonical_controls_in_fallback(self):
        self.run_js(r'''
          for(const change of [c=>{delete c.check_targets;},c=>{c.check_targets=[null,null];},c=>{c.check_targets=[];},
            c=>{c.check_targets[0].row_sha256='b'.repeat(64);},c=>{c.check_targeting.available=false;},c=>{delete c.check_targeting.row_sha256s[1];}]){
            const d=targeted();change(d.components[0]);const v=draw(d),c=v.comps[0];
            for(const input of c.checkBoxes)assert(c.checkFallback.contains(input));onlyCanonical(c);noNestedControls(c);
            assert(c.rows.every(row=>!row.tile.querySelector('.rcpt-row-checks')));
          }
        ''')

    def test_direct_refresh_tile_parks_and_moves_same_focused_control_before_replacing_target(self):
        self.run_js(r'''
          const v=draw(),c=v.comps[0],row=c.rows[1],other=c.rows[0].tile,check=c.checkBoxes[0],inputs=[...c.checkBoxes];
          c.grid.replaceChild=(fresh,old)=>{old.replaceWith(fresh);return old;};check.focus();const old=row.tile;
          row.values.notes='A corrected local note';rcptRefreshTile(v,c,row);
          assert(row.tile!==old);assert.equal(c.rows[0].tile,other);assert(check.isConnected);assert(row.checkHost.contains(check));
          assert.equal(document.activeElement,check);assert.equal(check.checked,false);onlyCanonical(c,inputs);noNestedControls(c);
        ''')


if __name__ == "__main__":
    unittest.main()
