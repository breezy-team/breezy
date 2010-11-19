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


class TestConflicts(script.TestCaseWithTransportAndScript):

    def setUp(self):
        super(TestConflicts, self).setUp()
        make_tree_with_conflicts(self, 'branch', 'other')

    def test_conflicts(self):
        self.run_script("""\
$ cd branch
$ bzr conflicts
Text conflict in my_other_file
Path conflict: mydir3 / mydir2
Text conflict in myfile
""")

    def test_conflicts_text(self):
        self.run_script("""\
$ cd branch
$ bzr conflicts --text
my_other_file
myfile
""")

    def test_conflicts_directory(self):
        self.run_script("""\
$ bzr conflicts  -d branch
Text conflict in my_other_file
Path conflict: mydir3 / mydir2
Text conflict in myfile
""")
