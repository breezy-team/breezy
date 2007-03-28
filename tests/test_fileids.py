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

from bzrlib.bzrdir import BzrDir
from bzrlib.repository import Repository
from bzrlib.trace import mutter
from bzrlib.tests import TestCase

import sha

from fileids import SimpleFileIdMap, generate_file_id, generate_svn_file_id
from repository import generate_svn_revision_id
from scheme import TrunkBranchingScheme
from tests import TestCaseWithSubversionRepository, RENAMES

class TestComplexFileids(TestCaseWithSubversionRepository):
    # branchtagcopy.dump
    # changeaftercp.dump
    # combinedbranch.dump
    # executable.dump
    # ignore.dump
    # inheritance.dump
    # movebranch.dump
    # movefileorder.dump
    # recreatebranch.dump
    def test_simplemove(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo': "data", "dc/blie": "bloe"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.client_copy("dc/foo", "dc/bar")
        self.client_delete("dc/foo")
        self.build_tree({'dc/bar': "data2"})
        self.client_commit("dc", "Second Message")

        repository = Repository.open("svn+"+repos_url)

        inv1 = repository.get_inventory(
                repository.generate_revision_id(1, ""))
        inv2 = repository.get_inventory(
                repository.generate_revision_id(2, ""))
        mutter('inv1: %r' % inv1.entries())
        mutter('inv2: %r' % inv2.entries())
        if RENAMES:
            self.assertEqual(inv1.path2id("foo"), inv2.path2id("bar"))
        self.assertNotEqual(None, inv1.path2id("foo"))
        self.assertIs(None, inv2.path2id("foo"))
        self.assertNotEqual(None, inv2.path2id("bar"))
        self.assertNotEqual(inv1.path2id("foo"), inv2.path2id("blie"))
        self.assertNotEqual(inv2.path2id("bar"), inv2.path2id("blie"))

    def test_simplecopy(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo': "data", "dc/blie": "bloe"})
        self.client_add("dc/foo")
        self.client_add("dc/blie")
        self.client_commit("dc", "My Message")
        self.client_copy("dc/foo", "dc/bar")
        self.build_tree({'dc/bar': "data2"})
        self.client_commit("dc", "Second Message")

        bzrdir = BzrDir.open("svn+%s" % repos_url)
        repository = bzrdir.find_repository()

        inv1 = repository.get_inventory(
                repository.generate_revision_id(1, ""))
        inv2 = repository.get_inventory(
                repository.generate_revision_id(2, ""))
        self.assertNotEqual(inv1.path2id("foo"), inv2.path2id("bar"))
        self.assertNotEqual(inv1.path2id("foo"), inv2.path2id("blie"))
        self.assertIs(None, inv1.path2id("bar"))
        self.assertNotEqual(None, inv1.path2id("blie"))

    def test_simpledelete(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.client_delete("dc/foo")
        self.client_commit("dc", "Second Message")

        bzrdir = BzrDir.open("svn+%s" % repos_url)
        repository = bzrdir.find_repository()

        inv1 = repository.get_inventory(
                repository.generate_revision_id(1, ""))
        inv2 = repository.get_inventory(
                repository.generate_revision_id(2, ""))
        self.assertNotEqual(None, inv1.path2id("foo"))
        self.assertIs(None, inv2.path2id("foo"))

    def test_replace(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.client_delete("dc/foo")
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "Second Message")

        bzrdir = BzrDir.open("svn+"+repos_url)
        repository = bzrdir.find_repository()

        inv1 = repository.get_inventory(
                repository.generate_revision_id(1, ""))
        inv2 = repository.get_inventory(
                repository.generate_revision_id(2, ""))
        self.assertNotEqual(inv1.path2id("foo"), inv2.path2id("foo"))

    def test_copy_branch(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/trunk/dir/file': "data", 'dc/branches': None})
        self.client_add("dc/trunk")
        self.client_add("dc/branches")
        self.client_commit("dc", "My Message")
        self.client_copy("dc/trunk", "dc/branches/mybranch")
        self.client_commit("dc", "Copy branch")

        bzrdir = BzrDir.open("svn+"+repos_url + "/branches/mybranch")
        repository = bzrdir.find_repository()

        inv1 = repository.get_inventory(
                repository.generate_revision_id(1, "trunk"))
        inv2 = repository.get_inventory(
                repository.generate_revision_id(2, "branches/mybranch"))
        self.assertEqual(inv1.path2id("dir"), inv2.path2id("dir"))
        self.assertEqual(inv1.path2id("dir/file"), inv2.path2id("dir/file"))

        fileid, revid = repository.get_fileid_map(2, 
                            "branches/mybranch")["dir/file"]
        self.assertEqual(fileid, inv1.path2id("dir/file"))
        self.assertEqual(repository.generate_revision_id(1, "trunk"), revid)

def sha1(text):
    return sha.new(text).hexdigest()

class TestFileIdGenerator(TestCase):
    def test_generate_file_id_root(self):
        self.assertEqual("2@uuid:bp:", generate_file_id(generate_svn_revision_id("uuid", 2, "bp"), ""))

    def test_generate_file_id_path(self):
        self.assertEqual("2@uuid:bp:mypath", 
                generate_file_id(generate_svn_revision_id("uuid", 2, "bp"), "mypath"))

    def test_generate_file_id_long(self):
        dir = "this/is/a" + ("/very"*40) + "/long/path/"
        self.assertEqual("2@uuid:bp;" + sha1(dir+"filename"), 
                generate_file_id(generate_svn_revision_id("uuid", 2, "bp"), dir+"filename"))

    def test_generate_revid_special_char_ascii(self):
        self.assertEqual("2@uuid:bp:mypath%2C%8A", 
                generate_file_id(generate_svn_revision_id("uuid", 2, "bp"), "mypath\x2c\x8a"))

    def test_generate_file_id_special_char(self):
        self.assertEqual("2@uuid:bp:mypath%2C%C2%8A",
                         generate_file_id(generate_svn_revision_id("uuid", 2, "bp"), u"mypath\x2c\x8a"))

    def test_generate_svn_file_id(self):
        self.assertEqual("2@uuid:bp:path", 
                generate_svn_file_id("uuid", 2, "bp", "path"))

    def test_generate_svn_file_id_nordic(self):
        self.assertEqual("2@uuid:bp:%C3%A6%C3%B8%C3%A5", 
                generate_svn_file_id("uuid", 2, "bp", u"\xe6\xf8\xe5"))

    def test_generate_svn_file_id_nordic_branch(self):
        self.assertEqual("2@uuid:%C3%A6:%C3%A6%C3%B8%C3%A5", 
                generate_svn_file_id("uuid", 2, u"\xe6", u"\xe6\xf8\xe5"))


class TestFileMapping(TestCase):
    def apply_mappings(self, mappings, find_children=None, renames={}):
        map = {}
        revids = mappings.keys()
        revids.sort()
        for r in revids:
            def new_file_id(x):
                if renames.has_key(r) and renames[r].has_key(x):
                    return renames[r][x]
                return generate_file_id(r, x)
            revmap = SimpleFileIdMap._apply_changes(new_file_id, mappings[r], find_children)
            map.update(dict([(x, (revmap[x],r)) for x in revmap]))
        return map

    def test_simple(self):
        map = self.apply_mappings({generate_svn_revision_id("uuid", 1, ""): {"foo": ('A', None, None)}})
        self.assertEqual({ 'foo': ("1@uuid::foo",
                                       generate_svn_revision_id("uuid", 1, ""))
                         }, map)

    def test_simple_add(self):
        map = self.apply_mappings({generate_svn_revision_id("uuid", 1, ""): {"": ('A', None, None), "foo": ('A', None, None)}})
        self.assertEqual({'': ('1@uuid::', generate_svn_revision_id("uuid", 1, "")),
            'foo': ("1@uuid::foo", 
                                       generate_svn_revision_id("uuid", 1, ""))
                         }, map)

    def test_copy(self):
        def find_children(path, revid):
            if path == "foo":
                yield "foo/blie"
                yield "foo/bla"
        map = self.apply_mappings(
                {generate_svn_revision_id("uuid", 1, ""): {
                                   "foo": ('A', None, None), 
                                   "foo/blie": ('A', None, None),
                                   "foo/bla": ('A', None, None)},
                generate_svn_revision_id("uuid", 2, ""): {
                                   "foob": ('A', 'foo', 1), 
                                   "foob/bla": ('M', None, None)}
                }, find_children)
        self.assertTrue(map.has_key("foob/bla"))
        self.assertTrue(map.has_key("foob/blie"))

    def test_touchparent(self):
        map = self.apply_mappings(
                {generate_svn_revision_id("uuid", 1, ""): {
                                   "foo": ('A', None, None), 
                                   "foo/bla": ('A', None, None)},
                 generate_svn_revision_id("uuid", 2, ""): {
                                   "foo/bla": ('M', None, None)}
                })
        self.assertEqual(generate_svn_revision_id("uuid", 1, ""), map["foo"][1])
        self.assertEqual(generate_svn_revision_id("uuid", 1, ""), map["foo/bla"][1])

    def test_usemap(self):
        map = self.apply_mappings(
                {generate_svn_revision_id("uuid", 1, ""): {
                                   "foo": ('A', None, None), 
                                   "foo/bla": ('A', None, None)},
                 generate_svn_revision_id("uuid", 2, ""): {
                                   "foo/bla": ('M', None, None)}
                 }, 
                renames={generate_svn_revision_id("uuid", 1, ""): {"foo": "myid"}})
        self.assertEqual("myid", map["foo"][0])

    def test_usemap_later(self):
        map = self.apply_mappings(
                {generate_svn_revision_id("uuid", 1, ""): {
                                   "foo": ('A', None, None), 
                                   "foo/bla": ('A', None, None)},
                 generate_svn_revision_id("uuid", 2, ""): {
                                   "foo/bla": ('M', None, None)}
                 }, 
                renames={generate_svn_revision_id("uuid", 2, ""): {"foo": "myid"}})
        self.assertEqual("1@uuid::foo", map["foo"][0])
        self.assertEqual(generate_svn_revision_id("uuid", 1, ""), map["foo"][1])

class GetMapTests(TestCaseWithSubversionRepository):
    def setUp(self):
        super(GetMapTests, self).setUp()
        self.repos_url = self.make_client("d", "dc")
        self.repos = Repository.open(self.repos_url)

    def test_empty(self):
        self.assertEqual({"": (generate_svn_file_id(self.repos.uuid, 0, "", ""), self.repos.generate_revision_id(0, ""))}, 
                         self.repos.get_fileid_map(0, ""))

    def test_empty_trunk(self):
        self.repos.set_branching_scheme(TrunkBranchingScheme())
        self.build_tree({"dc/trunk": None})
        self.client_add("dc/trunk")
        self.client_commit("dc", "Msg")
        self.assertEqual({"": (generate_svn_file_id(self.repos.uuid, 1, "trunk", ""), self.repos.generate_revision_id(1, "trunk"))}, self.repos.get_fileid_map(1, "trunk"))

    def test_change_parent(self):
        self.repos.set_branching_scheme(TrunkBranchingScheme())
        self.build_tree({"dc/trunk": None})
        self.client_add("dc/trunk")
        self.client_commit("dc", "Msg")
        self.build_tree({"dc/trunk/file": 'data'})
        self.client_add("dc/trunk/file")
        self.client_commit("dc", "Msg")
        self.assertEqual({"": (generate_svn_file_id(self.repos.uuid, 1, "trunk", ""), self.repos.generate_revision_id(2, "trunk")), "file": (generate_svn_file_id(self.repos.uuid, 2, "trunk", "file"), self.repos.generate_revision_id(2, "trunk"))}, self.repos.get_fileid_map(2, "trunk"))

    def test_change_updates(self):
        self.repos.set_branching_scheme(TrunkBranchingScheme())
        self.build_tree({"dc/trunk": None})
        self.client_add("dc/trunk")
        self.client_commit("dc", "Msg")
        self.build_tree({"dc/trunk/file": 'data'})
        self.client_add("dc/trunk/file")
        self.client_commit("dc", "Msg")
        self.build_tree({"dc/trunk/file": 'otherdata'})
        self.client_commit("dc", "Msg")
        self.assertEqual({"": (generate_svn_file_id(self.repos.uuid, 1, "trunk", ""), self.repos.generate_revision_id(3, "trunk")), "file": (generate_svn_file_id(self.repos.uuid, 2, "trunk", "file"), self.repos.generate_revision_id(3, "trunk"))}, self.repos.get_fileid_map(3, "trunk"))

    def test_sibling_unrelated(self):
        self.repos.set_branching_scheme(TrunkBranchingScheme())
        self.build_tree({"dc/trunk": None})
        self.client_add("dc/trunk")
        self.client_commit("dc", "Msg")
        self.build_tree({"dc/trunk/file": 'data', 'dc/trunk/bar': 'data2'})
        self.client_add("dc/trunk/file")
        self.client_add("dc/trunk/bar")
        self.client_commit("dc", "Msg")
        self.build_tree({"dc/trunk/file": 'otherdata'})
        self.client_commit("dc", "Msg")
        self.assertEqual({"": (generate_svn_file_id(self.repos.uuid, 1, "trunk", ""), self.repos.generate_revision_id(3, "trunk")), "bar": (generate_svn_file_id(self.repos.uuid, 2, "trunk", "bar"), self.repos.generate_revision_id(2, "trunk")), "file": (generate_svn_file_id(self.repos.uuid, 2, "trunk", "file"), self.repos.generate_revision_id(3, "trunk"))}, self.repos.get_fileid_map(3, "trunk"))

    def test_copy(self):
        self.repos.set_branching_scheme(TrunkBranchingScheme())
        self.build_tree({"dc/trunk": None})
        self.client_add("dc/trunk")
        self.client_commit("dc", "Msg")
        self.build_tree({"dc/trunk/file": 'data'})
        self.client_add("dc/trunk/file")
        self.client_commit("dc", "Msg")
        self.client_copy("dc/trunk/file", "dc/trunk/bar")
        self.client_commit("dc", "Msg")
        self.assertEqual({
            "": (generate_svn_file_id(self.repos.uuid, 1, "trunk", ""), self.repos.generate_revision_id(3, "trunk")), 
            "bar": (generate_svn_file_id(self.repos.uuid, 3, "trunk", "bar"), self.repos.generate_revision_id(3, "trunk")), "file": (generate_svn_file_id(self.repos.uuid, 2, "trunk", "file"), self.repos.generate_revision_id(2, "trunk"))}, self.repos.get_fileid_map(3, "trunk"))

    def test_copy_nested_modified(self):
        self.repos.set_branching_scheme(TrunkBranchingScheme())
        self.build_tree({"dc/trunk": None})
        self.client_add("dc/trunk")
        self.client_commit("dc", "Msg")
        self.build_tree({"dc/trunk/dir/file": 'data'})
        self.client_add("dc/trunk/dir")
        self.client_commit("dc", "Msg")
        self.client_copy("dc/trunk/dir", "dc/trunk/bar")
        self.build_tree({"dc/trunk/bar/file": "data2"})
        self.client_commit("dc", "Msg")
        self.assertEqual({
          "": (generate_svn_file_id(self.repos.uuid, 1, "trunk", ""), 
            self.repos.generate_revision_id(3, "trunk")), 
          "dir": (generate_svn_file_id(self.repos.uuid, 2, "trunk", "dir"), 
                self.repos.generate_revision_id(2, "trunk")),
          "dir/file": (generate_svn_file_id(self.repos.uuid, 2, "trunk", "dir/file"), 
              self.repos.generate_revision_id(2, "trunk")),
          "bar": (generate_svn_file_id(self.repos.uuid, 3, "trunk", "bar"), 
              self.repos.generate_revision_id(3, "trunk")),
          "bar/file": (generate_svn_file_id(self.repos.uuid, 3, "trunk", "bar/file"), 
              self.repos.generate_revision_id(3, "trunk"))},
            self.repos.get_fileid_map(3, "trunk"))
