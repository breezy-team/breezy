# Copyright (C) 2006 Canonical Ltd
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

import os

from bzrlib import (
    conflicts
    )
from bzrlib.workingtree import WorkingTree
from bzrlib.tests.blackbox import ExternalBase

# FIXME: These don't really look at the output of the conflict commands, just
# the number of lines - there should be more examination.

class TestConflicts(ExternalBase):

    def setUp(self):
        super(ExternalBase, self).setUp()
        try:
            os.mkdir('a')
        except:
            raise os.getcwd()
        os.chdir('a')
        self.run_bzr('init')
        file('myfile', 'wb').write('contentsa\n')
        file('my_other_file', 'wb').write('contentsa\n')
        os.mkdir('mydir')
        self.run_bzr('add')
        self.run_bzr('commit -m new')
        os.chdir('..')
        self.run_bzr('branch a b')
        os.chdir('b')
        file('myfile', 'wb').write('contentsb\n')
        file('my_other_file', 'wb').write('contentsb\n')
        self.run_bzr('mv mydir mydir2')
        self.run_bzr('commit -m change')
        os.chdir('../a')
        file('myfile', 'wb').write('contentsa2\n')
        file('my_other_file', 'wb').write('contentsa2\n')
        self.run_bzr('mv mydir mydir3')
        self.run_bzr('commit -m change')
        self.run_bzr('merge ../b', retcode=1)

    def test_conflicts(self):
        conflicts, errs = self.run_bzr(['conflicts'])
        self.assertEqual(3, len(conflicts.splitlines()))

    def test_conflicts_text(self):
        conflicts = self.run_bzr('conflicts', '--text')[0].splitlines()
        self.assertEqual(['my_other_file', 'myfile'], conflicts)

    def test_resolve(self):
        self.run_bzr('resolve myfile')
        conflicts, errs = self.run_bzr(['conflicts'])
        self.assertEqual(2, len(conflicts.splitlines()))
        self.run_bzr('resolve my_other_file')
        self.run_bzr('resolve mydir2')
        conflicts, errs = self.run_bzr(['conflicts'])
        self.assertEqual(len(conflicts.splitlines()), 0)

    def test_resolve_all(self):
        self.run_bzr('resolve --all')
        conflicts, errs = self.run_bzr(['conflicts'])
        self.assertEqual(len(conflicts.splitlines()), 0)

    def test_resolve_in_subdir(self):
        """resolve when run from subdirectory should handle relative paths"""
        orig_dir = os.getcwdu()
        try:
            os.mkdir("subdir")
            os.chdir("subdir")
            self.run_bzr("resolve ../myfile")
            os.chdir("../../b")
            self.run_bzr("resolve ../a/myfile")
            wt = WorkingTree.open_containing('.')[0]
            conflicts = wt.conflicts()
            if not conflicts.is_empty():
                self.fail("tree still contains conflicts: %r" % conflicts)
        finally:
            os.chdir(orig_dir)

    def test_auto_resolve(self):
        """Text conflicts can be resolved automatically"""
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file',
            '<<<<<<<\na\n=======\n>>>>>>>\n')])
        tree.add('file', 'file_id')
        self.assertEqual(tree.kind('file_id'), 'file')
        file_conflict = conflicts.TextConflict('file', file_id='file_id')
        tree.set_conflicts(conflicts.ConflictList([file_conflict]))
        os.chdir('tree')
        note = self.run_bzr('resolve', retcode=1)[1]
        self.assertContainsRe(note, '0 conflict\\(s\\) auto-resolved.')
        self.assertContainsRe(note,
            'Remaining conflicts:\nText conflict in file')
        self.build_tree_contents([('file', 'a\n')])
        note = self.run_bzr('resolve')[1]
        self.assertContainsRe(note, 'All conflicts resolved.')
