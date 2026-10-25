"""Collection lab keys follow live filtered rows without changing records."""
import unittest
from decklab.tests import test_collection_layout_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionKeysUiTests(unittest.TestCase):
    run_js = test_collection_layout_ui.CollectionLayoutUiTests.run_js

    def test_keys_move_live_selection_and_focus_without_wrapping(self):
        self.run_js("""
          const cv=draw(), sorted=colShownRows(cv);
          const press=key=>main.querySelector('.col-row-lab').querySelector('.table-wrap').fire('keydown',{key});
          assert(press('j').defaultPrevented);assert.equal(cv.selectedKey,colKey(sorted[0]));
          assert.equal(document.activeElement,tableRow(cv.selectedKey).querySelector('.col-open'));
          press('k');assert.equal(cv.selectedKey,colKey(sorted[0]));
          press('j');assert.equal(cv.selectedKey,colKey(sorted[1]));
          search('Beta');press('j');assert.equal(cv.selectedKey,'fdn|2|nonfoil');
          press('j');assert.equal(cv.selectedKey,'fdn|2|nonfoil');
          assert.equal(inspections.length,0);
        """)

    def test_navigation_crosses_pages_in_the_same_filtered_order(self):
        self.run_js("""
          const many=Array.from({length:105},(_,i)=>row('Card '+String(i).padStart(3,'0'),i));
          const cv=draw({rows:many,pictures:{}}),sorted=colShownRows(cv);
          colSelectRow(cv,colKey(sorted[99]));
          main.querySelector('.col-row-lab').querySelector('.table-wrap').fire('keydown',{key:'j'});
          assert.equal(cv.page,2);assert.equal(cv.selectedKey,colKey(sorted[100]));assert.equal(tableRows().length,5);
          assert.equal(document.activeElement,tableRow(cv.selectedKey).querySelector('.col-open'));
          main.querySelector('.col-row-lab').querySelector('.table-wrap').fire('keydown',{key:'k'});
          assert.equal(cv.page,1);assert.equal(cv.selectedKey,colKey(sorted[99]));
        """)

    def test_enter_opens_the_recorded_card_with_visible_focus_return_and_caption(self):
        self.run_js("""
          const cv=draw(),key='fdn|1|foil';colSelectRow(cv,key);
          const choice=tableRow(key).querySelector('.col-open');
          const event=main.querySelector('.col-row-lab').querySelector('.table-wrap').fire('keydown',{key:'Enter',target:choice});
          assert(event.defaultPrevented);assert.equal(inspections.length,1);
          assert.equal(inspections[0].card,cv.pictures[key]);assert(inspections[0].trigger.isConnected);
          assert.equal(inspections[0].trigger.closest('tr').getAttribute('data-key'),key);
          const group=viewerGroup(inspections[0].trigger);assert.equal(group.items[group.index].card,cv.pictures[key]);
          assert(group.items[group.index].caption.includes('picture of another printing'));
          assert(!group.items.some(item=>!item.card));
        """)

    def test_enter_restores_an_off_page_selection_before_opening_its_card(self):
        self.run_js("""
          const many=Array.from({length:105},(_,i)=>row('Card '+String(i).padStart(3,'0'),i));
          const pics=Object.fromEntries(many.map(item=>[colKey(item),picture(item.name,item.collector_number)]));
          const cv=draw({rows:many,pictures:pics}),key=colKey(colShownRows(cv)[0]);
          colSelectRow(cv,key);cv.page=2;drawColRowList(cv);
          const edits=[];openCollectionSheet=(...args)=>edits.push(args);
          main.querySelector('.col-row-lab').querySelector('.table-wrap').fire('keydown',{key:'Enter'});
          assert.equal(cv.page,1);assert.equal(cv.selectedKey,key);assert.equal(edits.length,0);
          assert.equal(inspections.length,1);assert.equal(inspections[0].card,cv.pictures[key]);
          assert(inspections[0].trigger.isConnected);
        """)

    def test_modifiers_headers_text_fields_stale_targets_and_viewers_keep_their_guards(self):
        self.run_js("""
          const cv=draw(),region=main.querySelector('.col-row-lab').querySelector('.table-wrap');
          const fire=(key,extra={})=>region.fire('keydown',{key,...extra});
          assert(!fire('j',{ctrlKey:true}).defaultPrevented);
          assert(!fire('j',{target:main.querySelector('#col-row-search')}).defaultPrevented);
          assert(!fire('Enter',{target:main.querySelector('.th-sort')}).defaultPrevented);
          cv.busy=true;fire('j');cv.busy=false;assert.equal(cv.selectedKey,null);
          routeToken++;fire('j');routeToken--;assert.equal(cv.selectedKey,null);
          state.profile={id:'other'};fire('j');assert.equal(cv.selectedKey,null);
          state.profile={id:cv.profile};drawColRowList(cv);fire('j');assert.equal(cv.selectedKey,null,'detached region stays inert');
          assert.equal(inspections.length,0);
        """)

    def test_unknown_cards_use_current_edit_permission_or_read_only_preview(self):
        self.run_js("""
          const cv=draw({pictures:{},editable:false});colSelectRow(cv,'fdn|2|nonfoil');
          main.querySelector('.col-row-lab').querySelector('.table-wrap').fire('keydown',{key:'Enter',target:tableRow(cv.selectedKey).querySelector('.col-open')});
          assert.equal(document.activeElement,preview());assert.equal(inspections.length,0);
          const edits=[];openCollectionSheet=(view,row)=>edits.push([view,row]);
          const writable=draw({pictures:{}});colSelectRow(writable,'fdn|2|nonfoil');
          main.querySelector('.col-row-lab').querySelector('.table-wrap').fire('keydown',{key:'Enter',target:tableRow(writable.selectedKey).querySelector('.col-open')});
          assert.equal(edits.length,1);assert.equal(edits[0][1].name,'Beta');
        """)
