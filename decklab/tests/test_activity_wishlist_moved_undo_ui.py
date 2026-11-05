"""Activity's sheet for undoing a wishlist addition that moved other entries along (E11-S08)."""
import unittest

from decklab.tests import test_activity_wishlist_presence_undo_ui as presence
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class WishlistMovedUndoUiTests(unittest.TestCase):
    def run_js(self, scenario):
        presence.WishlistPresenceUndoUiTests.run_js(self, scenario)

    def test_moved_count_is_shown_and_saved_like_a_removal(self):
        self.run_js(r'''
          for(const [count,words] of [[1,'1 other entry moved along to make room for it, and goes back to its earlier place.'],
                                      [3,'3 other entries moved along to make room for it, and go back to their earlier place.']]){
            const p=presencePreview('wishlist_remove',{moved:count}),{sheet}=await openWish(p),text=sheet.body.textContent;
            assert(text.includes(words),text);assert(text.includes('Your list keeps its order.'));
            assert(text.includes('Save Undo removes this entry from your wishlist.'));
            let sent=[];apiWrite=async(path,body)=>{sent.push([path,body]);return presenceSaved(p);};
            save(sheet).click();await settle();same(sent,[['/api/activity/wishlist-undo',{id:42,expect:'a'.repeat(64)}]]);assert(button(sheet.dialog,'Done'));
          }
        ''')

    def test_moved_count_is_only_for_removals_and_must_be_one_to_fifty(self):
        self.run_js(r'''
          for(const [action,moved] of [['wishlist_remove',0],['wishlist_remove',51],['wishlist_remove','2'],['wishlist_remove',1.5],['wishlist_remove',null],
                                       ['wishlist_add',2]]){
            const {sheet}=await openWish(presencePreview(action,{moved}));assert(!save(sheet),action+moved);
          }
          const {sheet}=await openWish(presencePreview('wishlist_remove'));assert(save(sheet));assert(!sheet.body.textContent.includes('moved along'));
        ''')
