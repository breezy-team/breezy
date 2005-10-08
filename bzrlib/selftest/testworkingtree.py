# (C) 2005 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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
from bzrlib.branch import Branch
from bzrlib.selftest import TestCaseInTempDir
from bzrlib.trace import mutter
from bzrlib.workingtree import TreeEntry, TreeDirectory, TreeFile, TreeLink

class TestTreeDirectory(TestCaseInTempDir):

    def test_kind_character(self):
        self.assertEqual(TreeDirectory().kind_character(), '/')


class TestTreeEntry(TestCaseInTempDir):

    def test_kind_character(self):
        self.assertEqual(TreeEntry().kind_character(), '???')


class TestTreeFile(TestCaseInTempDir):

    def test_kind_character(self):
        self.assertEqual(TreeFile().kind_character(), '')


class TestTreeLink(TestCaseInTempDir):

    def test_kind_character(self):
        self.assertEqual(TreeLink().kind_character(), '')


class TestWorkingTree(TestCaseInTempDir):

    def test_listfiles(self):
        branch = Branch.initialize('.')
        os.mkdir('dir')
        print >> open('file', 'w'), "content"
        os.symlink('target', 'symlink')
        tree = branch.working_tree()
        files = list(tree.list_files())
        self.assertEqual(files[0], ('dir', '?', 'directory', None, TreeDirectory()))
        self.assertEqual(files[1], ('file', '?', 'file', None, TreeFile()))
        self.assertEqual(files[2], ('symlink', '?', 'symlink', None, TreeLink()))
