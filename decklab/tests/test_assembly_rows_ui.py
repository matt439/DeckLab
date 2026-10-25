"""Lab row projection retains original physical tasks, viewer entries and list-only finish intent."""
import unittest

from decklab.tests import test_assembly_completion_ui as completion
from decklab.tests.test_workspace_ui import NODE, WEB

SETUP = """
  const longUnknown='Unknown card with an intentionally long unbroken name for wrapping';
  const donor='A donor deck with an intentionally very long saved title';
  const rowData=()=>{const a=item(),b=item('casual/b','owned');
    a.steps=[{name:'Alpha',need:5,keep:1,storage:3,transfers:[{from:'casual/donor',from_title:donor,quantity:1}],waiting:0,missing:0},
      {name:longUnknown,need:2,keep:0,storage:2,transfers:[],waiting:0,missing:0}];
    a.basics=[{name:'Forest',quantity:4}];a.returns=[{name:'Beta',quantity:2}];
    a.standins={rows:[{for:'Spare marker fixture',qty:1,using:false}]};
    a.finishes={Alpha:[{finish:'foil',quantity:2},{finish:'nonfoil',quantity:3}],Forest:[{finish:'etched',quantity:4}],Beta:[{finish:'foil',quantity:2}]};
    b.steps=[{name:'Beta',need:1,keep:0,storage:1,transfers:[],waiting:0,missing:0}];
    const data=plan([a,b]);data.cards.Beta={...beta,img:'/img/b/1/normal',img_small:'/img/b/1/small'};
    data.cards.Forest={...alpha,name:'Forest',img:null,img_small:null,type_line:'Basic Land'};return data;};
  const openRows=(narrow=false)=>{window.matchMedia('(min-width: 1000px)').matches=!narrow;
    const data=rowData();drawAssembly(data,routeToken);return packingProgressView;};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AssemblyRowsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        completion.AssemblyCompletionUiTests.run_js(self, SETUP + scenario)

    def test_every_original_action_keeps_its_copy_quantity_and_list_context(self):
        self.run_js("""
          const v=openRows();await settle();same(v.ticks.map(t=>t.count),[3,2,1,4,1,2,1]);
          assert.equal(v.bar.progress.copies.textContent,'0 / 14');
          for(const tick of v.ticks){assert(tick.tile.contains(tick.node));assert.equal(tick.node.getAttribute('data-pack-count'),String(tick.count));
            assert.equal(tick.tile.querySelector('.pack-row-qty').textContent,String(tick.count));
            assert.equal(tick.tile.querySelector('.pack-row-qty').getAttribute('aria-hidden'),'true');
            assert.equal((tick.node.events.get('click')||[]).length,1);}
          const moved=v.ticks.find(t=>t.node.getAttribute('data-pack-tick').startsWith('move|'));
          assert(moved.tile.querySelector('.card-tile-meta').textContent.includes('From '+donor));
          assert(moved.tile.querySelector('.pack-row-finish').textContent.includes('List: 2 foil'));
          const returned=v.ticks.find(t=>t.node.getAttribute('data-pack-tick').startsWith('return|'));
          assert(!returned.tile.querySelector('.pack-row-finish'));assert(!returned.tile.querySelector('.card-tile-chips'));
          const basics=v.ticks.find(t=>t.node.getAttribute('data-pack-tick').startsWith('basic|'));
          assert.equal(basics.tile.querySelector('.pack-row-finish').textContent,'List: etched');
          assert.equal(v.ticks[0].tile.querySelector('.card-tile-qty').textContent,String.fromCodePoint(0xd7)+'3');
        """)

    def test_unknown_and_known_no_art_keep_original_trigger_semantics_and_viewer_order(self):
        self.run_js("""
          const v=openRows(true);await settle();const entries=v.packViewerEntries.slice();
          same(entries.map(e=>e.card.name),['Alpha','Alpha','Forest','Beta','Beta']);
          const unknown=v.ticks.find(t=>t.node.getAttribute('data-pack-tick')==='pull|'+longUnknown);
          assert.equal(unknown.tile.querySelector('.card-tile-open').tag,'div');assert(!entries.some(e=>unknown.tile.contains(e.trigger)));
          assert(unknown.node.isConnected);const noArt=entries.find(e=>e.card.name==='Forest');
          assert.equal(noArt.trigger.tag,'button');assert(!noArt.trigger.querySelector('.card-tile-img'));
          const calls=[];openCardViewer=(items,index,opts)=>{calls.push({items,index,opts});return null;};
          noArt.trigger.click();assert.equal(calls[0].index,2);assert(calls[0].opts.trigger===noArt.trigger);
          same(calls[0].items.map(e=>e.card.name),['Alpha','Alpha','Forest','Beta','Beta']);
          assert(calls[0].items[0].caption.includes('Deck list: 2 foil'));
          assert(calls[0].items[1].caption.includes(donor));assert(!calls[0].items[3].caption.includes('Deck list'));
          v.switcher.panels[1].button.click();entries[4].trigger.click();assert.equal(calls[1].index,4);
          assert(v.packViewerEntries.every((entry,index)=>entry===entries[index]));
        """)

    def test_bulk_done_and_undo_keep_projection_nodes_scope_and_open_steps(self):
        self.run_js("""
          const v=openRows(true);await settle();const scope=v.progress.scope,ids=v.ticks.map(t=>t.id);
          const quantities=v.ticks.map(t=>t.tile.querySelector('.pack-row-qty')),fold=v.switcher.panels[0].node.querySelector('.pack-fold');
          fold.open=true;let undo;showToast=(text,opts)=>{undo=opts?.undo;};v.bulk[0].button.click();await settle();
          assert(v.ticks.slice(0,6).every(t=>t.done&&t.tile.classList.contains('is-ticked')));assert(!v.ticks[6].done);
          assert.equal(v.bar.progress.copies.textContent,'13 / 14');assert(fold.open);assert(!packCanFinish(v));
          v.switcher.panels[1].button.click();undo();await settle();assert(v.ticks.every(t=>!t.done));assert(fold.open);
          assert.equal(v.progress.scope,scope);same(v.ticks.map(t=>t.id),ids);
          assert(v.ticks.every((t,i)=>t.tile.querySelector('.pack-row-qty')===quantities[i]));
          assert(v.switcher.panels.every(p=>p.node.isConnected));
        """)

    def test_visual_projection_leaves_requested_finish_data_and_captions_unchanged(self):
        self.run_js("""
          const data=rowData(),before=JSON.stringify(data);drawAssembly(data,routeToken);await settle();const v=packingProgressView;
          assert.equal(JSON.stringify(data),before);const mixed=v.packViewerEntries[0];
          assert.equal(mixed.trigger.getAttribute('aria-label'),'Alpha. Pull 3 from storage for Elves. Deck list: 2 foil · 3 nonfoil');
          assert.equal(viewerCards.get(mixed.trigger).caption,mixed.caption);
          const intent=mixed.trigger.querySelector('.pack-row-finish');assert.equal(intent.getAttribute('aria-hidden'),'true');
          assert.equal(intent.getAttribute('title'),'Deck list: 2 foil · 3 nonfoil');
          const tick=v.ticks[0],original=tick.node;tick.node.focus();tick.node.click();await settle();
          assert(tick.node===original&&document.activeElement===original);assert(tick.done);assert.equal(tick.node.getAttribute('aria-pressed'),'true');
        """)


    def test_checked_image_error_retains_fallback_words_and_external_name(self):
        self.run_js("""
          const v=openRows(true);await settle();const tick=v.ticks[0],pic=tick.tile.querySelector('.card-tile-pic');
          const words=pic.querySelector('.card-tile-text'),image=pic.querySelector('.card-tile-img');
          const name=tick.tile.querySelector('.card-tile-name'),label=tick.tile.querySelector('.card-tile-open').getAttribute('aria-label');
          assert(image&&words);assert.equal(words.getAttribute('aria-hidden'),'true');tick.node.click();await settle();
          assert(tick.tile.classList.contains('is-ticked'));assert(pic.querySelector('.card-tile-text')===words);
          image.fire('error');assert(!pic.querySelector('.card-tile-img'));assert(pic.querySelector('.card-tile-text')===words);
          assert(words.isConnected);assert(words.textContent.includes('Alpha'));assert(name.isConnected&&name.textContent==='Alpha');
          assert.equal(tick.tile.querySelector('.card-tile-open').getAttribute('aria-label'),label);
          const noArt=v.packViewerEntries.find(e=>e.card.name==='Forest').trigger;
          assert(!noArt.querySelector('.card-tile-img'));assert(noArt.querySelector('.card-tile-text').textContent.includes('Forest'));
          const unknown=v.ticks.find(t=>t.node.getAttribute('data-pack-tick')==='pull|'+longUnknown).tile;
          assert(!unknown.querySelector('.card-tile-img'));assert(unknown.querySelector('.card-tile-text').textContent.includes(longUnknown));
        """)


class AssemblyRowsSourceTests(unittest.TestCase):
    def test_ghost_fallback_rule_requires_checked_packing_art_and_an_actual_image_child(self):
        css=(WEB/'assembly.css').read_text(encoding='utf-8')
        selector='.pack-tiles .card-tile.is-ticked .card-tile-pic:has(> .card-tile-img) > .card-tile-text'
        rule=css.split(selector+' {',1)[1].split('}',1)[0]
        self.assertEqual(rule.strip(),'visibility: hidden;')
        self.assertNotIn('.card-tile-text { visibility: hidden;',css.replace(selector+' { visibility: hidden; }',''))

    def test_lab_projection_binds_owner_row_thumbnail_badges_and_full_row_focus(self):
        css=(WEB/'assembly.css').read_text(encoding='utf-8')
        lab=css.rsplit('@media (min-width: 1000px)',1)[1]
        self.assertIn('min-height: 46px',lab)
        self.assertIn('grid-template-columns: 28px minmax(0, 1fr) auto',lab)
        self.assertIn('width: 20px; height: 20px',lab)
        self.assertIn('font-family: var(--font-mono)',lab)
        self.assertIn('.card-tile:has(> .card-tile-open:focus-visible)',lab)
        self.assertIn('white-space: normal; overflow: visible',lab)
        self.assertIn('width: 28px; height: 28px',css)
        self.assertIn('background: var(--surface-chip); color: var(--ink-2)',css)

    def test_done_styles_are_scoped_readable_and_do_not_dim_controls_or_auto_fold(self):
        css=(WEB/'assembly.css').read_text(encoding='utf-8')
        projection=css.split('/* The original viewer/tick nodes',1)[1]
        casual,lab=projection.split('@media (min-width: 1000px)',1)
        self.assertIn('.card-tile-img { opacity: .42; filter: none; }',casual)
        self.assertIn('width: 40px; height: 40px',casual)
        self.assertIn(':has(> .card-tile-img)::before',casual)
        self.assertNotIn('@media',casual)
        self.assertIn('.card-tile-img { opacity: 1; filter: none; }',lab)
        self.assertIn('color: var(--ink-3); font-weight: var(--fw-medium)',css)
        self.assertNotIn('text-decoration: line-through',css)
        self.assertNotIn('.card-tile.is-ticked { opacity',css)
        self.assertIn('.pack-row-qty, .pack-row-finish, .pack-row-meta { display: none; }',css)

    def test_lab_long_context_and_placeholder_override_shared_tile_constraints(self):
        css=(WEB/'assembly.css').read_text(encoding='utf-8')
        lab=css.rsplit('@media (min-width: 1000px)',1)[1]
        self.assertIn('.card-tile-meta .meta-part { white-space: normal; overflow-wrap: anywhere; }',lab)
        self.assertIn('display: block; -webkit-line-clamp: unset; -webkit-box-orient: initial',lab)
        self.assertIn('background: var(--track)',lab)
        placeholder=lab.split('.pack-tiles .card-tile-text {',1)[1].split('}',1)[0]
        self.assertIn('clip-path: inset(50%)',placeholder)
        self.assertNotIn('display: none',placeholder)
