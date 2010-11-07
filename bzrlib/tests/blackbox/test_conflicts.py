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

def make_tree_with_conflicts(test, this_path='this', other_path='other'):
    this_tree = test.make_branch_and_tree(this_path)
    test.build_tree_contents([
        ('%s/myfile' % (this_path,), 'this content\n'),
        ('%s/my_other_file' % (this_path,), 'this content\n'),
        ('%s/mydir/' % (this_path,),),
        ])
    this_tree.add('myfile')
    this_tree.add('my_other_file')
    this_tree.add('mydir')
    this_tree.commit(message="new")
    other_tree = this_tree.bzrdir.sprout(other_path).open_workingtree()
    test.build_tree_contents([
        ('%s/myfile' % (other_path,), 'contentsb\n'),
        ('%s/my_other_file' % (other_path,), 'contentsb\n'),
        ])
    other_tree.rename_one('mydir', 'mydir2')
    other_tree.commit(message="change")
    test.build_tree_contents([
        ('%s/myfile' % (this_path,), 'contentsa2\n'),
        ('%s/my_other_file' % (this_path,), 'contentsa2\n'),
        ])
    this_tree.rename_one('mydir', 'mydir3')
    this_tree.commit(message='change')
    this_tree.merge_from_branch(other_tree.branch)
    return this_tree, other_tree


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
