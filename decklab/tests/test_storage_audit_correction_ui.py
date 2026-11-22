"""Saved storage differences enter the normal correction tools and return to the right section."""
import json
import subprocess
import unittest

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


FIXTURE = SETUP + """
  as('matt', MAY.admin);
  const map = '#/collection?view=map', origin = 'audit-section', hash = 'a'.repeat(64);
  const elf = {name:'Fixture Elf', set:'fdn', collector_number:'1', finish:'nonfoil', quantity:4,
    condition:'NM', language:'EN', notes:'fixture note'};
  const foil = {...elf, finish:'foil', quantity:2};
  const other = {...elf, name:'Fixture Bear', collector_number:'2'};
  const rows = [elf, foil, other];
  const rowsData = (more = {}) => ({space:'home', editable:true, sha256:hash, rows, pictures:{},
    locations:{ready:true, sha256:'c'.repeat(64), rows:{[colKey(elf)]:'Row 1'}}, ...more});
  const difference = row => ({...row, key:colKey(row), expected:2, observed:1, estimated:true});
  const audit = differences => ({revision:1, audited_at:'2026-11-22T00:00:00Z', expected:2, observed:1,
    mismatch_rows:1, extra:0, missing:1, surplus:0, current:true, differences});
  const section = differences => ({id:origin, container:'Storage box', place:'Row 1', label:'White creatures',
    quantity:2, audit:audit(differences)});
  const next = () => { storageAuditCorrectionRoute(++routeToken); clear(main); };
  let current;
  const drawMap = (differences, returning = false) => {
    location.hash = map;
    if (returning) next();
    current = section(differences);
    const cv = drawCollectionStorageMap({space:'home', editable:true, ready:true, sections:[current,
      {id:'other-section', container:'Storage box', place:'Row 1', label:'Green creatures', quantity:1}],
      containers:[{name:'Storage box',sections:['Row 1']}]}, 'home', routeToken);
    return cv;
  };
  const printing = {name:'Fixture Elf', printings:[{set:'fdn',collector_number:'1',finishes:['nonfoil','foil']},
    {set:'abc',collector_number:'5',finishes:['nonfoil']}]};
  api = async path => {
    if (path.includes('/api/collection/storage-map')) return {space:'home', ready:true, editable:true, section:current,
      rows:[], expect:'attempt', excluded_names:[], scan:{available:false}};
    if (path.startsWith('/api/printings?')) return printing;
    throw Error('Unexpected API read '+path);
  };
  const writes = [];
  apiWrite = async (path, body) => { writes.push([path, body]); throw new Error('Unexpected write'); };
  const view = rowsArg => { next(); return drawCollectionRows(rowsArg || rowsData(), 'home', routeToken); };
  const auditLink = cv => cv.auditPanel.querySelector('a');
  const openAudit = async (diff, actionText) => {
    const cv = drawMap([diff]);
    cv.mapContent.querySelector('.col-map-section[data-section="audit-section"]').click();
    await flush();
    button(openDialog(), actionText).click();
    await flush();
  };
  const token = {front:'Fish', back:'Clue', set:'tblb', front_collector_number:'7', back_collector_number:'8',
    finish:'nonfoil', front_details:'1/1', back_details:''};
  const exact = {...token,key:'r0',quantity:4,notes:'Record kept',uses:[]};
  const wrong = {...exact,key:'r1',quantity:9,back_collector_number:'9'};
  const tokenData = {space:'home',sha256:hash,exists:true,sorted:true,rows:[wrong,exact],missing:[]};
  const openTokenCorrection = async () => {
    const diff = {...difference(elf), key:'token-'+hash, name:'Fish / Clue', manualLabel:'Fish 7 / Clue 8', token};
    await openAudit(diff,'Review token copies');
    assert.equal(location.hash,'#/tokens');
    next();
    return drawTokens(tokenData,routeToken,'home');
  };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class StorageAuditCorrectionUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_card_correction_starts_with_blank_owned_total_and_reopens_the_same_saved_section(self):
        self.run_js("""
          await openAudit(difference(elf),'Review collection copies');
          assert.equal(location.hash, '#/collection?view=rows');
          const cv = view();
          assert(cv.auditPanel.textContent.includes('FDN 1 · Non-foil'));
          assert(cv.auditPanel.textContent.includes('2 expected (estimate) · 1 counted'));
          assert.equal(auditLink(cv).getAttribute('href'), map);
          button(cv.auditPanel, 'Review owned total').click();
          await flush();
          const dialog = openDialog();
          const input = dialog.querySelector('input[aria-label="Total owned copies of this printing"]');
          assert.equal(input.value, '');
          assert.equal(dialog.querySelectorAll('.col-strip-tile').length, 1);
          assert(!button(dialog,'Foil'));
          button(dialog,'Save').click(); await flush();
          assert.equal(writes.length, 0);
          apiWrite = async (path, body) => {
            writes.push([path, body]);
            return {sha256:'b'.repeat(64), rows:[{...elf,quantity:5},foil,other]};
          };
          input.value = '5'; button(dialog,'Save').click(); await flush();
          assert.equal(writes[0][0], '/api/collection/save');
          same(writes[0][1].row, {...elf, quantity:5});
          assert(!('location' in writes[0][1]));
          const returned = drawMap([difference(elf)], true); await flush();
          assert.notEqual(returned.mapContent.querySelector('details[data-map-row]').getAttribute('open'), null);
          assert(openDialog().textContent.includes('White creatures'));
          assert(openDialog().textContent.includes('2 expected'));
          assert.equal(storageAuditCorrection, null);
        """)

    def test_location_correction_reviews_one_exact_row_even_with_a_filtered_list(self):
        self.run_js("""
          await openAudit(difference(elf),'Review collection copies');
          const cv = view();
          cv.rowSearch.value = 'Bear'; cv.rowSearch.fire('input');
          button(cv.auditPanel, 'Review storage location').click();
          const dialog = openDialog();
          same(dialog.querySelectorAll('[data-location-key]').map(node => node.getAttribute('data-location-key')), [colKey(elf)]);
          const input = dialog.querySelector('input'); input.value = 'Binder'; input.fire('input');
          apiWrite = async (path,body) => {
            writes.push([path,body]);
            return {...rowsData(),changed:1};
          };
          button(dialog,'Save 1 row').click(); await flush();
          assert.equal(writes[0][0], '/api/collection/locations/bulk');
          same(writes[0][1].keys, [{set:'fdn',collector_number:'1',finish:'nonfoil'}]);
          assert.equal(writes[0][1].location, 'Binder');
          assert(!('quantity' in writes[0][1]));
        """)

    def test_exact_extra_needs_an_explicit_add_and_stale_totals_are_never_reapplied(self):
        self.run_js("""
          const extra = {...difference(foil),expected:0,observed:1,estimated:false};
          await openAudit(extra,'Review collection copies');
          const cv = view(rowsData({rows:[elf,other]}));
          button(cv.auditPanel, 'Add this printing').click(); await flush();
          const dialog = openDialog(), input = dialog.querySelector('input[aria-label="Total owned copies of this printing"]');
          assert.equal(input.value, ''); assert(button(dialog,'Foil')); assert(!button(dialog,'Non-foil'));
          apiWrite = async (path,body) => { writes.push([path,body]); throw new ApiError(409,'Changed',rowsData()); };
          input.value = '2'; button(dialog,'Add').click(); await flush();
          assert.equal(writes.length,1);
          assert.equal(writes[0][1].row.finish,'foil');
          assert(!button(dialog,'Load the latest and add my card'));
          button(dialog,'Review current copies').click();
          assert(button(cv.auditPanel,'Review owned total')); assert(!button(cv.auditPanel,'Add this printing'));
          assert.equal(writes.length,1);
        """)

    def test_token_correction_matches_both_faces_and_typed_quantity_alone_is_sent(self):
        self.run_js("""
          const tokens = await openTokenCorrection();
          assert(tokens.auditPanel.textContent.includes('Total owned: 4')); assert(!tokens.auditPanel.textContent.includes('Total owned: 9'));
          button(tokens.auditPanel,'Review owned total').click();
          const dialog = openDialog(), count = dialog.querySelector('input[type="number"]');
          assert.equal(count.value, ''); assert(dialog.textContent.includes('Total owned token cards'));
          apiWrite = async (path,body) => { writes.push([path,body]); return {data:{...tokenData,rows:[wrong,{...exact,quantity:5}]}}; };
          count.value='5'; button(dialog,'Save').click(); await flush();
          assert.equal(writes[0][0],'/api/tokens/save');
          same(writes[0][1].base,tokBase(exact));
          same(writes[0][1].row,{...tokBase(exact),quantity:5});
          assert.equal(auditLink(tokens).getAttribute('href'),map);
        """)

    def test_leaving_tokens_closes_audit_edit_and_remove_sheets(self):
        self.run_js("""
          noteVisit = () => {}; syncShell = () => {}; showTerminology = () => {}; drawWho = () => {};
          let tokens = await openTokenCorrection();
          button(tokens.auditPanel,'Review owned total').click();
          const auditEditor = openDialog();
          location.hash = '#/help'; route();
          assert(!auditEditor.isConnected);
          assert.equal(storageAuditCorrection, null);

          tokens = await openTokenCorrection();
          button(tokens.auditPanel,'Review owned total').click();
          button(openDialog(),'Remove…').click();
          const remove = openDialog();
          const confirm = button(remove,'Remove');
          state.profile = null; route();
          assert(!remove.isConnected);
          assert.equal(storageAuditCorrection, null);
          confirm.click(); await flush();
          assert.equal(writes.length,0);
        """)

    def test_another_profile_or_address_retires_the_private_handoff(self):
        self.run_js("""
          await openAudit(difference(elf),'Review collection copies');
          as('user1',MAY.user1);
          const cv = view();
          assert(!cv.auditPanel);
          assert.equal(storageAuditCorrection,null);
          as('matt',MAY.admin);
          await openAudit(difference(elf),'Review collection copies');
          location.hash='#/tokens'; next();
          location.hash='#/collection?view=rows';
          assert(!view().auditPanel);
          assert.equal(writes.length,0);
        """)
