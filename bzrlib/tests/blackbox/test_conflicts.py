# Copyright (C) 2006, 2007, 2009, 2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

from bzrlib import (
    conflicts,
    tests,
    workingtree,
    )
from bzrlib.tests import script


# FIXME: These don't really look at the output of the conflict commands, just
# the number of lines - there should be more examination.

class TestConflictsBase(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestConflictsBase, self).setUp()
        self.make_tree_with_conflicts()

    def make_tree_with_conflicts(self):
        a_tree = self.make_branch_and_tree('a')
        self.build_tree_contents([
            ('a/myfile', 'contentsa\n'),
            ('a/my_other_file', 'contentsa\n'),
            ('a/mydir/',),
            ])
        a_tree.add('myfile')
        a_tree.add('my_other_file')
        a_tree.add('mydir')
        a_tree.commit(message="new")
        b_tree = a_tree.bzrdir.sprout('b').open_workingtree()
        self.build_tree_contents([
            ('b/myfile', 'contentsb\n'),
            ('b/my_other_file', 'contentsb\n'),
            ])
        b_tree.rename_one('mydir', 'mydir2')
        b_tree.commit(message="change")
        self.build_tree_contents([
            ('a/myfile', 'contentsa2\n'),
            ('a/my_other_file', 'contentsa2\n'),
            ])
        a_tree.rename_one('mydir', 'mydir3')
        a_tree.commit(message='change')
        a_tree.merge_from_branch(b_tree.branch)

    def run_bzr(self, cmd, working_dir='a', **kwargs):
        return super(TestConflictsBase, self).run_bzr(
            cmd, working_dir=working_dir, **kwargs)


class TestConflicts(TestConflictsBase):

    def test_conflicts(self):
        out, err = self.run_bzr('conflicts')
        self.assertEqual(3, len(out.splitlines()))

    def test_conflicts_text(self):
        out, err = self.run_bzr('conflicts --text')
        self.assertEqual(['my_other_file', 'myfile'], out.splitlines())

    def test_conflicts_directory(self):
        """Test --directory option"""
        out, err = self.run_bzr('conflicts --directory a', working_dir='.')
        self.assertEqual(3, len(out.splitlines()))
        self.assertEqual('', err)


class TestResolve(TestConflictsBase):

    def test_resolve(self):
        self.run_bzr('resolve myfile')
        out, err = self.run_bzr('conflicts')
        self.assertEqual(2, len(out.splitlines()))
        self.run_bzr('resolve my_other_file')
        self.run_bzr('resolve mydir2')
        out, err = self.run_bzr('conflicts')
        self.assertEqual(0, len(out.splitlines()))

    def test_resolve_all(self):
        self.run_bzr('resolve --all')
        out, err = self.run_bzr('conflicts')
        self.assertEqual(0, len(out.splitlines()))

    def test_resolve_in_subdir(self):
        """resolve when run from subdirectory should handle relative paths"""
        self.build_tree(["a/subdir/"])
        self.run_bzr("resolve ../myfile", working_dir='a/subdir')
        self.run_bzr("resolve ../a/myfile", working_dir='b')
        wt = workingtree.WorkingTree.open_containing('b')[0]
        conflicts = wt.conflicts()
        self.assertEqual(True, conflicts.is_empty(),
                         "tree still contains conflicts: %r" % conflicts)

    def test_auto_resolve(self):
        """Text conflicts can be resolved automatically"""
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file',
            '<<<<<<<\na\n=======\n>>>>>>>\n')])
        tree.add('file', 'file_id')
        self.assertEqual(tree.kind('file_id'), 'file')
        file_conflict = conflicts.TextConflict('file', file_id='file_id')
        tree.set_conflicts(conflicts.ConflictList([file_conflict]))
        note = self.run_bzr('resolve', retcode=1, working_dir='tree')[1]
        self.assertContainsRe(note, '0 conflict\\(s\\) auto-resolved.')
        self.assertContainsRe(note,
            'Remaining conflicts:\nText conflict in file')
        self.build_tree_contents([('tree/file', 'a\n')])
        note = self.run_bzr('resolve', working_dir='tree')[1]
        self.assertContainsRe(note, 'All conflicts resolved.')

    def test_resolve_all_directory(self):
        """Test --directory option"""
        out, err = self.run_bzr('resolve --all -d a', working_dir='.')
        self.assertEqual('', err)
        out, err = self.run_bzr('conflicts')
        self.assertEqual(0, len(out.splitlines()))

class TestResolveSilentlyIgnore(script.TestCaseWithTransportAndScript):

    def test_bug_646961(self):
        self.run_script("""\
            $ bzr init base
            Created a standalone tree (format: 2a)
            $ cd base
            $ echo >file1
            $ bzr add
            adding file1
            $ bzr ci -m "stuff"
            2>Committing to: .../base/
            2>added file1
            2>Committed revision 1.
            $ cd ..
            $ bzr branch base branch
            2>Branched 1 revision(s).
            $ cd base
            $ echo "1" >> file1
            $ bzr ci -m "branch 1"
            2>Committing to: .../base/
            2>modified file1
            2>Committed revision 2.
            $ cd ../branch
            $ echo "2" >> file1
            $ bzr ci -m "branch 2"
            2>Committing to: .../branch/
            2>modified file1
            2>Committed revision 2.
            $ cd ../base
            $ bzr merge ../branch
            2> M  file1
            2>Text conflict in file1
            2>1 conflicts encountered.
            # The following succeeds silently without resolving the conflict
            $ bzr resolve file1 --take-other
            # The following wil fail when --take-other is implemented
            # for text conflicts
            $ bzr conflicts
            Text conflict in file1
            """)

