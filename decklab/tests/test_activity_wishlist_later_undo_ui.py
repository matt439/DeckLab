"""Activity's sheet for putting back a wishlist removal after later list changes (E11-S08)."""
import unittest

from decklab.tests import test_activity_wishlist_presence_undo_ui as presence
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class WishlistLaterUndoUiTests(unittest.TestCase):
    def run_js(self, scenario):
        presence.WishlistPresenceUndoUiTests.run_js(self, scenario)

    def test_later_count_is_shown_and_saved_like_a_restore(self):
        self.run_js(r'''
          for(const [count,words] of [[1,'1 later change to your wishlist stays as it is.'],[3,'3 later changes to your wishlist stay as they are.']]){
            const p=presencePreview('wishlist_add',{later:count}),{sheet}=await openWish(p),text=sheet.body.textContent;
            assert(text.includes(words),text);assert(text.includes('The entry goes back to its old place.'));
            assert(text.includes('Save Undo restores this entry to your wishlist.'));assert(text.includes('Historical wishlist entry to restore'));
            assert(!text.includes('moved along'));
            let sent=[];apiWrite=async(path,body)=>{sent.push([path,body]);return presenceSaved(p);};
            save(sheet).click();await settle();same(sent,[['/api/activity/wishlist-undo',{id:42,expect:'a'.repeat(64)}]]);assert(button(sheet.dialog,'Done'));
          }
        ''')

    def test_later_count_is_only_for_restores_and_must_be_one_to_two_hundred(self):
        self.run_js(r'''
          for(const [action,later] of [['wishlist_add',0],['wishlist_add',201],['wishlist_add','2'],['wishlist_add',1.5],['wishlist_add',null],
                                       ['wishlist_add',true],['wishlist_remove',2]]){
            const {sheet}=await openWish(presencePreview(action,{later}));assert(!save(sheet),action+later);
          }
          {const {sheet}=await openWish(presencePreview('wishlist_add',{later:200}));assert(save(sheet));}
          const {sheet}=await openWish(presencePreview('wishlist_add'));assert(save(sheet));assert(!sheet.body.textContent.includes('later change'));
        ''')
