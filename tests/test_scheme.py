# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib.errors import NotBranchError

from bzrlib.tests import TestCase
from scheme import (ListBranchingScheme, NoBranchingScheme, 
                    BranchingScheme, TrunkBranchingScheme)

class BranchingSchemeTest(TestCase):
    def test_guess_empty(self):
        self.assertIsInstance(BranchingScheme.guess_scheme(""), 
                              NoBranchingScheme)

    def test_guess_not_convenience(self):
        self.assertIsInstance(BranchingScheme.guess_scheme("foo"), 
                              NoBranchingScheme)

    def test_find_scheme_no(self):
        self.assertIsInstance(BranchingScheme.find_scheme("none"),
                              NoBranchingScheme)

    def test_find_scheme_invalid(self):
        self.assertIs(None, BranchingScheme.find_scheme("foo"))

    def test_find_scheme_trunk(self):
        scheme = BranchingScheme.find_scheme("trunk")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(0, scheme.level)

    def test_find_scheme_trunk_0(self):
        scheme = BranchingScheme.find_scheme("trunk-0")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(0, scheme.level)

    def test_find_scheme_trunk_2(self):
        scheme = BranchingScheme.find_scheme("trunk-2")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(2, scheme.level)

    def test_find_scheme_trunk_invalid(self):
        scheme = BranchingScheme.find_scheme("trunk-invalid")
        self.assertIs(None, scheme)


class NoScheme(TestCase):
    def test_is_branch_empty(self):
        self.assertTrue(NoBranchingScheme().is_branch(""))

    def test_is_branch_slash(self):
        self.assertTrue(NoBranchingScheme().is_branch("/"))

    def test_is_branch_dir_slash(self):
        self.assertFalse(NoBranchingScheme().is_branch("/foo"))

    def test_is_branch_dir_slash_nested(self):
        self.assertFalse(NoBranchingScheme().is_branch("/foo/foo"))

    def test_is_branch_dir(self):
        self.assertFalse(NoBranchingScheme().is_branch("foo/bar"))

    def test_is_branch_dir_doubleslash(self):
        self.assertFalse(NoBranchingScheme().is_branch("//foo/bar"))

    def test_unprefix(self):
        self.assertEqual(NoBranchingScheme().unprefix(""), ("", ""))
        self.assertEqual(NoBranchingScheme().unprefix("/"), ("", ""))
        self.assertEqual(NoBranchingScheme().unprefix("foo/foo"), ("", "foo/foo"))
        self.assertEqual(NoBranchingScheme().unprefix("/foo/foo"), ("", "foo/foo"))

class ListScheme(TestCase):
    def test_is_branch(self):
        scheme = ListBranchingScheme(["foo", "bar/bloe"])
        self.assertFalse(scheme.is_branch(""))
        self.assertFalse(scheme.is_branch("/"))
        self.assertTrue(scheme.is_branch("/foo"))
        self.assertTrue(scheme.is_branch("foo"))
        self.assertFalse(scheme.is_branch("/foo/foo"))
        self.assertFalse(scheme.is_branch("foo/bar"))
        self.assertFalse(scheme.is_branch("foobla"))
        self.assertTrue(scheme.is_branch("//foo/"))
        self.assertTrue(scheme.is_branch("bar/bloe"))

    def test_unprefix(self):
        scheme = ListBranchingScheme(["foo", "bar/bloe"])
        self.assertRaises(NotBranchError, scheme.unprefix, "")
        self.assertRaises(NotBranchError, scheme.unprefix, "/")
        self.assertRaises(NotBranchError, scheme.unprefix, "blie/bloe/bla")
        self.assertEqual(scheme.unprefix("/foo"), ("foo", ""))
        self.assertEqual(scheme.unprefix("foo"), ("foo", ""))
        self.assertEqual(scheme.unprefix("/foo/foo"), ("foo", "foo"))
        self.assertEqual(scheme.unprefix("foo/bar"), ("foo", "bar"))
        self.assertEqual(scheme.unprefix("foo/bar/bla"), ("foo", "bar/bla"))
        self.assertEqual(scheme.unprefix("//foo/"), ("foo", ""))
        self.assertEqual(scheme.unprefix("bar/bloe"), ("bar/bloe", ""))

