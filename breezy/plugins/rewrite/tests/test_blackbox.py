# Copyright (C) 2007 by Jelmer Vernooij <jelmer@samba.org>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Couple of blackbox tests for the rewrite plugin."""

import os

from ....branch import Branch
from ....tests.blackbox import ExternalBase

class TestRebaseSimple(ExternalBase):

    def make_file(self, name, contents):
        with open(name, 'w' + ('b' if isinstance(contents, bytes) else '')) as f:
            f.write(contents)

    def setUp(self):
        super(TestRebaseSimple, self).setUp()
        os.mkdir('main')
        os.chdir('main')
        self.run_bzr('init')
        self.make_file('hello', b"hi world")
        self.run_bzr('add')
        self.run_bzr('commit -m bla')
        self.run_bzr('branch . ../feature')

    def test_no_upstream_branch(self):
        self.run_bzr_error(['brz: ERROR: No upstream branch specified.\n'],
                           'rebase')

    def test_notneeded(self):
        os.chdir('../feature')
        self.assertEquals(
            'No revisions to rebase.\n',
            self.run_bzr('rebase ../main')[0])

    def test_custom_merge_type(self):
        self.make_file('hello', '42')
        self.run_bzr('commit -m that')
        os.chdir('../feature')
        self.make_file('hoi', "my data")
        self.run_bzr('add')
        self.run_bzr('commit -m this')
        self.assertEquals('', self.run_bzr('rebase --lca ../main')[0])
        self.assertEquals('3\n', self.run_bzr('revno')[0])

    def test_notneeded_feature_ahead(self):
        os.chdir('../feature')
        self.make_file('barbla', "bloe")
        self.run_bzr('add')
        self.run_bzr('commit -m bloe')
        self.assertEquals(
            'No revisions to rebase.\n',
            self.run_bzr('rebase ../main')[0])

    def test_notneeded_main_ahead(self):
        self.make_file('barbla', "bloe")
        self.run_bzr('add')
        self.run_bzr('commit -m bloe')
        os.chdir('../feature')
        self.assertEquals(
            "Base branch is descendant of current branch. Pulling instead.\n",
            self.run_bzr('rebase ../main')[0])
        self.assertEquals(Branch.open("../feature").last_revision_info(),
                          Branch.open("../main").last_revision_info())

    def test_no_pending_merges(self):
        self.run_bzr_error(['brz: ERROR: No pending merges present.\n'],
                           ['rebase', '--pending-merges'])

    def test_pending_merges(self):
        os.chdir('..')
        self.build_tree_contents([('main/hello', '42')])
        self.run_bzr('add', working_dir='main')
        self.run_bzr('commit -m that main')
        self.build_tree_contents([('feature/hoi', 'my data')])
        self.run_bzr('add', working_dir='feature')
        self.run_bzr('commit -m this feature')
        self.assertEqual(
            ('', ' M  hello\nAll changes applied successfully.\n'),
            self.run_bzr('merge ../main', working_dir='feature'))
        out, err = self.run_bzr('rebase --pending-merges', working_dir='feature')
        self.assertEqual('', out)
        self.assertContainsRe(err, 'modified hello')
        self.assertEqual(
            ('3\n', ''),
            self.run_bzr('revno', working_dir='feature'))

    def test_simple_success(self):
        self.make_file('hello', '42')
        self.run_bzr('commit -m that')
        os.chdir('../feature')
        self.make_file('hoi', "my data")
        self.run_bzr('add')
        self.run_bzr('commit -m this')
        self.assertEquals('', self.run_bzr('rebase ../main')[0])
        self.assertEquals('3\n', self.run_bzr('revno')[0])

    def test_range(self):
        # commit mainline rev 2
        self.make_file('hello', '42')
        self.run_bzr('commit -m that')
        # commit feature rev 2
        os.chdir('../feature')
        self.make_file('hoi', "my data")
        self.run_bzr('add')
        self.run_bzr('commit -m this')
        # commit feature rev 3
        self.make_file('hooi', "your data")
        self.run_bzr('add')
        self.run_bzr('commit -m that')
        # commit feature rev 4
        self.make_file('hoooi', "someone else's data")
        self.run_bzr('add')
        self.run_bzr('commit -m these')
        # pick up just rev 2 and 3 and discard 4 from feature
        self.assertEquals('', self.run_bzr('rebase -r2..3 ../main')[0])
        # our rev 2 is now rev3 and 3 is now rev4:
        self.assertEquals('4\n', self.run_bzr('revno')[0])
        # content added from our old revisions 4 should be gone.
        self.assertPathDoesNotExist('hoooi')

    def test_range_open_end(self):
        # commit mainline rev 2
        self.make_file('hello', '42')
        self.run_bzr('commit -m that')
        # commit feature rev 2
        os.chdir('../feature')
        self.make_file('hoi', "my data")
        self.run_bzr('add')
        self.run_bzr('commit -m this')
        # commit feature rev 3
        self.make_file('hooi', "your data")
        self.run_bzr('add')
        self.run_bzr('commit -m that')
        # commit feature rev 4
        self.make_file('hoooi', "someone else's data")
        self.run_bzr('add')
        self.run_bzr('commit -m these')
        # rebase only rev 4 onto main
        self.assertEquals('', self.run_bzr('rebase -r4.. ../main')[0])
        # should only get rev 3 (our old 2 and 3 are gone)
        self.assertEquals('3\n', self.run_bzr('revno')[0])
        self.assertPathDoesNotExist('hoi')
        self.assertPathDoesNotExist('hooi')
        branch = Branch.open(".")
        self.assertEquals(
            "these",
            branch.repository.get_revision(branch.last_revision()).message)
        self.assertPathExists('hoooi')

    def test_conflicting(self):
        # commit mainline rev 2
        self.make_file('hello', '42')
        self.run_bzr('commit -m that')
        # commit feature rev 2 changing hello differently
        os.chdir('../feature')
        self.make_file('hello', "other data")
        self.run_bzr('commit -m this')
        self.run_bzr_error([
            'Text conflict in hello\n1 conflicts encountered.\nbrz: ERROR: A conflict occurred replaying a commit. Resolve the conflict and run \'brz rebase-continue\' or run \'brz rebase-abort\'.',
            ], ['rebase', '../main'])

    def test_conflicting_abort(self):
        self.make_file('hello', '42')
        self.run_bzr('commit -m that')
        os.chdir('../feature')
        self.make_file('hello', "other data")
        self.run_bzr('commit -m this')
        old_log = self.run_bzr('log')[0]
        self.run_bzr_error(['Text conflict in hello\n1 conflicts encountered.\nbrz: ERROR: A conflict occurred replaying a commit. Resolve the conflict and run \'brz rebase-continue\' or run \'brz rebase-abort\'.\n'], ['rebase', '../main'])
        self.assertEquals('', self.run_bzr('rebase-abort')[0])
        self.assertEquals(old_log, self.run_bzr('log')[0])

    def test_conflicting_continue(self):
        self.make_file('hello', '42')
        self.run_bzr('commit -m that')
        os.chdir('../feature')
        self.make_file('hello', "other data")
        self.run_bzr('commit -m this')
        self.run_bzr_error(['Text conflict in hello\n1 conflicts encountered.\nbrz: ERROR: A conflict occurred replaying a commit. Resolve the conflict and run \'brz rebase-continue\' or run \'brz rebase-abort\'.\n'], ['rebase', '../main'])
        self.run_bzr('resolved hello')
        self.assertEquals('', self.run_bzr('rebase-continue')[0])
        self.assertEquals('3\n', self.run_bzr('revno')[0])

    def test_continue_nothing(self):
        self.run_bzr_error(['brz: ERROR: No rebase to continue'],
                           ['rebase-continue'])

    def test_abort_nothing(self):
        self.run_bzr_error(['brz: ERROR: No rebase to abort'],
                           ['rebase-abort'])

    def test_todo_nothing(self):
        self.run_bzr_error(['brz: ERROR: No rebase in progress'],
                           ['rebase-todo'])

    def test_onto(self):
        self.make_file('hello', '42')
        self.run_bzr('add')
        self.run_bzr('commit -m that')
        self.make_file('other', '43')
        self.run_bzr('add')
        self.run_bzr('commit -m that_other')
        os.chdir('../feature')
        self.make_file('hoi', "my data")
        self.run_bzr('add')
        self.run_bzr('commit -m this')
        self.assertEquals(
            '', self.run_bzr('rebase --onto -2 ../main')[0])
        self.assertEquals(
            '3\n', self.run_bzr('revno')[0])

    def test_unrelated(self):
        os.chdir('..')
        os.mkdir('unrelated')
        os.chdir('unrelated')
        self.run_bzr('init')
        self.make_file('hello', "hi world")
        self.run_bzr('add')
        self.run_bzr('commit -m x')
        self.run_bzr_error(['brz: ERROR: Branches have no common ancestor, and no merge base.*'],
                           ['rebase', '../main'])

    def test_verbose(self):
        self.make_file('hello', '42')
        self.run_bzr('commit -m that')
        os.chdir('../feature')
        self.make_file('hoi', "my data")
        self.run_bzr('add')
        self.run_bzr('commit -m this')
        out, err = self.run_bzr('rebase -v ../main')
        self.assertContainsRe(err, '1 revisions will be rebased:')
        self.assertEqual('', out)
        self.assertEqual('3\n', self.run_bzr('revno')[0])

    def test_useless_merge(self):
        self.make_file('bar', '42')
        self.run_bzr('add')
        self.run_bzr('commit -m that')
        os.chdir('../feature')
        self.make_file('hello', "my data")
        self.run_bzr('commit -m this')
        self.run_bzr('merge')
        self.run_bzr('commit -m merge')
        self.run_bzr('rebase')

    def strip_last_revid_part(self, revid):
        """Assume revid is a revid in the default form, and strip the part
        which would be random.
        """
        return revid[:revid.rindex(b'-')]

    def test_always_rebase_merges(self):
        trunk = self.make_branch_and_tree('trunk')
        trunk.commit('base')
        feature2 = trunk.controldir.sprout('feature2').open_workingtree()
        revid2 = feature2.commit('change')
        feature = trunk.controldir.sprout('feature').open_workingtree()
        feature.commit('change')
        feature.merge_from_branch(feature2.branch)
        feature.commit('merge')
        feature.commit('change2')
        trunk.commit('additional upstream change')
        self.run_bzr('rebase --always-rebase-merges ../trunk', working_dir='feature')
        # second revision back should be a merge of feature2
        repo = feature.branch.repository
        repo.lock_read()
        self.addCleanup(repo.unlock)
        tip = feature.last_revision()
        merge_id = repo.get_graph().get_parent_map([tip])[tip][0]
        merge_parents = repo.get_graph().get_parent_map([merge_id])[merge_id]
        self.assertEqual(self.strip_last_revid_part(revid2),
                         self.strip_last_revid_part(merge_parents[1]))

    def test_rebase_merge(self):
        trunk = self.make_branch_and_tree('trunk')
        trunk.commit('base')
        feature2 = trunk.controldir.sprout('feature2').open_workingtree()
        revid2 = feature2.commit('change')
        feature = trunk.controldir.sprout('feature').open_workingtree()
        feature.commit('change')
        feature.merge_from_branch(feature2.branch)
        feature.commit('merge')
        feature.commit('change2')
        trunk.commit('additional upstream change')
        self.run_bzr('rebase ../trunk', working_dir='feature')
        # second revision back should be a merge of feature2
        repo = feature.branch.repository
        repo.lock_read()
        self.addCleanup(repo.unlock)
        tip = feature.last_revision()
        merge_id = repo.get_graph().get_parent_map([tip])[tip][0]
        merge_parents = repo.get_graph().get_parent_map([merge_id])[merge_id]
        self.assertEqual(self.strip_last_revid_part(revid2),
                         self.strip_last_revid_part(merge_parents[1]))

    def test_directory(self):
        self.make_file('test_directory1', "testing non-current directories")
        self.run_bzr('add')
        self.run_bzr('commit -m blah')
        os.chdir('../feature')
        self.make_file('test_directory2', "testing non-current directories")
        self.run_bzr('add')
        self.run_bzr('commit -m blah')
        os.chdir('..')
        self.assertEquals('', self.run_bzr('rebase -d feature main')[0])


