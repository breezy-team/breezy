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

from bzrlib.branch import Branch
from bzrlib.tests.blackbox import ExternalBase

class TestRebaseSimple(ExternalBase):

    def make_file(self, name, contents):
        f = open(name, 'wb')
        try:
            f.write(contents)
        finally:
            f.close()

    def setUp(self):
        super(TestRebaseSimple, self).setUp()
        os.mkdir('main')
        os.chdir('main')
        self.run_bzr('init')
        self.make_file('hello', "hi world")
        self.run_bzr('add')
        self.run_bzr('commit -m bla')
        self.run_bzr('branch . ../feature')

    def test_notneeded(self):
        os.chdir('../feature')
        self.check_output('No revisions to rebase.\n', 'rebase ../main')

    def test_notneeded_feature_ahead(self):
        os.chdir('../feature')
        self.make_file('barbla', "bloe")
        self.run_bzr('add')
        self.run_bzr('commit -m bloe')
        self.check_output('No revisions to rebase.\n', 'rebase ../main')

    def test_notneeded_main_ahead(self):
        self.make_file('barbla', "bloe")
        self.run_bzr('add')
        self.run_bzr('commit -m bloe')
        os.chdir('../feature')
        self.check_output("Base branch is descendant of current branch. Pulling instead.\n", 'rebase ../main')
        self.assertEquals(Branch.open("../feature").revision_history(),
                          Branch.open("../main").revision_history())

    def test_no_pending_merges(self):
        self.run_bzr_error(['bzr: ERROR: No pending merges present.\n'],
                           ['rebase', '--pending-merges'])

    def test_pending_merges(self):
        os.chdir('..')
        self.build_tree_contents([('main/hello', '42')])
        self.run_bzr('add', working_dir='main')
        self.run_bzr('commit -m that main')
        self.build_tree_contents([('feature/hoi', 'my data')])
        self.run_bzr('add', working_dir='feature')
        self.run_bzr('commit -m this feature')
        self.assertEqual(('', ' M  hello\nAll changes applied successfully.\n'),
            self.run_bzr('merge ../main', working_dir='feature'))
        out, err = self.run_bzr('rebase --pending-merges', working_dir='feature')
        self.assertEqual('', out)
        self.assertContainsRe(err, 'modified hello')
        self.assertEqual(('3\n', ''),
            self.run_bzr('revno', working_dir='feature'))

    def test_simple_success(self):
        self.make_file('hello', '42')
        self.run_bzr('commit -m that')
        os.chdir('../feature')
        self.make_file('hoi', "my data")
        self.run_bzr('add')
        self.run_bzr('commit -m this')
        self.check_output('', 'rebase ../main')
        self.check_output('3\n', 'revno')

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
        self.check_output('', 'rebase -r2..3 ../main')
        # our rev 2 is now rev3 and 3 is now rev4:
        self.check_output('4\n', 'revno')
        # content added from our old revisions 4 should be gone.
        self.failIfExists('hoooi')

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
        self.check_output('', 'rebase -r4.. ../main')
        # should only get rev 3 (our old 2 and 3 are gone)
        self.check_output('3\n', 'revno')
        self.failIfExists('hoi')
        self.failIfExists('hooi')
        branch = Branch.open(".")
        self.assertEquals("these",
            branch.repository.get_revision(branch.last_revision()).message)
        self.failUnlessExists('hoooi')

    def test_conflicting(self):
        # commit mainline rev 2
        self.make_file('hello', '42')
        self.run_bzr('commit -m that')
        # commit feature rev 2 changing hello differently
        os.chdir('../feature')
        self.make_file('hello', "other data")
        self.run_bzr('commit -m this')
        self.run_bzr_error([
            'Text conflict in hello\n1 conflicts encountered.\nbzr: ERROR: A conflict occurred replaying a commit. Resolve the conflict and run \'bzr rebase-continue\' or run \'bzr rebase-abort\'.',
            ], ['rebase', '../main'])

    def test_conflicting_abort(self):
        self.make_file('hello', '42')
        self.run_bzr('commit -m that')
        os.chdir('../feature')
        self.make_file('hello', "other data")
        self.run_bzr('commit -m this')
        old_log = self.run_bzr('log')[0]
        self.run_bzr_error(['Text conflict in hello\n1 conflicts encountered.\nbzr: ERROR: A conflict occurred replaying a commit. Resolve the conflict and run \'bzr rebase-continue\' or run \'bzr rebase-abort\'.\n'], ['rebase', '../main'])
        self.check_output('', 'rebase-abort')
        self.check_output(old_log, 'log')

    def test_conflicting_continue(self):
        self.make_file('hello', '42')
        self.run_bzr('commit -m that')
        os.chdir('../feature')
        self.make_file('hello', "other data")
        self.run_bzr('commit -m this')
        self.run_bzr_error(['Text conflict in hello\n1 conflicts encountered.\nbzr: ERROR: A conflict occurred replaying a commit. Resolve the conflict and run \'bzr rebase-continue\' or run \'bzr rebase-abort\'.\n'], ['rebase', '../main'])
        self.run_bzr('resolved hello')
        self.check_output('', 'rebase-continue')
        self.check_output('3\n', 'revno')

    def test_continue_nothing(self):
        self.run_bzr_error(['bzr: ERROR: No rebase to continue'],
                           ['rebase-continue'])

    def test_abort_nothing(self):
        self.run_bzr_error(['bzr: ERROR: No rebase to abort'],
                           ['rebase-abort'])

    def test_todo_nothing(self):
        self.run_bzr_error(['bzr: ERROR: No rebase in progress'],
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
        self.check_output('', 'rebase --onto -2 ../main')
        self.check_output('3\n', 'revno')

    def test_unrelated(self):
        os.chdir('..')
        os.mkdir('unrelated')
        os.chdir('unrelated')
        self.run_bzr('init')
        self.make_file('hello', "hi world")
        self.run_bzr('add')
        self.run_bzr('commit -m x')
        self.run_bzr_error(['bzr: ERROR: Branches have no common ancestor, and no merge base.*'],
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
        self.check_output('3\n', 'revno')

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

class ReplayTests(ExternalBase):
    def test_replay(self):
        os.mkdir('main')
        os.chdir('main')
        self.run_bzr('init')
        open('bar', 'w').write('42')
        self.run_bzr('add')
        self.run_bzr('commit -m that')
        os.mkdir('../feature')
        os.chdir('../feature')
        self.run_bzr('init')
        branch = Branch.open('.')
        open('hello', 'w').write("my data")
        self.run_bzr('add')
        self.run_bzr('commit -m this')
        self.assertEquals(1, len(branch.revision_history()))
        self.run_bzr('replay -r1 ../main')
        self.assertEquals(2, len(branch.revision_history()))
        self.assertTrue(os.path.exists('bar'))

class ReplayTests(ExternalBase):
    def test_replay(self):
        os.mkdir('main')
        os.chdir('main')
        self.run_bzr('init')
        open('bar', 'w').write('42')
        self.run_bzr('add')
        self.run_bzr('commit -m that')
        open('bar', 'w').write('84')
        self.run_bzr('commit -m blathat')
        os.mkdir('../feature')
        os.chdir('../feature')
        self.run_bzr('init')
        branch = Branch.open('.')
        open('hello', 'w').write("my data")
        self.run_bzr('add')
        self.run_bzr('commit -m this')
        self.assertEquals(1, len(branch.revision_history()))
        self.run_bzr('replay -r1.. ../main')
        self.assertEquals(3, len(branch.revision_history()))
        self.assertTrue(os.path.exists('bar'))
