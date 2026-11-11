"""Lossless export choices and clipboard fallbacks stay with their original visible deck."""
import unittest

from decklab.tests import test_deck_page_ui as page_ui


@unittest.skipUnless(page_ui.NODE, "Node.js is not installed")
class DeckExportUiTests(unittest.TestCase):
    run_js = page_ui.DeckPageUiTests.run_js

    def test_lossless_copy_and_fallback_keep_finishes_and_categories(self):
        self.run_js(r'''
          const data=makePage();data.sections.Deck[0].category='Ramp';data.sections.Deck[1].finish='etched';data.sections.Deck[1].category='Draw';
          const expected=exportedDeck(data,{categories:true}),copied=[];navigator.clipboard={writeText:async text=>copied.push(text)};
          await copyDeck(data,{categories:true});same(copied,[expected]);assert(expected.includes(' #Ramp'));assert(expected.includes(' *E* #Draw'));
          navigator.clipboard={writeText:async()=>{throw Error('Unavailable');}};await copyDeck(data,{categories:true});
          const dialog=document.querySelector('dialog[open]');assert(dialog);assert.equal(dialog.querySelector('textarea').value,expected);
        ''')

    def test_more_menu_has_explicit_category_copy_and_old_menu_cannot_export_for_another_profile(self):
        self.run_js(r'''
          const data=makePage(),items=deckMoreItems(data),chosen=items.find(item=>item?.label==='Copy with categories');assert(chosen);
          const calls=[];copyDeck=(...args)=>calls.push(args);chosen.onclick();assert.equal(calls.length,1);same(calls[0][1],{categories:true});
          state.profile={id:'user2',space:'user2'};chosen.onclick();assert.equal(calls.length,1);
          items.find(item=>item?.label==='Copy decklist').onclick();assert.equal(calls.length,1);
        ''')

    def test_late_clipboard_failure_cannot_relay_private_list_to_a_new_frame_profile_or_route(self):
        self.run_js(r'''
          for(const change of ['profile','route','hash','frame','list']){
            state.profile={id:'matt',name:'Matt',plays_as:'user'};location.hash='#/deck?id=casual/test';
            const data=makePage();let reject;navigator.clipboard={writeText:()=>new Promise((resolve,fail)=>reject=fail)};
            const pending=copyDeck(data,{categories:true});
            if(change==='profile')state.profile={id:'user2'};if(change==='route')routeToken++;
            if(change==='hash')location.hash='#/collection';if(change==='list')data.sections.Deck[0].qty=99;
            if(change==='frame'){document.getElementById('main').remove();document.body.append(el('main',{id:'main'}));}
            reject(Error('Unavailable'));await pending;assert.equal(document.querySelectorAll('dialog[open]').length,0,change);
          }
        ''')
