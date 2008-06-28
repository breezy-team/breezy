# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""File id tests."""

from bzrlib.bzrdir import BzrDir
from bzrlib.repository import Repository
from bzrlib.trace import mutter
from bzrlib.tests import TestCase

from bzrlib.plugins.svn.fileids import simple_apply_changes
from bzrlib.plugins.svn.mapping3 import BzrSvnMappingv3FileProps, set_branching_scheme
from bzrlib.plugins.svn.mapping3.scheme import TrunkBranchingScheme, NoBranchingScheme
from bzrlib.plugins.svn.tests import TestCaseWithSubversionRepository

class MockRepo(object):
    def __init__(self, mapping, uuid="uuid"):
        self.uuid = uuid

    def lookup_revision_id(self, revid):
        ret = self.mapping.parse_revision_id(revid)
        return ret[1], ret[2], ret[3]


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
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.add_file("foo").modify("data")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.add_file("bar", "foo", 1)
        dc.delete("foo")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.open_file("bar").modify("data2")
        dc.close()

        repository = Repository.open("svn+"+repos_url)
        mapping = repository.get_mapping()

        inv1 = repository.get_inventory(
                repository.generate_revision_id(1, "", mapping))
        inv2 = repository.get_inventory(
                repository.generate_revision_id(2, "", mapping))
        mutter('inv1: %r' % inv1.entries())
        mutter('inv2: %r' % inv2.entries())
        self.assertNotEqual(None, inv1.path2id("foo"))
        self.assertIs(None, inv2.path2id("foo"))
        self.assertNotEqual(None, inv2.path2id("bar"))
        self.assertNotEqual(inv1.path2id("foo"), inv2.path2id("blie"))
        self.assertNotEqual(inv2.path2id("bar"), inv2.path2id("blie"))

    def test_simplecopy(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.add_file("foo").modify("data")
        dc.add_file("blie").modify("bloe")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.add_file("bar", "foo", 1).modify("data2")
        dc.close()

        bzrdir = BzrDir.open("svn+%s" % repos_url)
        repository = bzrdir.find_repository()

        mapping = repository.get_mapping()

        inv1 = repository.get_inventory(
                repository.generate_revision_id(1, "", mapping))
        inv2 = repository.get_inventory(
                repository.generate_revision_id(2, "", mapping))
        self.assertNotEqual(inv1.path2id("foo"), inv2.path2id("bar"))
        self.assertNotEqual(inv1.path2id("foo"), inv2.path2id("blie"))
        self.assertIs(None, inv1.path2id("bar"))
        self.assertNotEqual(None, inv1.path2id("blie"))

    def test_simpledelete(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.add_file("foo").modify("data")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.delete("foo")
        dc.close()

        bzrdir = BzrDir.open("svn+%s" % repos_url)
        repository = bzrdir.find_repository()
        mapping = repository.get_mapping()

        inv1 = repository.get_inventory(
                repository.generate_revision_id(1, "", mapping))
        inv2 = repository.get_inventory(
                repository.generate_revision_id(2, "", mapping))
        self.assertNotEqual(None, inv1.path2id("foo"))
        self.assertIs(None, inv2.path2id("foo"))

    def test_replace(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.add_file("foo").modify("data")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.delete("foo")
        dc.add_file("foo").modify("data")
        dc.close()

        bzrdir = BzrDir.open("svn+"+repos_url)
        repository = bzrdir.find_repository()

        mapping = repository.get_mapping()

        inv1 = repository.get_inventory(
                repository.generate_revision_id(1, "", mapping))
        inv2 = repository.get_inventory(
                repository.generate_revision_id(2, "", mapping))
        self.assertNotEqual(inv1.path2id("foo"), inv2.path2id("foo"))

    def test_copy_branch(self):
        scheme = TrunkBranchingScheme()
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        dir = trunk.add_dir("trunk/dir")
        dir.add_file("trunk/dir/file").modify("data")
        dc.add_dir("branches")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        branches = dc.open_dir("branches")
        branches.add_dir("branches/mybranch", "trunk", 1)
        dc.close()

        bzrdir = BzrDir.open("svn+"+repos_url + "/branches/mybranch")
        repository = bzrdir.find_repository()

        mapping = repository.get_mapping()

        inv1 = repository.get_inventory(
                repository.generate_revision_id(1, "trunk", mapping))
        inv2 = repository.get_inventory(
                repository.generate_revision_id(2, "branches/mybranch", mapping))
        self.assertEqual(inv1.path2id("dir"), inv2.path2id("dir"))
        self.assertEqual(inv1.path2id("dir/file"), inv2.path2id("dir/file"))

        fileid, revid = repository.get_fileid_map(2, 
                            "branches/mybranch", mapping)["dir/file"]
        self.assertEqual(fileid, inv1.path2id("dir/file"))
        self.assertEqual(repository.generate_revision_id(1, "trunk", mapping), revid)


class TestFileMapping(TestCase):
    def setUp(self):
        self.mapping = BzrSvnMappingv3FileProps(NoBranchingScheme())

    def apply_mappings(self, mappings, find_children=None, renames={}):
        map = {}
        brns = mappings.keys()
        brns.sort()
        for r in brns:
            (revnum, branchpath) = r
            def new_file_id(x):
                if renames.has_key(r) and renames[r].has_key(x):
                    return renames[r][x]
                return self.mapping.generate_file_id("uuid", revnum, branchpath, x)
            revmap = simple_apply_changes(new_file_id, mappings[r], find_children)
            map.update(dict([(x, (revmap[x],r)) for x in revmap]))
        return map

    def test_simple(self):
        map = self.apply_mappings({(1, ""): {"foo": ('A', None, None)}})
        self.assertEqual({ 'foo': ("1@uuid::foo",
                                       (1, ""))
                         }, map)

    def test_simple_add(self):
        map = self.apply_mappings({(1, ""): {"": ('A', None, None), "foo": ('A', None, None)}})
        self.assertEqual({
            '': ('1@uuid::', (1, "")),
            'foo': ("1@uuid::foo", (1, "")) 
            }, map)

    def test_copy(self):
        def find_children(path, revid):
            if path == "foo":
                yield "foo/blie"
                yield "foo/bla"
        map = self.apply_mappings({
                (1, ""): {
                                   "foo": ('A', None, None), 
                                   "foo/blie": ('A', None, None),
                                   "foo/bla": ('A', None, None)},
                (2, ""): {
                                   "foob": ('A', 'foo', 1), 
                                   "foob/bla": ('M', None, None)}
                }, find_children)
        self.assertTrue(map.has_key("foob/bla"))
        self.assertTrue(map.has_key("foob/blie"))

    def test_touchparent(self):
        map = self.apply_mappings(
                {(1, ""): {
                                   "foo": ('A', None, None), 
                                   "foo/bla": ('A', None, None)},
                 (2, ""): {
                                   "foo/bla": ('M', None, None)}
                })
        self.assertEqual((1, ""), 
                         map["foo"][1])
        self.assertEqual((1, ""), 
                         map["foo/bla"][1])

    def test_usemap(self):
        map = self.apply_mappings(
                {(1, ""): {
                                   "foo": ('A', None, None), 
                                   "foo/bla": ('A', None, None)},
                 (2, ""): {
                                   "foo/bla": ('M', None, None)}
                 }, 
                renames={(1, ""): {"foo": "myid"}})
        self.assertEqual("myid", map["foo"][0])

    def test_usemap_later(self):
        map = self.apply_mappings(
                {(1, ""): {
                                   "foo": ('A', None, None), 
                                   "foo/bla": ('A', None, None)},
                 (2, ""): {
                                   "foo/bla": ('M', None, None)}
                 }, 
                renames={(2, ""): {"foo": "myid"}})
        self.assertEqual("1@uuid::foo", map["foo"][0])
        self.assertEqual((1, ""), map["foo"][1])


class GetMapTests(TestCaseWithSubversionRepository):
    def setUp(self):
        super(GetMapTests, self).setUp()
        self.repos_url = self.make_repository("d")
        self.repos = Repository.open(self.repos_url)

    def test_empty(self):
        set_branching_scheme(self.repos, NoBranchingScheme())
        self.mapping = self.repos.get_mapping()
        self.assertEqual({"": (self.mapping.generate_file_id(self.repos.uuid, 0, "", u""), self.repos.generate_revision_id(0, "", self.mapping))}, 
                         self.repos.get_fileid_map(0, "", self.mapping))

    def test_empty_trunk(self):
        set_branching_scheme(self.repos, TrunkBranchingScheme())
        self.mapping = self.repos.get_mapping()
        dc = self.get_commit_editor(self.repos_url)
        dc.add_dir("trunk")
        dc.close()

        self.assertEqual({"": (self.mapping.generate_file_id(self.repos.uuid, 1, "trunk", u""), self.repos.generate_revision_id(1, "trunk", self.mapping))}, 
                self.repos.get_fileid_map(1, "trunk", self.mapping))

    def test_change_parent(self):
        set_branching_scheme(self.repos, TrunkBranchingScheme())
        self.mapping = self.repos.get_mapping()
        
        dc = self.get_commit_editor(self.repos_url)
        dc.add_dir("trunk")
        dc.close()

        dc = self.get_commit_editor(self.repos_url)
        dc.open_dir("trunk").add_file("trunk/file").modify("data")
        dc.close()

        self.assertEqual({"": (self.mapping.generate_file_id(self.repos.uuid, 1, "trunk", u""), self.repos.generate_revision_id(2, "trunk", self.mapping)), "file": (self.mapping.generate_file_id(self.repos.uuid, 2, "trunk", u"file"), self.repos.generate_revision_id(2, "trunk", self.mapping))}, self.repos.get_fileid_map(2, "trunk", self.mapping))

    def test_change_updates(self):
        set_branching_scheme(self.repos, TrunkBranchingScheme())
        self.mapping = self.repos.get_mapping()

        dc = self.get_commit_editor(self.repos_url)
        dc.add_dir("trunk")
        dc.close()

        dc = self.get_commit_editor(self.repos_url)
        dc.open_dir("trunk").add_file("trunk/file").modify("data")
        dc.close()

        dc = self.get_commit_editor(self.repos_url)
        dc.open_dir("trunk").open_file("trunk/file").modify("otherdata")
        dc.close()

        self.assertEqual({"": (self.mapping.generate_file_id(self.repos.uuid, 1, "trunk", u""), self.repos.generate_revision_id(3, "trunk", self.mapping)), "file": (self.mapping.generate_file_id(self.repos.uuid, 2, "trunk", u"file"), self.repos.generate_revision_id(3, "trunk", self.mapping))}, self.repos.get_fileid_map(3, "trunk", self.mapping))

    def test_sibling_unrelated(self):
        set_branching_scheme(self.repos, TrunkBranchingScheme())
        self.mapping = self.repos.get_mapping()

        dc = self.get_commit_editor(self.repos_url)
        dc.add_dir("trunk")
        dc.close()

        dc = self.get_commit_editor(self.repos_url)
        trunk = dc.open_dir("trunk")
        trunk.add_file("trunk/file").modify("data")
        trunk.add_file("trunk/bar").modify("data2")
        dc.close()

        dc = self.get_commit_editor(self.repos_url)
        trunk = dc.open_dir("trunk")
        trunk.open_file("trunk/file").modify('otherdata')
        dc.close()

        self.assertEqual({"": (self.mapping.generate_file_id(self.repos.uuid, 1, "trunk", u""), self.repos.generate_revision_id(3, "trunk", self.mapping)), "bar": (self.mapping.generate_file_id(self.repos.uuid, 2, "trunk", u"bar"), self.repos.generate_revision_id(2, "trunk", self.mapping)), "file": (self.mapping.generate_file_id(self.repos.uuid, 2, "trunk", u"file"), self.repos.generate_revision_id(3, "trunk", self.mapping))}, self.repos.get_fileid_map(3, "trunk", self.mapping))

    def test_copy(self):
        set_branching_scheme(self.repos, TrunkBranchingScheme())
        self.mapping = self.repos.get_mapping()

        dc = self.get_commit_editor(self.repos_url)
        dc.add_dir("trunk")
        dc.close()

        dc = self.get_commit_editor(self.repos_url)
        trunk = dc.open_dir("trunk")
        trunk.add_file("trunk/file").modify("data")
        dc.close()

        dc = self.get_commit_editor(self.repos_url)
        trunk = dc.open_dir("trunk")
        trunk.add_file("trunk/bar", "trunk/file", 2)
        dc.close()

        self.assertEqual({
            "": (self.mapping.generate_file_id(self.repos.uuid, 1, "trunk", u""), self.repos.generate_revision_id(3, "trunk", self.mapping)), 
            "bar": (self.mapping.generate_file_id(self.repos.uuid, 3, "trunk", u"bar"), self.repos.generate_revision_id(3, "trunk", self.mapping)), "file": (self.mapping.generate_file_id(self.repos.uuid, 2, "trunk", u"file"), self.repos.generate_revision_id(2, "trunk", self.mapping))}, self.repos.get_fileid_map(3, "trunk", self.mapping))

    def test_copy_nested_modified(self):
        set_branching_scheme(self.repos, TrunkBranchingScheme())
        self.mapping = self.repos.get_mapping()

        dc = self.get_commit_editor(self.repos_url)
        dc.add_dir("trunk")
        dc.close()

        dc = self.get_commit_editor(self.repos_url)
        trunk = dc.open_dir("trunk")
        dir = trunk.add_dir("trunk/dir")
        dir.add_file("trunk/dir/file").modify("data")
        dc.close()

        dc = self.get_commit_editor(self.repos_url)
        trunk = dc.open_dir("trunk")
        dir = trunk.add_dir("trunk/bar", "trunk/dir")
        dir.open_file("trunk/bar/file").modify("data2")
        dc.close()

        self.assertEqual({
          "": (self.mapping.generate_file_id(self.repos.uuid, 1, "trunk", u""), 
            self.repos.generate_revision_id(3, "trunk", self.mapping)), 
          "dir": (self.mapping.generate_file_id(self.repos.uuid, 2, "trunk", u"dir"), 
                self.repos.generate_revision_id(2, "trunk", self.mapping)),
          "dir/file": (self.mapping.generate_file_id(self.repos.uuid, 2, "trunk", u"dir/file"), 
              self.repos.generate_revision_id(2, "trunk", self.mapping)),
          "bar": (self.mapping.generate_file_id(self.repos.uuid, 3, "trunk", u"bar"), 
              self.repos.generate_revision_id(3, "trunk", self.mapping)),
          "bar/file": (self.mapping.generate_file_id(self.repos.uuid, 3, "trunk", u"bar/file"), 
              self.repos.generate_revision_id(3, "trunk", self.mapping))},
            self.repos.get_fileid_map(3, "trunk", self.mapping))
