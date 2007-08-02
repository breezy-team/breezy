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
"""Couple of blackbox tests for the rebase plugin."""

from bzrlib.branch import Branch
from bzrlib.tests.blackbox import ExternalBase

import os

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
        self.run_bzr_error(['bzr: ERROR: Already rebased on .*'], 
                           'rebase ../main')

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
        self.make_file('hello', '42')
        self.run_bzr('commit -m that')
        os.chdir('../feature')
        self.make_file('hoi', "my data")
        self.run_bzr('add')
        self.run_bzr('commit -m this')
        self.make_file('hooi', "your data")
        self.run_bzr('add')
        self.run_bzr('commit -m that')
        self.make_file('hoooi', "someone else's data")
        self.run_bzr('add')
        self.run_bzr('commit -m these')
        self.check_output('', 'rebase -r2..3 ../main')
        self.check_output('4\n', 'revno')

    def test_range_open_end(self):
        self.make_file('hello', '42')
        self.run_bzr('commit -m that')
        os.chdir('../feature')
        self.make_file('hoi', "my data")
        self.run_bzr('add')
        self.run_bzr('commit -m this')
        self.make_file('hooi', "your data")
        self.run_bzr('add')
        self.run_bzr('commit -m that')
        self.make_file('hoooi', "someone else's data")
        self.run_bzr('add')
        self.run_bzr('commit -m these')
        self.check_output('', 'rebase -r4.. ../main')
        self.check_output('3\n', 'revno')
        branch = Branch.open(".")
        self.assertEquals("these", 
            branch.repository.get_revision(branch.last_revision()).message)

    def test_conflicting(self):
        self.make_file('hello', '42')
        self.run_bzr('commit -m that')
        os.chdir('../feature')
        self.make_file('hello', "other data")
        self.run_bzr('commit -m this')
        self.run_bzr_error('Text conflict in hello\nbzr: ERROR: A conflict occurred replaying a commit. Resolve the conflict and run \'bzr rebase-continue\' or run \'bzr rebase-abort\'.\n', 'rebase ../main')

    def test_conflicting_abort(self):
        self.make_file('hello', '42')
        self.run_bzr('commit -m that')
        os.chdir('../feature')
        self.make_file('hello', "other data")
        self.run_bzr('commit -m this')
        old_log = self.run_bzr('log')[0]
        self.run_bzr_error('Text conflict in hello\nbzr: ERROR: A conflict occurred replaying a commit. Resolve the conflict and run \'bzr rebase-continue\' or run \'bzr rebase-abort\'.\n', 'rebase ../main')
        self.check_output('', 'rebase-abort')
        self.check_output(old_log, 'log')

    def test_conflicting_continue(self):
        self.make_file('hello', '42')
        self.run_bzr('commit -m that')
        os.chdir('../feature')
        self.make_file('hello', "other data")
        self.run_bzr('commit -m this')
        self.run_bzr_error('Text conflict in hello\nbzr: ERROR: A conflict occurred replaying a commit. Resolve the conflict and run \'bzr rebase-continue\' or run \'bzr rebase-abort\'.\n', 'rebase ../main')
        self.run_bzr('resolved hello')
        self.check_output('', 'rebase-continue')
        self.check_output('3\n', 'revno')

    def test_continue_nothing(self):
        self.run_bzr_error('bzr: ERROR: No rebase to continue', 
                           'rebase-continue')

    def test_abort_nothing(self):
        self.run_bzr_error('bzr: ERROR: No rebase to abort', 
                           'rebase-abort')

    def test_todo_nothing(self):
        self.run_bzr_error('bzr: ERROR: No rebase in progress', 
                           'rebase-todo')

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