class ReplayTests(ExternalBase):

    def test_replay(self):
        os.mkdir('main')
        os.chdir('main')
        self.run_bzr('init')
        with open('bar', 'w') as f:
            f.write('42')
        self.run_bzr('add')
        self.run_bzr('commit -m that')
        os.mkdir('../feature')
        os.chdir('../feature')
        self.run_bzr('init')
        branch = Branch.open('.')
        with open('hello', 'w') as f:
            f.write("my data")
        self.run_bzr('add')
        self.run_bzr('commit -m this')
        self.assertEquals(1, branch.revno())
        self.run_bzr('replay -r1 ../main')
        self.assertEquals(2, branch.revno())
        self.assertTrue(os.path.exists('bar'))

    def test_replay_open_range(self):
        os.mkdir('main')
        os.chdir('main')
        self.run_bzr('init')
        with open('bar', 'w') as f:
            f.write('42')
        self.run_bzr('add')
        self.run_bzr('commit -m that')
        with open('bar', 'w') as f:
            f.write('84')
        self.run_bzr('commit -m blathat')
        os.mkdir('../feature')
        os.chdir('../feature')
        self.run_bzr('init')
        branch = Branch.open('.')
        with open('hello', 'w') as f:
            f.write("my data")
        self.run_bzr('add')
        self.run_bzr('commit -m this')
        self.assertEquals(1, branch.revno())
        self.run_bzr('replay -r1.. ../main')
        self.assertEquals(3, branch.revno())
        self.assertTrue(os.path.exists('bar'))
