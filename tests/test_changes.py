# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from bzrlib.tests import TestCase
from bzrlib.plugins.svn.changes import path_is_child, find_prev_location, changes_path

class PathIsChildTests(TestCase):
    def test_both_empty(self):
        self.assertTrue(path_is_child("", ""))

    def test_child_path(self):
        self.assertTrue(path_is_child("trunk", "trunk/bar"))

    def test_self(self):
        self.assertTrue(path_is_child("trunk", "trunk"))

    def test_child_empty_bp(self):
        self.assertTrue(path_is_child("", "bar"))

    def test_unrelated(self):
        self.assertFalse(path_is_child("bla", "bar"))
