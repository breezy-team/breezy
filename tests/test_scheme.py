# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

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

"""Branching scheme tests."""

from bzrlib.errors import NotBranchError, BzrError

from bzrlib.tests import TestCase
from scheme import (ListBranchingScheme, NoBranchingScheme, 
                    BranchingScheme, TrunkBranchingScheme, 
                    SingleBranchingScheme, UnknownBranchingScheme,
                    parse_list_scheme_text, find_commit_paths, 
                    guess_scheme_from_branch_path, guess_scheme_from_history,
                    guess_scheme_from_path, scheme_from_branch_list)

class BranchingSchemeTest(TestCase):
    def test_is_branch(self):
        self.assertRaises(NotImplementedError, BranchingScheme().is_branch, "")

    def test_is_tag(self):
        self.assertRaises(NotImplementedError, BranchingScheme().is_tag, "")

    def test_is_branch_parent(self):
        self.assertRaises(NotImplementedError, 
                BranchingScheme().is_branch_parent, "")

    def test_is_tag_parent(self):
        self.assertRaises(NotImplementedError, 
                BranchingScheme().is_tag_parent, "")

    def test_unprefix(self):
        self.assertRaises(NotImplementedError, 
                BranchingScheme().unprefix, "")

    def test_find_scheme_no(self):
        self.assertIsInstance(BranchingScheme.find_scheme("none"),
                              NoBranchingScheme)

    def test_find_scheme_invalid(self):
        self.assertRaises(BzrError, lambda: BranchingScheme.find_scheme("foo"))

    def test_find_scheme_trunk(self):
        scheme = BranchingScheme.find_scheme("trunk")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(0, scheme.level)

    def test_find_scheme_trunk_0(self):
        scheme = BranchingScheme.find_scheme("trunk0")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(0, scheme.level)

    def test_find_scheme_trunk_2(self):
        scheme = BranchingScheme.find_scheme("trunk2")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(2, scheme.level)

    def test_find_scheme_trunk_invalid(self):
        self.assertRaises(BzrError, 
                          lambda: BranchingScheme.find_scheme("trunkinvalid"))

    def test_find_scheme_single(self):
        scheme = BranchingScheme.find_scheme("single-habla")
        self.assertIsInstance(scheme, SingleBranchingScheme)
        self.assertEqual("habla", scheme.path)

    def test_unknownscheme(self):
        e = UnknownBranchingScheme("foo")
        self.assertEquals("Branching scheme could not be found: foo", str(e))


class NoScheme(TestCase):
    def test_str(self):
        self.assertEqual("none", NoBranchingScheme().__str__())

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

    def test_is_tag_empty(self):
        self.assertFalse(NoBranchingScheme().is_tag(""))

    def test_is_tag_slash(self):
        self.assertFalse(NoBranchingScheme().is_tag("/"))

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

    def test_is_tag_parent_root(self):
        self.assertFalse(NoBranchingScheme().is_tag_parent(""))

    def test_is_tag_parent_other(self):
        self.assertFalse(NoBranchingScheme().is_tag_parent("trunk/foo"))


