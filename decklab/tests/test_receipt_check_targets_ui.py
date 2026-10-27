"""Saved original-order-row associations are context; verification stays component-wide."""
import unittest

from decklab.tests import test_receipts_ui
from decklab.tests.test_workspace_ui import NODE


SETUP = r'''
  const targeted = () => {
    const data=delivery(), c=data.components[0];
    c.rows.forEach(row=>{row.condition='NM';row.language='en';row.notes='';});
    c.rows[1].name='Alpha';c.rows[1].collector_number='2';
    c.checks=['Check exact art','General Alpha reminder'];
    c.check_targeting={available:true,payload_sha256:'a'.repeat(64),row_sha256s:['b'.repeat(64),'c'.repeat(64)]};
    c.check_targets=[{row:2,row_sha256:'c'.repeat(64)},null];
    return data;
  };
  const draw = (data=targeted()) => {clear(main);return drawReceipt(data,routeToken);};
  const canonicalChecks = c => c.section.querySelectorAll('.rcpt-check').map(label=>label.querySelector('input'));
'''


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ReceiptCheckTargetUiTests(unittest.TestCase):
    def run_js(self, scenario):
        test_receipts_ui.ReceiptBoardTests.run_js(self, SETUP + scenario, draw=False)

    def test_only_proved_original_row_gets_the_same_canonical_component_checkbox(self):
        self.run_js(r'''
          let reads=0,writes=0;api=async()=>{reads++;};apiWrite=async()=>{writes++;};
          const v=draw(),c=v.comps[0];
          assert.equal(c.rows[0].tile.querySelector('.rcpt-row-checks'),null);
          const strip=c.rows[1].tile.querySelector('.rcpt-row-checks');assert(strip);
          assert(strip.textContent.includes('Row 2: 1 x Alpha'));
          assert(strip.textContent.includes('original recorded order row'));
          assert(strip.textContent.includes('whole part'));assert(strip.textContent.includes('Check exact art'));
          assert(!strip.textContent.includes('General Alpha reminder'));assert.equal(strip.querySelector('input'),c.checkBoxes[0]);
          assert.equal(canonicalChecks(c).length,2);assert(canonicalChecks(c).every(Boolean));
          assert.equal(rcptFlag(c,c.rows[0]),'');assert.equal(rcptFlag(c,c.rows[1]),'Check exact art');
          assert.equal(reads,0);assert.equal(writes,0);
        ''')

    def test_legacy_name_and_token_pair_text_never_associate_general_checks(self):
        self.run_js(r'''
          const d=targeted();delete d.components[0].check_targets;delete d.components[0].check_targeting;
          d.components[0].checks=['Check Alpha exact art'];const v=draw(d),c=v.comps[0];
          assert.equal(main.querySelector('.rcpt-row-checks'),null);assert(c.section.textContent.includes('Check Alpha exact art'));
          c.rows.forEach(row=>assert.equal(rcptFlag(c,row),''));
          const token={c:{kind:'tokens',status:'pending',checks:['Confirm Bird // Golem pairing'],
            rows:[{front:'Bird',back:'Golem'}]},kind:'tokens',checks:[false]};
          assert.equal(rcptFlag(token,{orig:0,values:{front:'Bird',back:'Golem',notes:''}}),'');
        ''')

    def test_malformed_or_stale_proofs_remain_general_without_index_shifts(self):
        self.run_js(r'''
          for(const mutate of [
            c=>{c.check_targets=[];},c=>{c.check_targets.length=3;},c=>{delete c.check_targets[0];},
            c=>{c.check_targets[0]={row:0,row_sha256:'c'.repeat(64)};},
            c=>{c.check_targets[0]={row:3,row_sha256:'c'.repeat(64)};},
            c=>{c.check_targets[0]={row:'2',row_sha256:'c'.repeat(64)};},
            c=>{c.check_targets[0].row_sha256='b'.repeat(64);},c=>{c.check_targets[0].row_sha256='bad';},
            c=>{c.check_targeting.available=false;},c=>{c.check_targeting.payload_sha256=null;},
            c=>{c.check_targeting.row_sha256s=['b'.repeat(64)];},c=>{c.check_targeting.row_sha256s[1]='bad';}]) {
            const d=targeted();mutate(d.components[0]);const v=draw(d),c=v.comps[0];
            assert.equal(main.querySelector('.rcpt-row-checks'),null);
            assert.equal(canonicalChecks(c).length,2);
            assert(c.section.textContent.includes('Check exact art'));c.rows.forEach(row=>assert.equal(rcptFlag(c,row),''));
          }
        ''')

    def test_local_edited_and_split_parts_keep_original_row_label_and_component_verification(self):
        self.run_js(r'''
          const v=draw(),c=v.comps[0],r=c.rows[1];
          r.values.name='Changed display';r.values.collector_number='99';
          const part={...r,key:++rcptKeys,values:{...r.values,quantity:'1'}};c.rows.push(part);
          rcptDrawGrid(v,c);
          for(const row of [r,part]) {
            const strip=row.tile.querySelector('.rcpt-row-checks');assert(strip);
            assert(strip.textContent.includes('Row 2: 1 x Alpha'));assert(!strip.textContent.includes('Changed display'));
            assert(strip.textContent.includes('split pieces share'));
          }
          assert.equal([r,part].filter(row=>row.tile.querySelector('.rcpt-row-checks').querySelector('input')).length,1);
          assert.equal(canonicalChecks(c).length,2);
          c.rows[0].ticked=true;assert.equal(rcptRequest(v).components[0].verified,false);
          assert(rcptClientBlockers(v).some(x=>x.text==='Check not ticked: Check exact art'));
          c.checks=[true,true];assert.equal(rcptRequest(v).components[0].verified,true);
          assert.deepEqual(rcptRequest(v).components[0].take,[{row:1}]);
          assert(!JSON.stringify(rcptRequest(v)).includes('row_sha256'));
        ''')

    def test_checking_canonical_control_refreshes_attention_and_preserves_focus(self):
        self.run_js(r'''
          const v=draw(),c=v.comps[0];c.pictures[0].exact=true;c.pictures[1].exact=true;
          rcptSetFilter(v,'attention');assert(c.rows[0].tile.hidden);assert(!c.rows[1].tile.hidden);
          const check=c.checkBoxes[0];check.focus();check.checked=true;check.fire('change');
          assert.equal(document.activeElement,check);assert(c.rows[1].tile.hidden);
          assert.equal(rcptFlag(c,c.rows[1]),'');assert.equal(c.checks[0],true);
          assert.equal(canonicalChecks(c).length,2);
          assert.equal(c.rows[1].tile.querySelectorAll('.rcpt-row-checks').length,1);
        ''')

    def test_real_split_merge_and_undo_keep_one_original_association(self):
        self.run_js(r'''
          const d=targeted();d.components[0].check_targets[0]={row:1,row_sha256:'b'.repeat(64)};
          const v=draw(d),c=v.comps[0],first=c.rows[0];rcptSplit(v,c,first,1);
          assert.equal(c.rows.length,3);assert.equal(c.rows.filter(row=>row.orig===0).length,2);
          for(const row of c.rows.filter(row=>row.orig===0))assert(row.tile.querySelector('.rcpt-row-checks').textContent.includes('Row 1: 2 x Alpha'));
          assert.equal(canonicalChecks(c).length,2);await rcptMerge(v,c,c.rows[1]);
          assert.equal(c.rows.length,2);assert(c.rows[0].tile.querySelector('.rcpt-row-checks'));
          document.querySelector('#toast-undo').querySelector('button').click();
          assert.equal(c.rows.length,3);assert.equal(c.rows.filter(row=>row.tile.querySelector('.rcpt-row-checks')).length,2);
          assert.equal(canonicalChecks(c).length,2);
        ''')

    def test_paired_token_edited_faces_keep_saved_row_provenance_without_new_association(self):
        self.run_js(r'''
          const d=targeted(),c=d.components[0];c.kind='tokens';c.fields=['front','back','set','front_collector_number','back_collector_number','finish','quantity','front_details','back_details','notes'];
          c.rows=[{front:'Bird',back:'Golem',set:'tst',front_collector_number:'1',back_collector_number:'2',finish:'foil',quantity:'3',front_details:'',back_details:'',notes:''}];
          c.pictures=[];c.decks=null;c.checks=['Confirm the physical reverse'];
          c.check_targeting.row_sha256s=['b'.repeat(64)];c.check_targets=[{row:1,row_sha256:'b'.repeat(64)}];
          const v=draw(d),comp=v.comps[0],row=comp.rows[0];
          row.values.front='Food';row.values.back='Treasure';rcptRowChanged(v,comp,row);
          const strip=row.tile.querySelector('.rcpt-row-checks');assert(strip.textContent.includes('3 x Bird // Golem'));
          assert(!strip.textContent.includes('Food'));assert(!strip.textContent.includes('Treasure'));
          assert.equal(rcptFlag(comp,row),'Confirm the physical reverse');assert.equal(canonicalChecks(comp).length,1);
          assert.equal(strip.querySelector('input'),comp.checkBoxes[0]);
        ''')

    def test_inspection_selected_panel_and_list_share_read_only_original_context(self):
        self.run_js(r'''
          const v=draw(),c=v.comps[0],r=c.rows[1];
          rcptOpenSheet(v,c,r);assert(v.sheet.sheet.body.querySelector('.rcpt-row-checks'));
          assert(v.selectedFacts.querySelector('.rcpt-row-checks'));
          assert.equal(v.sheet.sheet.body.querySelector('.rcpt-row-checks').querySelector('input'),null);
          v.sheet.sheet.close();v.layout='list';rcptRefreshAll(v);
          assert(r.tile.getAttribute('class').includes('rcpt-row'));assert(r.tile.querySelector('.rcpt-row-checks'));
          assert.equal(canonicalChecks(c).length,2);
        ''')

    def test_drafts_do_not_carry_association_authority_and_resume_keeps_original_proof(self):
        self.run_js(r'''
          const v=draw(),c=v.comps[0];c.checks=[true,false];c.rows[1].values.collector_number='99';
          rcptChanged(v);const raw=[...store.values()].find(value=>value.includes('"comps"'));assert(raw);
          assert(!raw.includes('check_targets'));assert(!raw.includes('row_sha256'));assert(!raw.includes('payload_sha256'));
          const draft=JSON.parse(raw);const next=draw();rcptApplyDraft(next,draft);
          assert.equal(next.comps[0].checks[0],true);
          const strip=next.comps[0].rows[1].tile.querySelector('.rcpt-row-checks');assert(strip);
          assert(strip.textContent.includes('TST 2'));assert(!strip.textContent.includes('TST 99'));
        ''')

    def test_nonpending_product_and_read_only_checks_stay_visible_without_controls_in_strips(self):
        self.run_js(r'''
          for(const kind of ['product','cards']) {
            const d=targeted(),c=d.components[0];c.kind=kind;c.status='received';c.items=[];
            state.may={admin:false,receipts:false};const v=draw(d);
            assert.equal(main.querySelector('.rcpt-row-checks'),null);
            assert(main.textContent.includes('Check exact art'));
            assert.equal(main.querySelector('.rcpt-check input'),null);
          }
        ''')
