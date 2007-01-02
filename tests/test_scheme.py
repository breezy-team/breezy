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
    def test_str(self):
        self.assertEqual("null", NoBranchingScheme().__str__())

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

    def test_unprefix_slash(self):
        self.assertEqual(NoBranchingScheme().unprefix("/"), ("", ""))

    def test_unprefix_nested(self):
        self.assertEqual(NoBranchingScheme().unprefix("foo/foo"), ("", "foo/foo"))

    def test_unprefix_slash_nested(self):
        self.assertEqual(NoBranchingScheme().unprefix("/foo/foo"), ("", "foo/foo"))

    def test_is_branch_parent_root(self):
        self.assertFalse(NoBranchingScheme().is_branch_parent(""))

    def test_is_branch_parent_other(self):
        self.assertFalse(NoBranchingScheme().is_branch_parent("trunk/foo"))

class ListScheme(TestCase):
    def setUp(self):
        self.scheme = ListBranchingScheme(["foo", "bar/bloe"])

    def test_is_branch_empty(self):
        self.assertFalse(self.scheme.is_branch(""))

    def test_is_branch_slash(self):
        self.assertFalse(self.scheme.is_branch("/"))

    def test_is_branch_slashsub(self):
        self.assertTrue(self.scheme.is_branch("/foo"))

    def test_is_branch_sub(self):
        self.assertTrue(self.scheme.is_branch("foo"))

    def test_is_branch_sub_sub_slash(self):
        self.assertFalse(self.scheme.is_branch("/foo/foo"))

    def test_is_branch_sub_sub(self):
        self.assertFalse(self.scheme.is_branch("foo/bar"))

    def test_is_branch_unknown(self):
        self.assertFalse(self.scheme.is_branch("foobla"))

    def test_is_branch_doubleslash(self):
        self.assertTrue(self.scheme.is_branch("//foo/"))

    def test_is_branch_nested(self):
        self.assertTrue(self.scheme.is_branch("bar/bloe"))

    def test_unprefix_notbranch_empty(self):
        self.assertRaises(NotBranchError, self.scheme.unprefix, "")

    def test_unprefix_notbranch_slash(self):
        self.assertRaises(NotBranchError, self.scheme.unprefix, "/")

    def test_unprefix_notbranch_unknown(self):
        self.assertRaises(NotBranchError, self.scheme.unprefix, "blie/bloe/bla")

    def test_unprefix_branch_slash(self):
        self.assertEqual(self.scheme.unprefix("/foo"), ("foo", ""))

    def test_unprefix_branch(self):
        self.assertEqual(self.scheme.unprefix("foo"), ("foo", ""))

    def test_unprefix_nested_slash(self):
        self.assertEqual(self.scheme.unprefix("/foo/foo"), ("foo", "foo"))

    def test_unprefix_nested(self):
        self.assertEqual(self.scheme.unprefix("foo/bar"), ("foo", "bar"))

    def test_unprefix_double_nested(self):
        self.assertEqual(self.scheme.unprefix("foo/bar/bla"), ("foo", "bar/bla"))

    def test_unprefix_double_slash(self):
        self.assertEqual(self.scheme.unprefix("//foo/"), ("foo", ""))

    def test_unprefix_nested_branch(self):
        self.assertEqual(self.scheme.unprefix("bar/bloe"), ("bar/bloe", ""))