class ListScheme(TestCase):
    def setUp(self):
        self.scheme = ListBranchingScheme(["foo", "bar/bloe"])

    def test_create_from_string(self):
        self.scheme = ListBranchingScheme('QlpoOTFBWSZTWXb2s-UAAADBAAAQAQCgACGYGYQYXckU4UJB29rPlA..')
        self.assertEquals(["foo"], self.scheme.branch_list)

    def test_is_tag_empty(self):
        self.assertFalse(self.scheme.is_tag(""))

    def test_is_tag_sub(self):
        self.assertFalse(self.scheme.is_tag("foo"))

    def test_is_tag_tag(self):
        self.assertFalse(self.scheme.is_tag("tags/foo"))

    def test_is_branch_empty(self):
        self.assertFalse(self.scheme.is_branch(""))

    def test_is_branch_slash(self):
        self.assertFalse(self.scheme.is_branch("/"))

    def test_is_branch_wildcard(self):
        scheme = ListBranchingScheme(["trunk/*"])
        self.assertTrue(scheme.is_branch("trunk/foo"))
        self.assertFalse(scheme.is_branch("trunk"))

    def test_is_branch_wildcard_root(self):
        scheme = ListBranchingScheme(["*/trunk"])
        self.assertTrue(scheme.is_branch("bla/trunk"))
        self.assertFalse(scheme.is_branch("trunk"))
        self.assertFalse(scheme.is_branch("bla"))

    def test_is_branch_wildcard_multiple(self):
        scheme = ListBranchingScheme(["*/trunk/*"])
        self.assertTrue(scheme.is_branch("bla/trunk/bloe"))
        self.assertFalse(scheme.is_branch("bla/trunk"))
        self.assertFalse(scheme.is_branch("trunk/bloe"))
        self.assertFalse(scheme.is_branch("blie/trunk/bloe/bla"))
        self.assertFalse(scheme.is_branch("bla"))

    def test_is_branch_parent_root_root(self):
        self.assertFalse(ListBranchingScheme([""]).is_branch_parent(""))

    def test_is_branch_parent_root(self):
        self.assertTrue(ListBranchingScheme(["trunk/*"]).is_branch_parent("trunk"))

    def test_is_branch_parent_other(self):
        self.assertFalse(ListBranchingScheme(["trunk/*"]).is_branch_parent("trunk/foo"))

    def test_is_tag_parent_other(self):
        self.assertFalse(ListBranchingScheme(["trunk"]).is_tag_parent("trunk/foo"))

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

    def test_unprefix_wildcard(self):
        scheme = ListBranchingScheme(["*/trunk"])
        self.assertEquals(("bla/trunk", "foo"), 
                          scheme.unprefix("bla/trunk/foo"))

    def test_unprefix_wildcard_multiple(self):
        scheme = ListBranchingScheme(["trunk/*/*"])
        self.assertEquals(("trunk/foo/bar", "bla/blie"), 
                          scheme.unprefix("trunk/foo/bar/bla/blie"))

    def test_unprefix_wildcard_nonexistant(self):
        scheme = ListBranchingScheme(["*/trunk"])
        self.assertRaises(NotBranchError, self.scheme.unprefix, "bla")
        self.assertRaises(NotBranchError, self.scheme.unprefix, "trunk")
        self.assertRaises(NotBranchError, self.scheme.unprefix, "trunk/bla")

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

    def test_str(self):
        self.assertEqual("list-QlpoOTFBWSZTWSDz6woAAAPRgAAQAACzBJAAIAAiDRo9QgyYjmbjatAeLuSKcKEgQefWFA..", str(self.scheme))

    def test_parse_text(self):
        self.assertEqual(["bla/bloe"], parse_list_scheme_text("bla/bloe\n"))

    def test_parse_text_no_newline(self):
        self.assertEqual(["bla/bloe", "blie"], parse_list_scheme_text("bla/bloe\nblie"))

    def test_parse_text_comment(self):
        self.assertEqual(["bla/bloe", "blie"], parse_list_scheme_text("bla/bloe\n# comment\nblie"))

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

    def test_is_branch_tag(self):
        self.assertFalse(TrunkBranchingScheme().is_branch("tags/foo"))

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

    def test_is_tag_empty(self):
        self.assertFalse(TrunkBranchingScheme().is_tag(""))

    def test_is_tag_sub(self):
        self.assertFalse(TrunkBranchingScheme().is_tag("foo"))

    def test_is_tag_tag(self):
        self.assertTrue(TrunkBranchingScheme().is_tag("tags/foo"))

    def test_is_tag_tag_slash(self):
        self.assertTrue(TrunkBranchingScheme().is_tag("tags/branches/"))

    def test_is_tag_nested(self):
        self.assertFalse(TrunkBranchingScheme().is_tag("tags/foo/bla"))

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

    def test_str0(self):
        self.assertEqual("trunk0", TrunkBranchingScheme().__str__())

    def test_str1(self):
        self.assertEqual("trunk1", TrunkBranchingScheme(1).__str__())
        
    def test_is_branch_parent_root(self):
        self.assertTrue(TrunkBranchingScheme().is_branch_parent(""))

    def test_is_tag_parent_root(self):
        self.assertFalse(TrunkBranchingScheme().is_tag_parent(""))

    def test_is_branch_parent_branches(self):
        self.assertTrue(TrunkBranchingScheme().is_branch_parent("branches"))

    def test_is_tagparent_branches(self):
        self.assertFalse(TrunkBranchingScheme().is_tag_parent("branches"))

    def test_is_tagparent_tags(self):
        self.assertTrue(TrunkBranchingScheme().is_tag_parent("tags"))

    def test_is_branch_parent_tags(self):
        self.assertFalse(TrunkBranchingScheme().is_branch_parent("tags"))

    def test_is_branch_parent_trunk(self):
        self.assertFalse(TrunkBranchingScheme().is_branch_parent("trunk"))

    def test_is_branch_parent_level(self):
        self.assertTrue(TrunkBranchingScheme(1).is_branch_parent("anything"))

    def test_is_tag_parent_level(self):
        self.assertFalse(TrunkBranchingScheme(1).is_tag_parent("anything"))

    def test_is_branch_parent_level_root(self):
        self.assertTrue(TrunkBranchingScheme(1).is_branch_parent(""))

    def test_is_branch_parent_level_strange(self):
        self.assertFalse(TrunkBranchingScheme(1).is_branch_parent("trunk/foo"))

    def test_is_branch_parent_level_inside(self):
        self.assertFalse(TrunkBranchingScheme(1).is_branch_parent("foo/trunk/foo"))

    def test_is_branch_parent_level_branches(self):
        self.assertTrue(TrunkBranchingScheme(1).is_branch_parent("anything/branches"))

    def test_is_tag_parent_level_tags(self):
        self.assertTrue(TrunkBranchingScheme(1).is_tag_parent("anything/tags"))

    def test_is_branch_parent_other(self):
        self.assertFalse(TrunkBranchingScheme().is_branch_parent("trunk/foo"))