class TrunkScheme(TestCase):
    def test_is_branch(self):
        scheme = TrunkBranchingScheme()
        self.assertFalse(scheme.is_branch(""))
        self.assertFalse(scheme.is_branch("/"))
        self.assertFalse(scheme.is_branch("/foo"))
        self.assertFalse(scheme.is_branch("foo"))
        self.assertFalse(scheme.is_branch("/foo/foo"))
        self.assertFalse(scheme.is_branch("foo/bar"))
        self.assertFalse(scheme.is_branch("foobla"))
        self.assertTrue(scheme.is_branch("/trunk/"))
        self.assertTrue(scheme.is_branch("////trunk"))
        self.assertTrue(scheme.is_branch("/branches/foo"))
        self.assertFalse(scheme.is_branch("/branche/foo"))
        self.assertFalse(scheme.is_branch("/branchesfoo"))
        self.assertTrue(scheme.is_branch("/branches/foo/"))
        self.assertFalse(scheme.is_branch("/trunkfoo"))
        self.assertFalse(scheme.is_branch("/trunk/foo"))
        self.assertFalse(scheme.is_branch("/branches"))

    def test_is_branch_level(self):
        scheme = TrunkBranchingScheme(2)
        self.assertFalse(scheme.is_branch("/trunk/"))
        self.assertFalse(scheme.is_branch("/foo/trunk"))
        self.assertTrue(scheme.is_branch("/foo/bar/trunk"))
        self.assertFalse(scheme.is_branch("/branches/trunk"))
        self.assertTrue(scheme.is_branch("/bar/branches/trunk"))

    def test_unprefix(self):
        scheme = TrunkBranchingScheme()
        self.assertRaises(NotBranchError, scheme.unprefix, "")
        self.assertRaises(NotBranchError, scheme.unprefix, "branches")
        self.assertRaises(NotBranchError, scheme.unprefix, "/")
        self.assertRaises(NotBranchError, scheme.unprefix, "blie/bloe/bla")
        self.assertRaises(NotBranchError, scheme.unprefix, "aa")
        self.assertEqual(scheme.unprefix("/trunk"), ("trunk", ""))
        self.assertEqual(scheme.unprefix("branches/ver1/foo"), ("branches/ver1", "foo"))
        self.assertEqual(scheme.unprefix("tags/ver1"), ("tags/ver1", ""))
        self.assertEqual(scheme.unprefix("//trunk/foo"), ("trunk", "foo"))
        self.assertEqual(scheme.unprefix("/tags/ver2/foo/bar"), ("tags/ver2", "foo/bar"))

    def test_unprefix_level(self):
        scheme = TrunkBranchingScheme(1)
        self.assertRaises(NotBranchError, scheme.unprefix, "trunk")
        self.assertRaises(NotBranchError, scheme.unprefix, "/branches/foo")
        self.assertRaises(NotBranchError, scheme.unprefix, "branches/ver1/foo")
        self.assertEqual(scheme.unprefix("/foo/trunk"), ("foo/trunk", ""))
        self.assertEqual(scheme.unprefix("data/tags/ver1"), ("data/tags/ver1", ""))

    def test_guess(self):
        scheme = BranchingScheme.guess_scheme("trunk") 
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(0, scheme.level)
        scheme = BranchingScheme.guess_scheme("branches/foo/bar")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(0, scheme.level)
        scheme = BranchingScheme.guess_scheme("test/branches/foo/bar")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(1, scheme.level)
        scheme = BranchingScheme.guess_scheme("test/bar/branches/foo/bar")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(2, scheme.level)
        scheme = BranchingScheme.guess_scheme("branches/trunk")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(0, scheme.level)

