"""The dense queue uses one live table/card projection over the same guarded queue controls."""
import unittest

from decklab.tests import test_shopping_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingQueueTableInteractionTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js

    def run_queue_js(self, scenario):
        self.run_js("""
          state.may = {admin: true, orders: true, see_inventory: ['home']};
          const cardData = name => ({name, type_line:'Creature', mana_cost:'', img:'/img/test/1/normal', img_small:'/img/test/1/small'});
          const data = queue => ({...empty, queue_revision:'q1', to_buy:queue});
          const qrow = (name, n, extra={}) => row(name, {queue_row:n, card:cardData(name), ...extra});
          const density = lab => {const query=window.matchMedia(SHOP_QUEUE_LAB); query.matches=lab; query.fire('change');};
          const entry = n => main.querySelectorAll('[data-shop-queue]').find(node=>Number(node.getAttribute('data-shop-queue'))===n);
          const edit = n => main.querySelectorAll('.shop-queue-edit').find(node=>Number(node.dataset.queueRow)===n);
          const move = n => main.querySelectorAll('.shop-category-move').find(node=>Number(node.dataset.queueRow)===n);
          const viewTrigger = n => entry(n).querySelector('.card-row');
          const choose = value => { const radio=main.querySelectorAll('.shop-store-radio').find(node=>node.value===value);
            radio.checked=true; radio.fire('change'); return radio; };
          const goMove = (n, label) => {move(n).click(); entry(n).querySelectorAll('[role=menuitem]').find(node=>node.textContent===label).click();};
          const settle = async () => {for(let i=0;i<8;i++) await Promise.resolve();};
          const deferred = () => {let resolve,reject; const promise=new Promise((a,b)=>{resolve=a;reject=b}); return {promise,resolve,reject};};
          toast=()=>{};
        """ + scenario)

    def test_table_has_real_group_rows_exact_intent_ids_and_visible_research_facts(self):
        self.run_queue_js("""
          density(true);
          const queue=[qrow('Deferred',1,{state:'deferred',quantity:4}),
            qrow('Reprint',2,{state:'waiting_for_reprint', printing:'exact',set:'fdn',collector_number:'7',finish:'foil'}),
            qrow('Ready',3,{listed_aud:'0',listed_at:' Store ',checked:'2026-10-24',in_stock:'yes',deck:{id:'casual/otters',title:'Otters'}}),
            qrow('Stock',4,{state:'waiting_for_stock',in_stock:'no'}), qrow('Unknown',5,{state:'legacy',card:null})];
          const before=JSON.stringify(queue); drawShopping(data(queue));
          const table=main.querySelector('.shop-queue-table'); assert(table);
          same(table.querySelector('thead').querySelectorAll('th').map(node=>node.textContent),
            ['Card','Printing','For','Qty','Ref AUD','Shop','Stock','Checked','Actions']);
          assert.equal(table.querySelector('.shop-q-head-stock').getAttribute('aria-label'),'Stock when checked');
          assert(table.querySelector('thead').querySelectorAll('th').every(node=>node.getAttribute('scope')==='col'));
          same(table.querySelectorAll('.group-row').map(node=>node.textContent), ['Ready · 1 row','Waiting · 2 rows','Deferred · 1 row','State not recorded · 1 row']);
          assert(table.querySelectorAll('.group-row').every(node=>node.querySelector('th').getAttribute('colspan')==='9' && node.querySelector('th').getAttribute('scope')==='rowgroup'));
          assert.equal(table.querySelectorAll('tbody').length,4);
          assert(table.querySelectorAll('tbody').every(node=>node.children[0].getAttribute('class')==='group-row'));
          assert(table.children.every(node=>['caption','thead','tbody'].includes(node.tag)));
          assert(table.querySelector('tbody').children.every(node=>node.tag==='tr'));
          same(table.querySelectorAll('[data-shop-queue]').map(node=>Number(node.getAttribute('data-shop-queue'))), [3,2,4,1,5]);
          assert.equal(entry(3).querySelector('.shop-q-price').textContent,'0.00');
          assert.equal(entry(3).querySelector('.shop-q-shop').textContent,'Store');
          assert.equal(entry(3).querySelector('.shop-q-checked').textContent,'2026-10-24');
          assert.equal(entry(3).querySelector('.shop-q-stock').textContent,'In stock');
          assert.equal(entry(3).querySelector('.shop-queue-deck').getAttribute('href'),'#/deck?id=casual%2Fotters&v=target');
          assert.equal(entry(2).querySelector('.shop-q-printing-line').querySelector('.sr-only').textContent,'Exact: FDN 7 foil');
          assert.equal(entry(2).querySelector('.shop-q-printing').querySelector('.chip-foil').textContent,'Foil');
          assert.equal(entry(2).querySelector('.shop-q-reason').textContent,'for a reprint');
          assert(entry(4).querySelector('.shop-q-stock').textContent.includes('Out of stock'));
          assert(entry(5).querySelector('.shop-q-price').textContent.includes('Reference price not recorded'));
          assert(entry(5).querySelector('.shop-q-shop').textContent.includes('Shop not recorded'));
          assert(entry(5).querySelector('.shop-q-checked').textContent.includes('Check date not recorded'));
          assert(entry(5).querySelector('.shop-q-stock').textContent.includes('Stock not recorded'));
          assert.equal(main.querySelectorAll('[data-viewer]').length,4);
          assert.equal(main.querySelectorAll('.shop-queue-edit').length,5);
          assert.equal(JSON.stringify(queue),before);
          assert(!main.textContent.includes('A$0.00'));
        """)

    def test_density_roundtrip_preserves_single_viewer_and_control_identity_and_focus(self):
        self.run_queue_js("""
          const view=drawShopping(data([qrow('Alpha',1,{notes:'Keep this note'})]));
          const trigger=viewTrigger(1), editor=edit(1), mover=move(1), actions=entry(1).querySelector('.shop-queue-actions');
          trigger.focus(); density(true);
          assert(main.querySelector('.shop-queue-table')); assert(viewTrigger(1)===trigger);
          assert(document.activeElement===trigger); assert(edit(1)===editor && move(1)===mover);
          assert(entry(1).querySelector('.shop-queue-actions')===actions);
          trigger.click(); assert(inspections.at(-1).trigger===trigger);
          assert.equal(viewerGroup(trigger).items.length,1);
          const more=entry(1).querySelector('.shop-q-more'); more.click();
          assert.equal(more.getAttribute('aria-expanded'),'true');
          assert.equal(main.querySelector('.shop-q-extra').hidden,false);
          editor.focus(); density(false);
          assert.equal(main.querySelector('.shop-queue-table'),null);
          assert(viewTrigger(1)===trigger && edit(1)===editor && move(1)===mover);
          assert(document.activeElement===editor);
          assert.equal(trigger.getAttribute('aria-label'),'Alpha, 1 copy');
          density(true); assert.equal(main.querySelector('.shop-q-extra').hidden,false);
          main.querySelector('.shop-q-more').focus(); density(false);
          assert(document.activeElement===trigger, 'a table-only disclosure returns to the same visible card trigger');
          density(true);
          assert.equal(main.querySelectorAll('.shop-queue-write').filter(node=>Number(node.dataset.queueRow)===1).length,2);
          assert.equal(main.querySelectorAll('[data-viewer]').length,1);
        """)

    def test_open_menu_closes_on_resize_and_same_trigger_is_focused_and_menu_is_positioned(self):
        self.run_queue_js("""
          density(true); drawShopping(data([qrow('Alpha',1)]));
          const button=move(1), menu=entry(1).querySelector('.menu');
          button.box={left:2300,right:2355,top:1250,bottom:1280,width:55,height:30};
          menu.box={left:0,right:240,top:0,bottom:250,width:240,height:250};
          button.click(); assert.equal(menu.hidden,false);
          assert.equal(menu.style.left,'2297px'); assert.equal(menu.style.top,'1042px');
          density(false); assert.equal(menu.hidden,true); assert(document.activeElement===button);
          assert(move(1)===button);
          assert.equal(menu.style.left,''); assert.equal(menu.style.top,''); assert.equal(menu.style.translate,'');
          button.click(); assert.equal(menu.hidden,false); assert.equal(menu.style.top,'');
        """)

    def test_pending_move_resize_and_matching_reveal_keep_writes_disabled_and_focus_new_saved_row(self):
        self.run_queue_js("""
          const pending=deferred(), writes=[];
          apiWrite=(path,body)=>{writes.push(body);return pending.promise};
          const queue=[qrow('Now',1),...Array.from({length:14},(_,i)=>qrow('Later '+i,i+2,
            {state:'long_term',for:'Later',listed_at:i===13?'Shop':'Other'}))];
          const view=drawShopping(data(queue)); goMove(1,'Long-term plan');
          density(true); choose('shop:Shop');
          assert.equal(main.querySelectorAll('[data-shop-queue]').length,15);
          assert(main.querySelectorAll('.shop-queue-write').every(node=>node.disabled));
          pending.resolve({revision:'q2'}); await settle();
          assert.equal(view.data.queue_revision,'q2'); assert.equal(queue[0].state,'long_term');
          assert(document.activeElement===move(1)); assert(!move(1).disabled);
          assert(move(1).scrolled>0); assert.equal(writes[0].row,1); assert.equal(writes[0].expect,'q1');
          assert.equal(main.querySelectorAll('[data-viewer]').length,15);
        """)

    def test_conflict_alert_and_retry_survive_density_changes_without_enabling_writes(self):
        self.run_queue_js("""
          const pending=deferred(); apiWrite=()=>pending.promise;
          drawShopping(data([qrow('Alpha',1)])); goMove(1,'Deferred');
          const error=entry(1).querySelector('.form-error'); density(true);
          pending.reject(Object.assign(new Error('Changed elsewhere'),{status:409})); await settle();
          assert(error.isConnected); assert(!error.hidden); assert(error.textContent.includes('Changed elsewhere'));
          density(false); density(true);
          assert(entry(1).querySelector('.form-error')===error);
          assert(main.querySelectorAll('.shop-queue-write').every(node=>node.disabled));
          assert(error.querySelector('button').isConnected);
          assert.equal(entry(1).getAttribute('data-shop-queue'),'1');
        """)

    def test_longterm_matching_reveals_and_roundtrip_clear_keep_exact_rows_and_expansion(self):
        self.run_queue_js("""
          density(true);
          const queue=['A','B'].flatMap((group,g)=>Array.from({length:14},(_,i)=>qrow(group+i,g*14+i+1,
            {state:'long_term',for:group,listed_at:i===13?'Shop':'Other'})));
          const view=drawShopping(data(queue)); const first=viewTrigger(1), firstMove=move(1);
          assert.equal(main.querySelectorAll('[data-shop-queue]').length,24);
          choose('shop:Shop'); assert.equal(main.querySelectorAll('[data-shop-queue]').length,28);
          assert(viewTrigger(1)===first && move(1)===firstMove);
          density(false); density(true);
          assert(viewTrigger(1)===first && move(1)===firstMove);
          assert.equal(main.querySelectorAll('[data-shop-match=true]').length,2);
          main.querySelector('.shop-clear-match').click();
          assert.equal(main.querySelectorAll('[data-shop-queue]').length,28);
          assert.equal(main.querySelectorAll('[data-shop-match=true]').length,0);
          assert.equal(main.querySelectorAll('.shop-long-more').length,0);
          assert.equal(main.querySelectorAll('[data-viewer]').length,28);
        """)

    def test_readonly_and_old_media_callbacks_cannot_reveal_or_rewrite_replaced_private_view(self):
        self.run_queue_js("""
          density(true); state.may.admin=false; state.may.orders=false;
          // Other pages' page-lifetime listeners (the Editor's resize) aren't the view's.
          const resident=[...(window.matchMedia(SHOP_QUEUE_LAB).events.get('change')||[])];
          const view=drawShopping(data([qrow('Private',1,{listed_at:'Secret shop'})]));
          assert.equal(main.querySelectorAll('.shop-queue-write').length,0);
          const query=window.matchMedia(SHOP_QUEUE_LAB), callbacks=query.events.get('change').filter(c=>!resident.includes(c));
          assert(callbacks.length);
          const table=main.querySelector('.shop-queue-table'); state.profile={id:'elsewhere'};
          density(false); assert(main.querySelector('.shop-queue-table')===table);
          assert(callbacks.every(callback=>!query.events.get('change').includes(callback)));
          clear(main); callbacks.forEach(callback=>callback()); assert.equal(main.textContent,'');
          assert.equal(view.data.to_buy[0].name,'Private');
        """)

    def test_reprint_control_and_open_queue_sheet_keep_their_context_and_live_trigger_after_resize(self):
        self.run_queue_js("""
          const view=drawShopping(data([qrow('Alpha',1,{state:'waiting_for_reprint',notes:'Do not lose me',
            reprints:{ready:true,upcoming:[],source_url:'',price_check:{offered:true,reason:'unknown'}}})]));
          const reprint=entry(1).querySelector('.reprint-check'), button=edit(1);
          button.focus(); button.click(); const sheet=[...shopQueueSheets][0]; assert(sheet);
          density(true); assert(edit(1)===button); assert(reprint.isConnected);
          assert.equal(main.querySelectorAll('.reprint-check').length,1);
          assert.equal(main.querySelector('.shop-q-extra').hidden,true);
          sheet.close(); assert(button.isConnected);
          entry(1).querySelector('.shop-q-more').click(); assert(!main.querySelector('.shop-q-extra').hidden);
          assert(entry(1).querySelector('.shop-q-checked').textContent.includes('Check date not recorded'));
        """)

    def test_actual_viewer_close_returns_to_the_same_live_trigger_after_both_density_changes(self):
        self.run_queue_js("""
          drawShopping(data([qrow('Alpha',1)])); const trigger=viewTrigger(1);
          const group=viewerGroup(trigger); openCardViewer(group.items,group.index,{trigger});
          assert(viewerState.trigger===trigger); density(true);
          assert(viewTrigger(1)===trigger); assert(document.activeElement===viewerDom.close);
          viewerClosed(); assert(document.activeElement===trigger);
          const again=viewerGroup(trigger); openCardViewer(again.items,again.index,{trigger});
          density(false); viewerClosed(); assert(document.activeElement===trigger);
          assert.equal(main.querySelectorAll('[data-viewer]').length,1);
        """)

    def test_remove_renumbers_current_table_rows_and_next_move_uses_the_saved_revision(self):
        self.run_queue_js("""
          density(true); const queue=[qrow('Alpha',1),qrow('Beta',2)], writes=[];
          apiWrite=async(path,body)=>{writes.push(body);return {revision:'q'+(writes.length+1)}};
          const view=drawShopping(data(queue)), old=move(2);
          edit(1).click(); const sheet=[...shopQueueSheets][0];
          await shopSaveQueue(view,sheet,sheet.queueError,{action:'remove',row:1,reason:'Duplicate'},queue[0]);
          assert.equal(queue.length,1); assert.equal(queue[0].name,'Beta'); assert.equal(queue[0].queue_row,1);
          assert.equal(view.data.queue_revision,'q2'); assert(!old.isConnected);
          density(false); density(true); goMove(1,'Deferred'); await settle();
          assert.equal(writes[1].row,1); assert.equal(writes[1].expect,'q2');
          assert.equal(queue[0].state,'deferred'); assert.equal(view.data.queue_revision,'q3');
          assert(document.activeElement===move(1)); assert(move(1).scrolled>0);
        """)

    def test_used_reprint_control_and_matching_chip_keep_a_visible_focus_target_on_resize(self):
        self.run_queue_js("""
          const view=drawShopping(data([qrow('Alpha',1,{listed_at:'Shop',state:'waiting_for_reprint',
            reprints:{ready:true,upcoming:[],price_check:{offered:true,reason:'unknown'}}})]));
          const reprint=entry(1).querySelector('.reprint-check'); reprint.click();
          const sheet=[...reprintSheets][0]; assert(sheet); density(true);
          assert.equal(main.querySelector('.shop-q-extra').hidden,false);
          assert(reprint.isConnected); assert.equal(main.querySelectorAll('.reprint-check').length,1);
          sheet.close(); reprint.focus(); density(false); assert(document.activeElement===reprint);
          choose('shop:Shop'); main.querySelector('.shop-clear-match').focus(); density(true);
          assert(document.activeElement===main.querySelector('.shop-clear-match'));
        """)

    def test_route_or_detachment_stops_density_callbacks_without_reads_or_cross_context_updates(self):
        self.run_queue_js("""
          api=()=>{throw new Error('Must not read')}; apiWrite=()=>{throw new Error('Must not write')};
          const view=drawShopping(data([qrow('Alpha',1,{listed_at:'Shop'})]));
          const query=window.matchMedia(SHOP_QUEUE_LAB), callback=query.events.get('change').at(-1);
          routeToken++; density(true); assert.equal(main.querySelector('.shop-queue-table'),null);
          assert(!query.events.get('change').includes(callback)); routeToken--;
          const trigger=viewTrigger(1); clear(main); callback(); assert(!trigger.isConnected);
          assert.equal(main.children.length,0); assert.equal(view.data.queue_revision,'q1');
        """)

    def test_readonly_unknown_card_disclosure_returns_focus_to_its_visible_text_row(self):
        self.run_queue_js("""
          density(true); state.may.admin=false; state.may.orders=false;
          drawShopping(data([qrow('Unknown card',1,{card:null,notes:'Keep this instruction'})]));
          const textRow=viewTrigger(1); assert.equal(textRow.tag,'div'); assert.equal(textRow.getAttribute('tabindex'),'-1');
          entry(1).querySelector('.shop-q-more').focus(); density(false);
          assert(document.activeElement===textRow); assert(textRow.isConnected);
          assert.equal(main.querySelectorAll('.shop-queue-write').length,0);
          assert.equal(main.querySelectorAll('[data-viewer]').length,0);
        """)

    def test_focused_table_region_returns_to_visible_group_and_only_latest_view_listens(self):
        self.run_queue_js("""
          density(true); const resident=[...(window.matchMedia(SHOP_QUEUE_LAB).events.get('change')||[])];
          drawShopping(data([qrow('Alpha',1)]));
          const holder=main.querySelector('.shop-queue-presentation'); main.querySelector('.shop-queue-table-wrap').focus();
          density(false); assert(document.activeElement===holder); assert.equal(holder.getAttribute('tabindex'),'-1');
          const query=window.matchMedia(SHOP_QUEUE_LAB), before=query.events.get('change').filter(c=>!resident.includes(c));
          assert(before.length);
          clear(main); drawShopping(data([qrow('Beta',1)]));
          assert(before.every(callback=>!query.events.get('change').includes(callback)));
          density(true); assert.equal(main.querySelectorAll('.shop-queue-table').length,1);
          assert(viewTrigger(1).textContent.includes('Beta'));
        """)

    def test_compact_cells_keep_full_saved_words_and_exact_printing_outside_title_only_hints(self):
        self.run_queue_js("""
          density(true);
          const shop='A shop name long enough to wrap across several lines',
            purpose='An unlinked saved deck purpose that is much longer than its column',
            title='A linked deck title longer than its column';
          drawShopping(data([qrow('Alpha',1,{for:purpose,listed_at:shop,state:'waiting_for_reprint',
            printing:'exact',set:'fdn',collector_number:'123',finish:'foil',checked:'2026-10-24',in_stock:'no'}),
            qrow('Beta',2,{deck:{id:'casual/long-title',title}})]));
          const forWords=entry(1).querySelector('.shop-q-for').querySelector('.shop-q-clip'),
            shopWords=entry(1).querySelector('.shop-q-shop').querySelector('.shop-q-clip');
          assert.equal(forWords.textContent,purpose); assert.equal(forWords.getAttribute('title'),purpose);
          assert.equal(shopWords.textContent,shop); assert.equal(shopWords.getAttribute('title'),shop);
          const deck=entry(2).querySelector('.shop-queue-deck');
          assert.equal(deck.textContent,title); assert.equal(deck.getAttribute('title'),title);
          assert.equal(deck.getAttribute('href'),'#/deck?id=casual%2Flong-title&v=target');
          assert.equal(entry(1).querySelector('.shop-q-printing-line').getAttribute('title'),'Exact: FDN 123 foil');
          assert.equal(entry(1).querySelector('.shop-q-printing-number').textContent,'123');
          assert.equal(entry(1).querySelector('.shop-q-printing').querySelector('.chip-foil').textContent,'Foil');
          assert.equal(entry(1).querySelector('.shop-q-reason').textContent,'for a reprint');
          assert.equal(entry(1).querySelector('.shop-q-stock').textContent,'Out of stock');
          assert.equal(entry(1).querySelector('.shop-q-checked').textContent,'2026-10-24');
          choose('shop:'+shop); assert.equal(entry(1).getAttribute('data-shop-match'),'true');
          assert.equal(shopWords.textContent,shop); assert.equal(viewerGroup(viewTrigger(1)).items.length,2);
        """)