class TrunkScheme(TestCase):
    def test_is_branch_empty(self):
        self.assertFalse(TrunkBranchingScheme().is_branch(""))

    def test_is_branch_slash(self):
        self.assertFalse(TrunkBranchingScheme().is_branch("/"))

    def test_is_branch_unknown_slash(self):
        self.assertFalse(TrunkBranchingScheme().is_branch("/foo"))

    def test_is_branch_unknown(self):
        self.assertFalse(TrunkBranchingScheme().is_branch("foo"))

    def test_is_branch_unknown_nested_slash(self):
        self.assertFalse(TrunkBranchingScheme().is_branch("/foo/foo"))

    def test_is_branch_unknown_nested(self):
        self.assertFalse(TrunkBranchingScheme().is_branch("foo/bar"))

    def test_is_branch_unknown2(self):
        self.assertFalse(TrunkBranchingScheme().is_branch("foobla"))

    def test_is_branch_trunk(self):
        self.assertTrue(TrunkBranchingScheme().is_branch("/trunk/"))

    def test_is_branch_trunk_slashes(self):
        self.assertTrue(TrunkBranchingScheme().is_branch("////trunk"))

    def test_is_branch_branch(self):
        self.assertTrue(TrunkBranchingScheme().is_branch("/branches/foo"))

    def test_is_branch_typo(self):
        self.assertFalse(TrunkBranchingScheme().is_branch("/branche/foo"))

    def test_is_branch_missing_slash(self):
        self.assertFalse(TrunkBranchingScheme().is_branch("/branchesfoo"))

    def test_is_branch_branch_slash(self):
        self.assertTrue(TrunkBranchingScheme().is_branch("/branches/foo/"))

    def test_is_branch_trunk_missing_slash(self):
        self.assertFalse(TrunkBranchingScheme().is_branch("/trunkfoo"))

    def test_is_branch_trunk_file(self):
        self.assertFalse(TrunkBranchingScheme().is_branch("/trunk/foo"))

    def test_is_branch_branches(self):
        self.assertFalse(TrunkBranchingScheme().is_branch("/branches"))

    def test_is_branch_level(self):
        scheme = TrunkBranchingScheme(2)
        self.assertFalse(scheme.is_branch("/trunk/"))
        self.assertFalse(scheme.is_branch("/foo/trunk"))
        self.assertTrue(scheme.is_branch("/foo/bar/trunk"))
        self.assertFalse(scheme.is_branch("/branches/trunk"))
        self.assertTrue(scheme.is_branch("/bar/branches/trunk"))

    def test_unprefix_empty(self):
        self.assertRaises(NotBranchError, TrunkBranchingScheme().unprefix, "")

    def test_unprefix_topdir(self):
        self.assertRaises(NotBranchError, TrunkBranchingScheme().unprefix, "branches")

    def test_unprefix_slash(self):
        self.assertRaises(NotBranchError, TrunkBranchingScheme().unprefix, "/")

    def test_unprefix_unknown_sub(self):
        self.assertRaises(NotBranchError, TrunkBranchingScheme().unprefix, "blie/bloe/bla")

    def test_unprefix_unknown(self):
        self.assertRaises(NotBranchError, TrunkBranchingScheme().unprefix, "aa")

    def test_unprefix_slash_branch(self):
        self.assertEqual(TrunkBranchingScheme().unprefix("/trunk"), ("trunk", ""))

    def test_unprefix_nested_branch_sub(self):
        self.assertEqual(TrunkBranchingScheme().unprefix("branches/ver1/foo"), ("branches/ver1", "foo"))

    def test_unprefix_nested_tag_sub(self):
        self.assertEqual(TrunkBranchingScheme().unprefix("tags/ver1"), ("tags/ver1", ""))

    def test_unprefix_doubleslash_branch(self):
        self.assertEqual(TrunkBranchingScheme().unprefix("//trunk/foo"), ("trunk", "foo"))

    def test_unprefix_slash_tag(self):
        self.assertEqual(TrunkBranchingScheme().unprefix("/tags/ver2/foo/bar"), ("tags/ver2", "foo/bar"))

    def test_unprefix_level(self):
        self.assertRaises(NotBranchError, TrunkBranchingScheme(1).unprefix, "trunk")

    def test_unprefix_level_wrong_level(self):
        self.assertRaises(NotBranchError, TrunkBranchingScheme(1).unprefix, "/branches/foo")

    def test_unprefix_level_wrong_level_nested(self):
        self.assertRaises(NotBranchError, TrunkBranchingScheme(1).unprefix, "branches/ver1/foo")

    def test_unprefix_level_correct_branch(self):
        self.assertEqual(TrunkBranchingScheme(1).unprefix("/foo/trunk"), ("foo/trunk", ""))

    def test_unprefix_level_correct_nested(self):
        self.assertEqual(TrunkBranchingScheme(1).unprefix("data/tags/ver1"), ("data/tags/ver1", ""))

    def test_guess_trunk_zero(self):
        scheme = BranchingScheme.guess_scheme("trunk") 
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(0, scheme.level)

    def test_guess_trunk_branch_sub(self):
        scheme = BranchingScheme.guess_scheme("branches/foo/bar")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(0, scheme.level)

    def test_guess_trunk_level(self):
        scheme = BranchingScheme.guess_scheme("test/branches/foo/bar")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(1, scheme.level)

    def test_guess_trunk_level_sub(self):
        scheme = BranchingScheme.guess_scheme("test/bar/branches/foo/bar")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(2, scheme.level)

    def test_guess_level_detection(self):
        scheme = BranchingScheme.guess_scheme("branches/trunk")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(0, scheme.level)

    def test_str0(self):
        self.assertEqual("trunk0", TrunkBranchingScheme().__str__())

    def test_str1(self):
        self.assertEqual("trunk1", TrunkBranchingScheme(1).__str__())
        
    def test_is_branch_parent_root(self):
        self.assertTrue(TrunkBranchingScheme().is_branch_parent(""))

    def test_is_branch_parent_branches(self):
        self.assertTrue(TrunkBranchingScheme().is_branch_parent("branches"))

    def test_is_branch_parent_trunk(self):
        self.assertFalse(TrunkBranchingScheme().is_branch_parent("trunk"))

    def test_is_branch_parent_level(self):
        self.assertTrue(TrunkBranchingScheme(1).is_branch_parent("anything"))

    def test_is_branch_parent_level_root(self):
        self.assertTrue(TrunkBranchingScheme(1).is_branch_parent(""))

    def test_is_branch_parent_level_strange(self):
        self.assertFalse(TrunkBranchingScheme(1).is_branch_parent("trunk/foo"))

    def test_is_branch_parent_level_inside(self):
        self.assertFalse(TrunkBranchingScheme(1).is_branch_parent("foo/trunk/foo"))

    def test_is_branch_parent_level_branches(self):
        self.assertTrue(TrunkBranchingScheme(1).is_branch_parent("anything/branches"))

    def test_is_branch_parent_other(self):
        self.assertFalse(TrunkBranchingScheme().is_branch_parent("trunk/foo"))
