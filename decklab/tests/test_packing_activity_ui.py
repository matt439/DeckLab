"""Recorded packing activity is scoped evidence, never a live-presence claim."""
import unittest

from decklab.tests import test_assembly_progress_ui as progress
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, 'Node.js is not installed')
class PackingActivityUiTests(unittest.TestCase):
    def run_js(self, scenario):
        progress.AssemblyProgressUiTests.run_js(self, r'''
          state.profiles.push({id:'user1',name:'User1',space:'home'});
          let activity={profile:'user1',by:'User1',at:'2026-10-26T12:00:00Z',checks:2};
          apiWrite=async(path,body)=>{posts.push(body);return {...apply(body),activity};};
        ''' + scenario)

    def test_recorded_actor_count_date_and_person_colour_stay_retained_across_identical_polls(self):
        self.run_js(r'''
          const root=open(plan());await settle();const p=packingProgressView.progress;
          const node=root.querySelector('.pack-last-activity'),avatar=node.querySelector('.avatar'),text=node.children[1];
          assert(!node.hidden);assert(node.textContent.includes('Last recorded update: User1'));
          assert(node.textContent.includes('2 check updates'));assert(node.textContent.includes('2026'));
          assert(avatar.matches('.avatar-1'));assert.equal(avatar.getAttribute('aria-hidden'),'true');
          assert(!node.textContent.includes('online'));assert(!node.textContent.includes('packing now'));
          assert.equal(node.querySelector('time').getAttribute('datetime'),activity.at);
          const message=p.message.children[0];await poll();
          assert(root.querySelector('.pack-last-activity')===node&&node.querySelector('.avatar')===avatar);
          assert(node.children[1]===text&&p.message.children[0]===message);
        ''')

    def test_missing_old_server_or_malformed_optional_metadata_leaves_ticks_usable(self):
        self.run_js(r'''
          const root=open(plan());await settle();tiles(root)[0].click();await settle();same(checked(root),['true']);
          for(const value of [null,undefined,{...activity,at:'not a date'},{...activity,checks:0},{...activity,checks:'2'}]) {
            activity=value;await poll();assert(root.querySelector('.pack-last-activity').hidden);same(checked(root),['true']);
          }
          activity={profile:null,by:'Someone',at:'2026-10-26T12:00:00Z',checks:1};await poll();
          assert(!root.querySelector('.pack-last-activity').hidden);
          assert(root.querySelector('.pack-activity-avatar').matches('.is-unknown'));
          assert(root.querySelector('.pack-last-activity').textContent.includes('1 check update.'));
        ''')

    def test_pending_tasks_outside_current_selection_never_supply_current_activity(self):
        self.run_js(r'''
          const root=open(plan());await settle();const view=packingProgressView;
          assert(!root.querySelector('.pack-last-activity').hidden);
          packQueueTicks(view,[{id:'a task pending from an older selection',done:true}]);await settle();
          assert(root.querySelector('.pack-last-activity').hidden);
          await poll();assert(!root.querySelector('.pack-last-activity').hidden);
        ''')

    def test_failed_poll_hides_activity_and_retry_control_keeps_its_identity(self):
        self.run_js(r'''
          const root=open(plan());await settle();apiWrite=async()=>{throw Error('Fixture down');};
          await poll();assert(root.querySelector('.pack-last-activity').hidden);
          const p=packingProgressView.progress,retry=p.message.querySelector('button');retry.focus();
          packProgressNotice(packingProgressView);assert(p.message.querySelector('button')===retry);
          assert.equal(document.activeElement,retry);
        ''')