class SingleBranchingSchemeTests(TestCase):
    def test_is_branch(self):
        self.assertTrue(SingleBranchingScheme("bla").is_branch("bla"))

    def test_is_branch_tooshort(self):
        self.assertFalse(SingleBranchingScheme("bla").is_branch("bl"))

    def test_is_branch_nested(self):
        self.assertTrue(SingleBranchingScheme("bla/bloe").is_branch("bla/bloe"))

    def test_is_branch_child(self):
        self.assertFalse(SingleBranchingScheme("bla/bloe").is_branch("bla/bloe/blie"))

    def test_is_tag(self):
        self.assertFalse(SingleBranchingScheme("bla/bloe").is_tag("bla/bloe"))

    def test_unprefix(self):
        self.assertEquals(("ha", "ho"), SingleBranchingScheme("ha").unprefix("ha/ho"))

    def test_unprefix_branch(self):
        self.assertEquals(("ha", ""), SingleBranchingScheme("ha").unprefix("ha"))

    def test_unprefix_raises(self):
        self.assertRaises(NotBranchError, SingleBranchingScheme("ha").unprefix, "bla")

    def test_is_branch_parent_not(self):
        self.assertFalse(SingleBranchingScheme("ha").is_branch_parent("bla"))

    def test_is_branch_parent_branch(self):
        self.assertFalse(SingleBranchingScheme("bla/bla").is_branch_parent("bla/bla"))

    def test_is_branch_parent(self):
        self.assertTrue(SingleBranchingScheme("bla/bla").is_branch_parent("bla"))

    def test_is_branch_parent_grandparent(self):
        self.assertFalse(
            SingleBranchingScheme("bla/bla/bla").is_branch_parent("bla"))

    def test_create_empty(self):
        self.assertRaises(BzrError, SingleBranchingScheme, "")

    def test_str(self):
        self.assertEquals("single-ha/bla", str(SingleBranchingScheme("ha/bla")))


class FindCommitPathsTester(TestCase):
    def test_simple_trunk_only(self):
        self.assertEquals(["trunk"], 
            list(find_commit_paths([{"trunk": ('M', None, None)}])))

    def test_branches(self):
        self.assertEquals(["trunk", "branches/bar"], 
            list(find_commit_paths([{"trunk": ('M', None, None)},
                               {"branches/bar": ('A', None, None)}])))

    def test_trunk_more_files(self):
        self.assertEquals(["trunk"],
                list(find_commit_paths([{
                    "trunk/bfile": ('A', None, None),
                    "trunk/afile": ('M', None, None),
                    "trunk": ('A', None, None)
                    }])))

    def test_trunk_more_files_no_root(self):
        self.assertEquals(["trunk"],
                list(find_commit_paths([{
                    "trunk/bfile": ('A', None, None),
                    "trunk/afile": ('M', None, None)
                    }])))


