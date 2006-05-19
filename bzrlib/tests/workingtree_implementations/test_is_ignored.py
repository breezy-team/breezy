# (C) 2006 Canonical Ltd
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

from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestIsIgnored(TestCaseWithWorkingTree):

    def test_is_ignored(self):
        tree = self.make_branch_and_tree('.')
        # this will break if a tree changes the ignored format. That is fine
        # because at the moment tree format is orthogonal to user data, and
        # .bzrignore is user data so must not be changed by a tree format.
        self.build_tree_contents([
            ('.bzrignore', './rootdir\nrandomfile*\npath/from/ro?t\n')])
        # is_ignored returns the matching ignore regex when a path is ignored.
        # we check some expected matches for each rule, and one or more
        # relevant not-matches that look plausible as cases for bugs.
        self.assertEqual('./rootdir', tree.is_ignored('rootdir'))
        self.assertEqual(None, tree.is_ignored('foo/rootdir'))
        self.assertEqual(None, tree.is_ignored('rootdirtrailer'))
        self.assertEqual('randomfile*', tree.is_ignored('randomfile'))
        self.assertEqual('randomfile*', tree.is_ignored('randomfiles'))
        self.assertEqual('randomfile*', tree.is_ignored('foo/randomfiles'))
        self.assertEqual(None, tree.is_ignored('randomfil'))
        self.assertEqual(None, tree.is_ignored('foo/randomfil'))
        self.assertEqual("path/from/ro?t", tree.is_ignored('path/from/root'))
        self.assertEqual("path/from/ro?t", tree.is_ignored('path/from/roat'))
        self.assertEqual(None, tree.is_ignored('roat'))