class TestGuessBranchingSchemeFromBranchpath(TestCase):
    def test_guess_empty(self):
        self.assertIsInstance(guess_scheme_from_branch_path(""), 
                              NoBranchingScheme)

    def test_guess_not_convenience(self):
        self.assertIsInstance(guess_scheme_from_branch_path("foo"), 
                              SingleBranchingScheme)

    def test_guess_trunk_zero(self):
        scheme = guess_scheme_from_branch_path("trunk") 
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(0, scheme.level)

    def test_guess_trunk_branch_sub(self):
        scheme = guess_scheme_from_branch_path("branches/bar")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(0, scheme.level)

    def test_guess_trunk_level_sub(self):
        scheme = guess_scheme_from_branch_path("test/bar/branches/bla")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(2, scheme.level)

    def test_guess_level_detection(self):
        scheme = guess_scheme_from_branch_path("branches/trunk")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(0, scheme.level)


class TestGuessBranchingSchemeFromPath(TestCase):
    def test_guess_empty(self):
        self.assertIsInstance(guess_scheme_from_path(""), 
                              NoBranchingScheme)

    def test_guess_not_convenience(self):
        self.assertIsInstance(guess_scheme_from_path("foo"), 
                              NoBranchingScheme)

    def test_guess_trunk_zero(self):
        scheme = guess_scheme_from_path("trunk") 
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(0, scheme.level)

    def test_guess_trunk_nested(self):
        scheme = guess_scheme_from_path("trunk/child") 
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(0, scheme.level)

    def test_guess_trunk_branch_sub(self):
        scheme = guess_scheme_from_path("branches/bar")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(0, scheme.level)

    def test_guess_trunk_level_sub(self):
        scheme = guess_scheme_from_path("test/bar/branches/bla")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(2, scheme.level)

    def test_guess_level_detection(self):
        scheme = guess_scheme_from_path("branches/trunk")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(0, scheme.level)


class TestGuessBranchingSchemeFromHistory(TestCase):
    def test_simple(self):
        scheme = guess_scheme_from_history([
            ("", {"trunk": ('M', None, None)}, 0)], 1)
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(0, scheme.level)

    def test_simple_with_relpath(self):
        scheme = guess_scheme_from_history([
            ("", {"trunk": ('M', None, None)}, 0)], 1, 
            relpath="trunk")
        self.assertIsInstance(scheme, TrunkBranchingScheme)
        self.assertEqual(0, scheme.level)

    def test_simple_prefer_relpath(self):
        scheme = guess_scheme_from_history([
            ("", {"trunk": ('M', None, None)}, 1),
            ("", {"trunk": ('M', None, None)}, 2),
            ("", {"trunk/bar": ('M', None, None)}, 3),
            ], 3, 
            relpath="trunk/bar")
        self.assertIsInstance(scheme, SingleBranchingScheme)
        self.assertEqual("trunk/bar", scheme.path)

    def test_simple_notwant_single(self):
        scheme = guess_scheme_from_history([
            ("", {"foo": ('M', None, None)}, 1),
            ("", {"foo": ('M', None, None)}, 2),
            ("", {"foo/bar": ('M', None, None)}, 3),
            ], 3)
        self.assertIsInstance(scheme, NoBranchingScheme)

    def test_simple_no_bp_common(self):
        scheme = guess_scheme_from_history([
            ("", {"foo": ('M', None, None)}, 1),
            ("", {"trunk": ('M', None, None)}, 2),
            ("", {"trunk": ('M', None, None)}, 3),
            ], 3)
        self.assertIsInstance(scheme, TrunkBranchingScheme)

    def test_simple_no_history(self):
        scheme = guess_scheme_from_history([], 0)
        self.assertIsInstance(scheme, NoBranchingScheme)

    def test_simple_no_history_bp(self):
        scheme = guess_scheme_from_history([], 0, "trunk")
        self.assertIsInstance(scheme, TrunkBranchingScheme)

class SchemeFromBranchListTests(TestCase):
    def test_nobranchingscheme(self):
        self.assertIsInstance(scheme_from_branch_list(["."]), NoBranchingScheme)

    def test_listbranchingscheme(self):
        self.assertIsInstance(scheme_from_branch_list(["aap/*"]), 
                              ListBranchingScheme)

    def test_trunk(self):
        self.assertIsInstance(scheme_from_branch_list(["trunk", "branches/*", 
                                                       "tags/*"]), 
                              TrunkBranchingScheme)

