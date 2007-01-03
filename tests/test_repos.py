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

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.errors import NoSuchRevision, BzrError, UninitializableFormat
from bzrlib.inventory import Inventory
import bzrlib.osutils as osutils
from bzrlib.repository import Repository
from bzrlib.revision import NULL_REVISION
from bzrlib.tests import TestCase
from bzrlib.trace import mutter
from bzrlib.transport.local import LocalTransport

import os

import svn.fs

from convert import load_dumpfile
import errors
import format
from scheme import TrunkBranchingScheme, NoBranchingScheme
from transport import SvnRaTransport
from tests import TestCaseWithSubversionRepository
import repository
from repository import (parse_svn_revision_id, generate_svn_revision_id, 
                        svk_feature_to_revision_id, revision_id_to_svk_feature,
                        MAPPING_VERSION, escape_svn_path, unescape_svn_path,
                        SvnRepositoryFormat)


class TestSubversionRepositoryWorks(TestCaseWithSubversionRepository):
    def test_format(self):
        """ Test repository format is correct """
        bzrdir = self.make_local_bzrdir('a', 'ac')
        self.assertEqual(bzrdir._format.get_format_string(), \
                "Subversion Local Checkout")
        
        self.assertEqual(bzrdir._format.get_format_description(), \
                "Subversion Local Checkout")

    def test_get_branch_log(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        repos = Repository.open(repos_url)

        self.assertEqual(1, len(list(repos.follow_branch_history("", 1))))

    def test_make_working_trees(self):
        repos_url = self.make_client("a", "dc")
        repos = Repository.open(repos_url)
        self.assertFalse(repos.make_working_trees())

    def test_set_make_working_trees(self):
        repos_url = self.make_client("a", "dc")
        repos = Repository.open(repos_url)
        repos.set_make_working_trees(True)
        self.assertFalse(repos.make_working_trees())

    def test_add_revision(self):
        repos_url = self.make_client("a", "dc")
        repos = Repository.open(repos_url)
        self.assertRaises(NotImplementedError, repos.add_revision, "revid", 
                None)

    def test_has_signature_for_revision_id(self):
        repos_url = self.make_client("a", "dc")
        repos = Repository.open(repos_url)
        self.assertFalse(repos.has_signature_for_revision_id("foo"))

    def test_repr(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        repos = Repository.open(repos_url)

        self.assertEqual("SvnRepository('file://%s/')" % os.path.join(self.test_dir, "a"), repos.__repr__())

    def test_get_branch_invalid_revision(self):
        repos_url = self.make_client("a", "dc")
        repos = Repository.open(repos_url)
        self.assertRaises(NoSuchRevision, list, 
                          repos.follow_branch_history("/", 20))

    def test_history_all(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/file': "data", "dc/foo/file":"data"})
        self.client_add("dc/trunk")
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        repos = Repository.open(repos_url)

        self.assertEqual(1, len(list(repos.follow_history(1))))

    def test_all_revs_empty(self):
        repos_url = self.make_client("a", "dc")
        repos = Repository.open(repos_url)
        repos.set_branching_scheme(TrunkBranchingScheme())
        self.assertEqual([], list(repos.all_revision_ids()))

    def test_all_revs(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/file': "data", "dc/foo/file":"data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "add trunk")
        self.build_tree({'dc/branches/somebranch/somefile': 'data'})
        self.client_add("dc/branches")
        self.client_commit("dc", "add a branch")
        self.client_delete("dc/branches/somebranch")
        self.client_commit("dc", "remove branch")

        repos = Repository.open(repos_url)
        repos.set_branching_scheme(TrunkBranchingScheme())
        self.assertEqual([
            "svn-v%d:2@%s-branches%%2fsomebranch" % (MAPPING_VERSION, repos.uuid),
            "svn-v%d:1@%s-trunk" % (MAPPING_VERSION, repos.uuid)
            ], list(repos.all_revision_ids()))

    def test_follow_history_follow(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/afile': "data", "dc/branches": None})
        self.client_add("dc/trunk")
        self.client_add("dc/branches")
        self.client_commit("dc", "My Message")

        self.client_copy("dc/trunk", "dc/branches/abranch")
        self.client_commit("dc", "Create branch")

        repos = Repository.open(repos_url)
        repos.set_branching_scheme(TrunkBranchingScheme())

        items = list(repos.follow_history(2))
        self.assertEqual([('branches/abranch', 2), 
                          ('trunk', 1)], items)

    def test_branch_log_specific(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({
            'dc/branches': None,
            'dc/branches/brancha': None,
            'dc/branches/branchab': None,
            'dc/branches/brancha/data': "data", 
            "dc/branches/branchab/data":"data"})
        self.client_add("dc/branches")
        self.client_commit("dc", "My Message")

        repos = Repository.open(repos_url)
        repos.set_branching_scheme(TrunkBranchingScheme())

        self.assertEqual(1, len(list(repos.follow_branch_history("branches/brancha",
            1))))

    def test_branch_log_specific_ignore(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/branches': None})
        self.client_add("dc/branches")
        self.build_tree({
            'dc/branches/brancha': None,
            'dc/branches/branchab': None,
            'dc/branches/brancha/data': "data", 
            "dc/branches/branchab/data":"data"})
        self.client_add("dc/branches/brancha")
        self.client_commit("dc", "My Message")

        self.client_add("dc/branches/branchab")
        self.client_commit("dc", "My Message2")

        repos = Repository.open(repos_url)
        repos.set_branching_scheme(TrunkBranchingScheme())

        self.assertEqual(1, len(list(repos.follow_branch_history("branches/brancha",
            2))))

    def test_find_branches_moved(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({
            'dc/tmp/branches/brancha': None,
            'dc/tmp/branches/branchab': None,
            'dc/tmp/branches/brancha/data': "data", 
            "dc/tmp/branches/branchab/data":"data"})
        self.client_add("dc/tmp")
        self.client_commit("dc", "My Message")
        self.client_copy("dc/tmp/branches", "dc/tags")
        self.client_commit("dc", "My Message 2")

        repos = Repository.open(repos_url)
        repos.set_branching_scheme(TrunkBranchingScheme())

        self.assertEqual([("tags/branchab", 2, True), 
                          ("tags/brancha", 2, True)], 
                list(repos.find_branches(2)))

    def test_find_branches_moved_nobranch(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({
            'dc/tmp/nested/foobar': None,
            'dc/tmp/nested/branches/brancha': None,
            'dc/tmp/nested/branches/branchab': None,
            'dc/tmp/nested/branches/brancha/data': "data", 
            "dc/tmp/nested/branches/branchab/data":"data"})
        self.client_add("dc/tmp")
        self.client_commit("dc", "My Message")
        self.client_copy("dc/tmp/nested", "dc/t2")
        self.client_commit("dc", "My Message 2")

        repos = Repository.open(repos_url)
        repos.set_branching_scheme(TrunkBranchingScheme(1))

        self.assertEqual([("t2/branches/brancha", 2, True), 
                          ("t2/branches/branchab", 2, True)], 
                list(repos.find_branches(2)))

    def test_find_branches_no(self):
        repos_url = self.make_client("a", "dc")

        repos = Repository.open(repos_url)
        repos.set_branching_scheme(NoBranchingScheme())

        self.assertEqual([("", 0, True)], list(repos.find_branches(0)))

    def test_find_branches_no_later(self):
        repos_url = self.make_client("a", "dc")

        repos = Repository.open(repos_url)
        repos.set_branching_scheme(NoBranchingScheme())

        self.assertEqual([("", 0, True)], list(repos.find_branches(0)))

    def test_find_branches_trunk_empty(self):
        repos_url = self.make_client("a", "dc")

        repos = Repository.open(repos_url)
        repos.set_branching_scheme(TrunkBranchingScheme())

        self.assertEqual([], list(repos.find_branches(0)))

    def test_find_branches_trunk_one(self):
        repos_url = self.make_client("a", "dc")

        repos = Repository.open(repos_url)
        repos.set_branching_scheme(TrunkBranchingScheme())

        self.build_tree({'dc/trunk/foo': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")

        self.assertEqual([("trunk", 1, True)], list(repos.find_branches(1)))

    def test_find_branches_removed(self):
        repos_url = self.make_client("a", "dc")

        repos = Repository.open(repos_url)
        repos.set_branching_scheme(TrunkBranchingScheme())

        self.build_tree({'dc/trunk/foo': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")

        self.client_delete("dc/trunk")
        self.client_commit("dc", "remove")

        self.assertEqual([("trunk", 1, True)], list(repos.find_branches(1)))
        self.assertEqual([("trunk", 2, False)], list(repos.find_branches(2)))

    def test_url(self):
        """ Test repository URL is kept """
        bzrdir = self.make_local_bzrdir('b', 'bc')
        self.assertTrue(isinstance(bzrdir, BzrDir))

    def test_uuid(self):
        """ Test UUID is retrieved correctly """
        bzrdir = self.make_local_bzrdir('c', 'cc')
        self.assertTrue(isinstance(bzrdir, BzrDir))
        repository = bzrdir.find_repository()
        fs = self.open_fs('c')
        self.assertEqual(svn.fs.get_uuid(fs), repository.uuid)

    def test_get_inventory_weave(self):
        bzrdir = self.make_client_and_bzrdir('d', 'dc')
        repository = bzrdir.find_repository()
        self.assertRaises(NotImplementedError, repository.get_inventory_weave)

    def test_has_revision(self):
        bzrdir = self.make_client_and_bzrdir('d', 'dc')
        repository = bzrdir.find_repository()
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.assertTrue(repository.has_revision(
            "svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid)))
        self.assertFalse(repository.has_revision("some-other-revision"))

    def test_has_revision_none(self):
        bzrdir = self.make_client_and_bzrdir('d', 'dc')
        repository = bzrdir.find_repository()
        self.assertTrue(repository.has_revision(None))

    def test_revision_parents(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo': "data2"})
        self.client_commit("dc", "Second Message")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual([],
                repository.revision_parents(
                    "svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid)))
        self.assertEqual([
            "svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid)], 
            repository.revision_parents(
                "svn-v%d:2@%s-" % (MAPPING_VERSION, repository.uuid)))

    def test_revision_fileidmap(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_set_prop("dc", "bzr:file-ids", "foo\tsomeid\n")
        self.client_commit("dc", "My Message")
        repository = Repository.open("svn+%s" % repos_url)
        tree = repository.revision_tree(Branch.open(repos_url).last_revision())
        self.assertEqual("someid", tree.inventory.path2id("foo"))
        self.assertFalse("svn-v2:1@%s--foo" % repository.uuid in tree.inventory)

    def test_revision_ghost_parents(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo': "data2"})
        self.client_set_prop("dc", "bzr:merge", "ghostparent\n")
        self.client_commit("dc", "Second Message")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual([],
                repository.revision_parents(
                    "svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid)))
        self.assertEqual(["svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid), 
            "ghostparent"], 
                repository.revision_parents(
                    "svn-v%d:2@%s-" % (MAPPING_VERSION, repository.uuid)))
 
    
    def test_get_revision(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.assertRaises(NoSuchRevision, repository.get_revision, "nonexisting")
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo': "data2"})
        (num, date, author) = self.client_commit("dc", "Second Message")
        repository = Repository.open("svn+%s" % repos_url)
        rev = repository.get_revision(
            "svn-v%d:2@%s-" % (MAPPING_VERSION, repository.uuid))
        self.assertEqual(["svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid)],
                rev.parent_ids)
        self.assertEqual(rev.revision_id,
            "svn-v%d:2@%s-" % (MAPPING_VERSION, repository.uuid))
        self.assertEqual(author, rev.committer)
        self.assertIsInstance(rev.properties, dict)

    def test_get_ancestry(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.assertRaises(NoSuchRevision, repository.get_revision, "nonexisting")
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo': "data2"})
        self.client_commit("dc", "Second Message")
        self.build_tree({'dc/foo': "data3"})
        self.client_commit("dc", "Third Message")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual([None, 
            "svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid), 
            "svn-v%d:2@%s-" % (MAPPING_VERSION, repository.uuid)],
                repository.get_ancestry(
                    "svn-v%d:3@%s-" % (MAPPING_VERSION, repository.uuid)))
        self.assertEqual([None, 
            "svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid)], 
                repository.get_ancestry(
                    "svn-v%d:2@%s-" % (MAPPING_VERSION, repository.uuid)))
        self.assertEqual([None],
                repository.get_ancestry(
                    "svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid)))
        self.assertEqual([None], repository.get_ancestry(None))

    def test_get_revision_graph_empty(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual({}, repository.get_revision_graph(NULL_REVISION))

    def test_get_revision_graph_invalid(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.assertRaises(NoSuchRevision, repository.get_revision_graph, 
                          "nonexisting")

    def test_get_revision_graph(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo': "data2"})
        self.client_commit("dc", "Second Message")
        self.build_tree({'dc/foo': "data3"})
        self.client_commit("dc", "Third Message")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual({
           "svn-v%d:3@%s-" % (MAPPING_VERSION, repository.uuid): [
               "svn-v%d:2@%s-" % (MAPPING_VERSION, repository.uuid)],
           "svn-v%d:2@%s-" % (MAPPING_VERSION, repository.uuid): [
               "svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid)],
           "svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid): []},
                repository.get_revision_graph(
                    "svn-v%d:3@%s-" % (MAPPING_VERSION, repository.uuid)))
        self.assertEqual({
           "svn-v%d:2@%s-" % (MAPPING_VERSION, repository.uuid): [
               "svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid)],
           "svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid): []},
                repository.get_revision_graph(
                    "svn-v%d:2@%s-" % (MAPPING_VERSION, repository.uuid)))
        self.assertEqual({
            "svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid): []},
                repository.get_revision_graph(
                    "svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid)))

    def test_get_ancestry2(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo': "data2"})
        self.client_commit("dc", "Second Message")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual([None],
                repository.get_ancestry(
                    "svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid)))
        self.assertEqual([None, 
            "svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid)], 
                repository.get_ancestry(
                    "svn-v%d:2@%s-" % (MAPPING_VERSION, repository.uuid)))

    def test_get_ancestry_merged(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.client_set_prop("dc", "bzr:merge", "a-parent\n")
        self.build_tree({'dc/foo': "data2"})
        self.client_commit("dc", "Second Message")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual([None],
                repository.get_ancestry(
                    "svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid)))
        self.assertEqual([None, 
            "svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid), 
                          "a-parent"], 
                repository.get_ancestry(
                    "svn-v%d:2@%s-" % (MAPPING_VERSION, repository.uuid)))


    def test_get_inventory(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.assertRaises(NoSuchRevision, repository.get_inventory, "nonexisting")
        self.build_tree({'dc/foo': "data", 'dc/blah': "other data"})
        self.client_add("dc/foo")
        self.client_add("dc/blah")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo': "data2", "dc/bar/foo": "data3"})
        self.client_add("dc/bar")
        self.client_commit("dc", "Second Message")
        self.build_tree({'dc/foo': "data3"})
        self.client_commit("dc", "Third Message")
        repository = Repository.open("svn+%s" % repos_url)
        inv = repository.get_inventory(
                "svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid))
        self.assertIsInstance(inv, Inventory)
        self.assertIsInstance(inv.path2id("foo"), basestring)
        inv = repository.get_inventory(
                "svn-v%d:2@%s-" % (MAPPING_VERSION, repository.uuid))
        self.assertEqual("svn-v%d:2@%s-" % (MAPPING_VERSION, repository.uuid), 
                         inv[inv.path2id("foo")].revision)
        self.assertEqual("svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid), 
                         inv[inv.path2id("blah")].revision)
        self.assertIsInstance(inv, Inventory)
        self.assertIsInstance(inv.path2id("foo"), basestring)
        self.assertIsInstance(inv.path2id("bar"), basestring)
        self.assertIsInstance(inv.path2id("bar/foo"), basestring)

    def test_generate_revision_id(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual(
            "svn-v%d:1@%s-bla%%2fbloe" % (MAPPING_VERSION, repository.uuid), 
            repository.generate_revision_id(1, "bla/bloe"))

    def test_generate_revision_id_none(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual(NULL_REVISION, 
                repository.generate_revision_id(0, "bla/bloe"))

    def test_parse_revision_id(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.assertRaises(NoSuchRevision, repository.parse_revision_id, 
            "nonexisting")
        self.assertEqual(("bloe", 0), 
            repository.parse_revision_id(
                "svn-v%d:0@%s-bloe" % (MAPPING_VERSION, repository.uuid)))

    def test_parse_revision_id_invalid_uuid(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.assertRaises(NoSuchRevision, 
            repository.parse_revision_id, 
                "svn-v%d:0@invaliduuid-bloe" % MAPPING_VERSION)
        
    def test_check(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        repository = Repository.open("svn+%s" % repos_url)
        repository.check([
            "svn-v%d:0@%s-" % (MAPPING_VERSION, repository.uuid), 
            "svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid)])

    def test_copy_contents_into(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo/blo': "data2", "dc/bar/foo": "data3", 'dc/foo/bla': "data"})
        self.client_add("dc/foo/blo")
        self.client_add("dc/bar")
        self.client_commit("dc", "Second Message")
        repository = Repository.open("svn+%s" % repos_url)

        to_repos = BzrDir.create_repository("e")

        repository.copy_content_into(to_repos, 
                "svn-v%d:2@%s-" % (MAPPING_VERSION, repository.uuid))

        self.assertTrue(repository.has_revision(
            "svn-v%d:2@%s-" % (MAPPING_VERSION, repository.uuid)))
        self.assertTrue(repository.has_revision(
            "svn-v%d:1@%s-" % (MAPPING_VERSION, repository.uuid)))
        self.assertTrue(repository.has_revision(
            "svn-v%d:0@%s-" % (MAPPING_VERSION, repository.uuid)))
        self.assertFalse(repository.has_revision(
            "svn-v%d:4@%s-" % (MAPPING_VERSION, repository.uuid)))

    def test_is_shared(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertTrue(repository.is_shared())

    def test_revision_fileid_renames(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/test': "data"})
        self.client_add("dc/test")
        self.client_set_prop("dc", "bzr:file-ids", "test\tbla\n")
        self.client_commit("dc", "Msg")

        repos = Repository.open(repos_url)
        renames = repos.revision_fileid_renames("svn-v%d:1@%s-" % (MAPPING_VERSION, repos.uuid))
        self.assertEqual({"test": "bla"}, renames)

    def test_fetch_fileid_renames(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/test': "data"})
        self.client_add("dc/test")
        self.client_set_prop("dc", "bzr:file-ids", "test\tbla\n")
        self.client_commit("dc", "Msg")

        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertEqual("bla", newrepos.get_inventory(
            "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid)).path2id("test"))

    def test_fetch_trunk1(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/proj1/trunk/file': "data"})
        self.client_add("dc/proj1")
        self.client_commit("dc", "My Message")
        oldrepos = Repository.open(repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme(1))
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

    def test_fetch_special_char(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({u'dc/trunk/f\x2cle': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")
        oldrepos = Repository.open(repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme(1))
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

    def test_fetch_delete(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.client_delete("dc/foo/bla")
        self.client_commit("dc", "Second Message")
        newrepos = Repository.open("f")
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(oldrepos.has_revision("svn-v%d:2@%s-" % (MAPPING_VERSION, oldrepos.uuid)))

    def test_fetch_local(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo/blo': "data2", "dc/bar/foo": "data3", 'dc/foo/bla': "data"})
        self.client_add("dc/foo/blo")
        self.client_add("dc/bar")
        self.client_commit("dc", "Second Message")
        oldrepos = Repository.open(repos_url)
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid)))
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:2@%s-" % (MAPPING_VERSION, oldrepos.uuid)))
        tree = newrepos.revision_tree(
                "svn-v%d:2@%s-" % (MAPPING_VERSION, oldrepos.uuid))
        self.assertTrue(tree.has_filename("foo/bla"))
        self.assertTrue(tree.has_filename("foo"))
        self.assertEqual("data", tree.get_file_by_path("foo/bla").read())

    def test_control_code_msg(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/trunk': None})
        self.client_add("dc/trunk")
        self.client_commit("dc", "\x24")

        self.build_tree({'dc/trunk/hosts': 'hej2'})
        self.client_add("dc/trunk/hosts")
        self.client_commit("dc", "bla\xfcbla") #2

        self.build_tree({'dc/trunk/hosts': 'hej3'})
        self.client_commit("dc", "a\x0cb") #3

        self.build_tree({'dc/branches/foobranch/file': 'foohosts'})
        self.client_add("dc/branches")
        self.client_commit("dc", "foohosts") #4

        oldrepos = Repository.open("svn+"+repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme())
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

        self.assertTrue(newrepos.has_revision(
            "svn-v%d:1@%s-trunk" % (MAPPING_VERSION, oldrepos.uuid)))
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:2@%s-trunk" % (MAPPING_VERSION, oldrepos.uuid)))
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:3@%s-trunk" % (MAPPING_VERSION, oldrepos.uuid)))
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:4@%s-branches%%2ffoobranch" % (MAPPING_VERSION, oldrepos.uuid)))
        self.assertFalse(newrepos.has_revision(
            "svn-v%d:4@%s-trunk" % (MAPPING_VERSION, oldrepos.uuid)))
        self.assertFalse(newrepos.has_revision(
            "svn-v%d:2@%s-" % (MAPPING_VERSION, oldrepos.uuid)))

        rev = newrepos.get_revision(
                "svn-v%d:1@%s-trunk" % (MAPPING_VERSION, oldrepos.uuid))
        self.assertEqual("$", rev.message)

        rev = newrepos.get_revision(
            "svn-v%d:2@%s-trunk" % (MAPPING_VERSION, oldrepos.uuid))
        self.assertEqual(u'bla\xfcbla', rev.message)

        rev = newrepos.get_revision(
            "svn-v%d:3@%s-trunk" % (MAPPING_VERSION, oldrepos.uuid))
        self.assertEqual(u"a\\x0cb", rev.message)

    def test_fetch_replace(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/bla': "data"})
        self.client_add("dc/bla")
        self.client_commit("dc", "My Message")
        self.client_delete("dc/bla")
        self.build_tree({'dc/bla': "data2"})
        self.client_add("dc/bla")
        self.client_commit("dc", "Second Message")
        oldrepos = Repository.open("svn+"+repos_url)
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid)))
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:2@%s-" % (MAPPING_VERSION, oldrepos.uuid)))
        inv1 = newrepos.get_inventory(
                "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid))
        inv2 = newrepos.get_inventory(
                "svn-v%d:2@%s-" % (MAPPING_VERSION, oldrepos.uuid))
        self.assertNotEqual(inv1.path2id("bla"), inv2.path2id("bla"))

    def test_fetch_copy_subdir(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/trunk/mydir/a': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/branches/tmp': None})
        self.client_add("dc/branches")
        self.client_commit("dc", "Second Message")
        self.client_copy("dc/trunk/mydir", "dc/branches/tmp/abranch")
        self.client_commit("dc", "Third Message")
        oldrepos = Repository.open("svn+"+repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme())
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

    def test_fetch_replace_with_subreplace(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        open(filename, 'w').write("""SVN-fs-dump-format-version: 2

UUID: 606c7b1f-987c-4826-b37d-eb456ceb87e1

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-12-26T00:04:55.850520Z
PROPS-END

Revision-number: 1
Prop-content-length: 103
Content-length: 103

K 7
svn:log
V 3
add
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:15.504335Z
PROPS-END

Node-path: x
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END

Node-path: x/t
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END

Node-path: u
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END

Revision-number: 2
Prop-content-length: 105
Content-length: 105

K 7
svn:log
V 5
readd
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:43.584249Z
PROPS-END

Node-path: x
Node-action: delete

Node-path: x
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 3
Prop-content-length: 108
Content-length: 108

K 7
svn:log
V 8
Replace

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:30:06.383777Z
PROPS-END

Node-path: x
Node-action: delete

Node-path: y
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: x

Node-path: y/t
Node-action: delete

Node-path: y/t
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: u


""")
        os.mkdir("old")

        load_dumpfile("dumpfile", "old")
        oldrepos = Repository.open("old")
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid)))
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:3@%s-" % (MAPPING_VERSION, oldrepos.uuid)))
        inv1 = newrepos.get_inventory(
                "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid))
        inv2 = newrepos.get_inventory(
                "svn-v%d:3@%s-" % (MAPPING_VERSION, oldrepos.uuid))

    def test_fetch_replace_self(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        open(filename, 'w').write("""SVN-fs-dump-format-version: 2

UUID: 6dcc86fc-ac21-4df7-a3a3-87616123c853

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-12-25T04:27:54.633666Z
PROPS-END

Revision-number: 1
Prop-content-length: 108
Content-length: 108

K 7
svn:log
V 8
Add dir

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:28:17.503039Z
PROPS-END

Node-path: bla
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 2
Prop-content-length: 117
Content-length: 117

K 7
svn:log
V 16
Add another dir

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:28:30.160663Z
PROPS-END

Node-path: blie
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 3
Prop-content-length: 105
Content-length: 105

K 7
svn:log
V 5
Copy

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:28:44.996894Z
PROPS-END

Node-path: bloe
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: bla


Revision-number: 4
Prop-content-length: 108
Content-length: 108

K 7
svn:log
V 8
Replace

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:30:06.383777Z
PROPS-END

Node-path: bla
Node-action: delete


Node-path: bla
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 2
Node-copyfrom-path: bla


""")
        os.mkdir("old")

        load_dumpfile("dumpfile", "old")
        oldrepos = Repository.open("old")
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid)))
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:3@%s-" % (MAPPING_VERSION, oldrepos.uuid)))
        inv1 = newrepos.get_inventory(
                "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid))
        inv2 = newrepos.get_inventory(
                "svn-v%d:3@%s-" % (MAPPING_VERSION, oldrepos.uuid))
        self.assertEqual(inv1.path2id("bla"), inv2.path2id("bla"))

    def test_fetch_replace_backup(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        open(filename, 'w').write("""SVN-fs-dump-format-version: 2

UUID: 6dcc86fc-ac21-4df7-a3a3-87616123c853

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-12-25T04:27:54.633666Z
PROPS-END

Revision-number: 1
Prop-content-length: 108
Content-length: 108

K 7
svn:log
V 8
Add dir

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:28:17.503039Z
PROPS-END

Node-path: bla
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 2
Prop-content-length: 117
Content-length: 117

K 7
svn:log
V 16
Add another dir

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:28:30.160663Z
PROPS-END

Node-path: blie
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 3
Prop-content-length: 105
Content-length: 105

K 7
svn:log
V 5
Copy

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:28:44.996894Z
PROPS-END

Node-path: bloe
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: bla


Revision-number: 4
Prop-content-length: 112
Content-length: 112

K 7
svn:log
V 11
Change bla

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T23:51:09.678679Z
PROPS-END

Node-path: bla
Node-kind: dir
Node-action: change
Prop-content-length: 28
Content-length: 28

K 3
foo
V 5
bloe

PROPS-END


Revision-number: 5
Prop-content-length: 108
Content-length: 108

K 7
svn:log
V 8
Replace

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:30:06.383777Z
PROPS-END

Node-path: bla
Node-action: delete


Node-path: bla
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: bla


""")
        os.mkdir("old")

        load_dumpfile("dumpfile", "old")
        oldrepos = Repository.open("old")
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid)))
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:3@%s-" % (MAPPING_VERSION, oldrepos.uuid)))
        inv1 = newrepos.get_inventory(
                "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid))
        inv2 = newrepos.get_inventory(
                "svn-v%d:3@%s-" % (MAPPING_VERSION, oldrepos.uuid))
        self.assertEqual(inv1.path2id("bla"), inv2.path2id("bla"))

    def test_fetch_replace_unrelated(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        open(filename, 'w').write("""SVN-fs-dump-format-version: 2

UUID: 606c7b1f-987c-4826-b37d-eb456ceb87e1

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-12-26T00:04:55.850520Z
PROPS-END

Revision-number: 1
Prop-content-length: 103
Content-length: 103

K 7
svn:log
V 3
add
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:15.504335Z
PROPS-END

Node-path: x
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 2
Prop-content-length: 102
Content-length: 102

K 7
svn:log
V 2
rm
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:30.775369Z
PROPS-END

Node-path: x
Node-action: delete


Revision-number: 3
Prop-content-length: 105
Content-length: 105

K 7
svn:log
V 5
readd
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:43.584249Z
PROPS-END

Node-path: x
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 4
Prop-content-length: 108
Content-length: 108

K 7
svn:log
V 8
Replace

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:30:06.383777Z
PROPS-END

Node-path: x
Node-action: delete


Node-path: x
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: x

                
""")
        os.mkdir("old")

        load_dumpfile("dumpfile", "old")
        oldrepos = Repository.open("old")
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid)))
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:4@%s-" % (MAPPING_VERSION, oldrepos.uuid)))
        inv1 = newrepos.get_inventory(
                "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid))
        inv2 = newrepos.get_inventory(
                "svn-v%d:4@%s-" % (MAPPING_VERSION, oldrepos.uuid))
        self.assertNotEqual(inv1.path2id("x"), inv2.path2id("x"))

    def test_fetch_replace_related(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        open(filename, 'w').write("""SVN-fs-dump-format-version: 2

UUID: 606c7b1f-987c-4826-b37d-eb456ceb87e1

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-12-26T00:04:55.850520Z
PROPS-END

Revision-number: 1
Prop-content-length: 103
Content-length: 103

K 7
svn:log
V 3
add
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:15.504335Z
PROPS-END

Node-path: x
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 2
Prop-content-length: 102
Content-length: 102

K 7
svn:log
V 2
rm
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:30.775369Z
PROPS-END

Node-path: x
Node-action: delete


Revision-number: 3
Prop-content-length: 105
Content-length: 105

K 7
svn:log
V 5
readd
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:43.584249Z
PROPS-END

Node-path: y
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: x
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 4
Prop-content-length: 108
Content-length: 108

K 7
svn:log
V 8
Replace

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:30:06.383777Z
PROPS-END

Node-path: y
Node-action: delete


Revision-number: 5
Prop-content-length: 108
Content-length: 108

K 7
svn:log
V 8
Replace

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:30:06.383777Z
PROPS-END


Node-path: y
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: x


""")
        os.mkdir("old")

        load_dumpfile("dumpfile", "old")
        oldrepos = Repository.open("old")
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid)))
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:5@%s-" % (MAPPING_VERSION, oldrepos.uuid)))
        inv1 = newrepos.get_inventory(
                "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid))
        inv2 = newrepos.get_inventory(
                "svn-v%d:5@%s-" % (MAPPING_VERSION, oldrepos.uuid))
        self.assertNotEqual(inv1.path2id("y"), inv2.path2id("y"))

    def test_fetch_dir_upgrade(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/trunk/lib/file': 'data'})
        self.client_add("dc/trunk")
        self.client_commit("dc", "trunk data")

        self.build_tree({'dc/branches': None})
        self.client_add("dc/branches")
        self.client_copy("dc/trunk/lib", "dc/branches/mybranch")
        self.client_commit("dc", "split out lib")

        oldrepos = Repository.open(repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme())
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

        branch = Branch.open("%s/branches/mybranch" % repos_url)
        self.assertEqual(['svn-v%d:2@%s-branches%%2fmybranch' % (MAPPING_VERSION, oldrepos.uuid)], 
                         branch.revision_history())

    def test_fetch_file_from_non_branch(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/old-trunk/lib/file': 'data'})
        self.client_add("dc/old-trunk")
        self.client_commit("dc", "trunk data")

        self.build_tree({'dc/trunk/lib': None})
        self.client_add("dc/trunk")
        self.client_copy("dc/old-trunk/lib/file", "dc/trunk/lib/file")
        self.client_commit("dc", "revive old trunk")

        oldrepos = Repository.open(repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme())
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

        branch = Branch.open("%s/trunk" % repos_url)
        self.assertEqual(['svn-v%d:2@%s-trunk' % (MAPPING_VERSION, oldrepos.uuid)], 
                         branch.revision_history())

    def test_fetch_dir_from_non_branch(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/old-trunk/lib/file': 'data'})
        self.client_add("dc/old-trunk")
        self.client_commit("dc", "trunk data")

        self.build_tree({'dc/trunk': None})
        self.client_add("dc/trunk")
        self.client_copy("dc/old-trunk/lib", "dc/trunk")
        self.client_commit("dc", "revive old trunk")

        oldrepos = Repository.open(repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme())
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

        branch = Branch.open("%s/trunk" % repos_url)
        self.assertEqual(['svn-v%d:2@%s-trunk' % (MAPPING_VERSION, oldrepos.uuid)], 
                         branch.revision_history())

    def test_fetch_from_non_branch(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/old-trunk/lib/file': 'data'})
        self.client_add("dc/old-trunk")
        self.client_commit("dc", "trunk data")

        self.client_copy("dc/old-trunk", "dc/trunk")
        self.client_commit("dc", "revive old trunk")

        oldrepos = Repository.open(repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme())
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

        branch = Branch.open("%s/trunk" % repos_url)
        self.assertEqual(['svn-v%d:2@%s-trunk' % (MAPPING_VERSION, oldrepos.uuid)], 
                         branch.revision_history())



    def test_fetch_branch_downgrade(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/trunk/file': 'data'})
        self.client_add("dc/trunk")
        self.client_commit("dc", "trunk data")

        self.build_tree({'dc/branches/mybranch': None})
        self.client_add("dc/branches")
        self.client_copy("dc/trunk", "dc/branches/mybranch/lib")
        self.client_commit("dc", "split out lib")

        oldrepos = Repository.open(repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme())
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

    # FIXME
    def notest_fetch_all(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/trunk': None, 
                         'dc/trunk/hosts': 'hej1'})
        self.client_add("dc/trunk")
        self.client_commit("dc", "created trunk and added hosts") #1

        self.build_tree({'dc/trunk/hosts': 'hej2'})
        self.client_commit("dc", "rev 2") #2

        self.build_tree({'dc/trunk/hosts': 'hej3'})
        self.client_commit("dc", "rev 3") #3

        self.build_tree({'dc/branches/foobranch/file': 'foohosts'})
        self.client_add("dc/branches")
        self.client_commit("dc", "foohosts") #4

        oldrepos = format.SvnRemoteAccess(SvnRaTransport("svn+"+repos_url), format.SvnFormat(), 
                                   TrunkBranchingScheme()).find_repository()
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

        self.assertTrue(newrepos.has_revision(
            "svn-v%d:1@%s-trunk" % (MAPPING_VERSION, oldrepos.uuid)))
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:2@%s-trunk" % (MAPPING_VERSION, oldrepos.uuid)))
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:3@%s-trunk" % (MAPPING_VERSION, oldrepos.uuid)))
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:4@%s-branches%%2ffoobranch" % (MAPPING_VERSION, oldrepos.uuid)))
        self.assertFalse(newrepos.has_revision(
            "svn-v%d:4@%s-trunk" % (MAPPING_VERSION, oldrepos.uuid)))
        self.assertFalse(newrepos.has_revision(
            "svn-v%d:2@%s-" % (MAPPING_VERSION, oldrepos.uuid)))

    def test_fetch_odd(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/trunk': None, 
                         'dc/trunk/hosts': 'hej1'})
        self.client_add("dc/trunk")
        self.client_commit("dc", "created trunk and added hosts") #1

        self.build_tree({'dc/trunk/hosts': 'hej2'})
        self.client_commit("dc", "rev 2") #2

        self.build_tree({'dc/trunk/hosts': 'hej3'})
        self.client_commit("dc", "rev 3") #3

        self.build_tree({'dc/branches': None})
        self.client_add("dc/branches")
        self.client_commit("dc", "added branches") #4

        self.client_copy("dc/trunk", "dc/branches/foobranch")
        self.client_commit("dc", "added branch foobranch") #5

        self.build_tree({'dc/branches/foobranch/hosts': 'foohosts'})
        self.client_commit("dc", "foohosts") #6

        repos = format.SvnRemoteAccess(SvnRaTransport("svn+"+repos_url), format.SvnFormat(), 
                                   TrunkBranchingScheme()).find_repository()

        tree = repos.revision_tree(
             "svn-v%d:6@%s-branches%%2ffoobranch" % (MAPPING_VERSION, repos.uuid))

    def test_fetch_consistent(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/bla': "data"})
        self.client_add("dc/bla")
        self.client_set_prop("dc/bla", "svn:executable", "*")
        self.client_commit("dc", "My Message")
        oldrepos = Repository.open("svn+"+repos_url)
        dir1 = BzrDir.create("f")
        dir2 = BzrDir.create("g")
        newrepos1 = dir1.create_repository()
        newrepos2 = dir2.create_repository()
        oldrepos.copy_content_into(newrepos1)
        oldrepos.copy_content_into(newrepos2)
        inv1 = newrepos1.get_inventory(
                "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid))
        inv2 = newrepos2.get_inventory(
                "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid))
        self.assertEqual(inv1, inv2)

    def test_fetch_executable(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/bla': "data", 'dc/blie': "data2"})
        self.client_add("dc/bla")
        self.client_add("dc/blie")
        self.client_set_prop("dc/bla", "svn:executable", "*")
        self.client_set_prop("dc/blie", "svn:executable", "")
        self.client_commit("dc", "My Message")
        oldrepos = Repository.open("svn+"+repos_url)
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid)))
        inv1 = newrepos.get_inventory(
                "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid))
        self.assertTrue(inv1[inv1.path2id("bla")].executable)
        self.assertTrue(inv1[inv1.path2id("blie")].executable)

    def test_fetch_symlink(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/bla': "data"})
        os.symlink('bla', 'dc/mylink')
        self.client_add("dc/bla")
        self.client_add("dc/mylink")
        self.client_commit("dc", "My Message")
        oldrepos = Repository.open("svn+"+repos_url)
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid)))
        inv1 = newrepos.get_inventory(
                "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid))
        self.assertEqual('symlink', inv1[inv1.path2id("mylink")].kind)
        self.assertEqual('bla', inv1[inv1.path2id("mylink")].symlink_target)


    def test_fetch_executable_separate(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/bla': "data"})
        self.client_add("dc/bla")
        self.client_commit("dc", "My Message")
        self.client_set_prop("dc/bla", "svn:executable", "*")
        self.client_commit("dc", "Make executable")
        oldrepos = Repository.open("svn+"+repos_url)
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision(
            "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid)))
        inv1 = newrepos.get_inventory(
                "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid))
        self.assertFalse(inv1[inv1.path2id("bla")].executable)
        inv2 = newrepos.get_inventory(
                "svn-v%d:2@%s-" % (MAPPING_VERSION, oldrepos.uuid))
        self.assertTrue(inv2[inv2.path2id("bla")].executable)
        self.assertEqual("svn-v%d:2@%s-" % (MAPPING_VERSION, oldrepos.uuid), 
                         inv2[inv2.path2id("bla")].revision)

    def test_fetch_ghosts(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/bla': "data"})
        self.client_add("dc/bla")
        self.client_set_prop("dc", "bzr:merge", "aghost\n")
        self.client_commit("dc", "My Message")
        oldrepos = Repository.open("svn+"+repos_url)
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

        rev = newrepos.get_revision(
                "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid))
        self.assertTrue("aghost" in rev.parent_ids)

    def test_fetch_invalid_ghosts(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/bla': "data"})
        self.client_add("dc/bla")
        self.client_set_prop("dc", "bzr:merge", "a ghost\n")
        self.client_commit("dc", "My Message")
        oldrepos = Repository.open("svn+"+repos_url)
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

        rev = newrepos.get_revision(
                "svn-v%d:1@%s-" % (MAPPING_VERSION, oldrepos.uuid))
        self.assertEqual([], rev.parent_ids)

    def test_set_branching_scheme(self):
        repos_url = self.make_client('d', 'dc')
        repos = Repository.open(repos_url)
        repos.set_branching_scheme(NoBranchingScheme())

    def test_fetch_crosscopy(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/trunk/adir/afile': "data", 
                         'dc/trunk/adir/stationary': None,
                         'dc/branches/abranch': None})
        self.client_add("dc/trunk")
        self.client_add("dc/branches")
        self.client_commit("dc", "Initial commit")

        # copyrev
        self.client_copy("dc/trunk/adir", "dc/branches/abranch/bdir")
        self.client_commit("dc", "Cross copy commit")

        # prevrev
        self.build_tree({"dc/branches/abranch/bdir/afile": "otherdata"})
        self.client_commit("dc", "Change data")

        # lastrev
        self.build_tree({"dc/branches/abranch/bdir/bfile": "camel",
                      "dc/branches/abranch/bdir/stationary/traveller": "data"})
        self.client_add("dc/branches/abranch/bdir/bfile")
        self.client_add("dc/branches/abranch/bdir/stationary/traveller")
        self.client_commit("dc", "Change dir")

        oldrepos = Repository.open("svn+"+repos_url)
        oldrepos.set_branching_scheme(TrunkBranchingScheme())
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        copyrev = "svn-v%d:2@%s-branches%%2fabranch" % (MAPPING_VERSION, oldrepos.uuid)
        prevrev = "svn-v%d:3@%s-branches%%2fabranch" % (MAPPING_VERSION, oldrepos.uuid)
        lastrev = "svn-v%d:4@%s-branches%%2fabranch" % (MAPPING_VERSION, oldrepos.uuid)
        oldrepos.copy_content_into(newrepos, lastrev)

        inventory = newrepos.get_inventory(lastrev)
        self.assertEqual(prevrev, 
                         inventory[inventory.path2id("bdir/afile")].revision)

        inventory = newrepos.get_inventory(prevrev)
        self.assertEqual(copyrev, 
                         inventory[inventory.path2id("bdir/stationary")].revision)

class TestSvnRevisionTree(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestSvnRevisionTree, self).setUp()
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.repos = Repository.open(repos_url)
        self.inventory = self.repos.get_inventory(
                "svn-v%d:1@%s-" % (MAPPING_VERSION, self.repos.uuid))
        self.tree = self.repos.revision_tree(
                "svn-v%d:1@%s-" % (MAPPING_VERSION, self.repos.uuid))

    def test_inventory(self):
        self.assertIsInstance(self.tree.inventory, Inventory)
        self.assertEqual(self.inventory, self.tree.inventory)

    def test_get_parent_ids(self):
        self.assertEqual([], self.tree.get_parent_ids())

    def test_get_revision_id(self):
        self.assertEqual("svn-v%d:1@%s-" % (MAPPING_VERSION, self.repos.uuid), 
                         self.tree.get_revision_id())

    def test_get_file_lines(self):
        self.assertEqual(["data"], 
                self.tree.get_file_lines(self.inventory.path2id("foo/bla")))

    def test_executable(self):
        self.client_set_prop("dc/foo/bla", "svn:executable", "*")
        self.client_commit("dc", "My Message")
        
        inventory = self.repos.get_inventory(
                "svn-v%d:2@%s-" % (MAPPING_VERSION, self.repos.uuid))

        self.assertTrue(inventory[inventory.path2id("foo/bla")].executable)

    def test_symlink(self):
        os.symlink('foo/bla', 'dc/bar')
        self.client_add('dc/bar')
        self.client_commit("dc", "My Message")
        
        inventory = self.repos.get_inventory(
                "svn-v%d:2@%s-" % (MAPPING_VERSION, self.repos.uuid))

        self.assertEqual('symlink', inventory[inventory.path2id("bar")].kind)
        self.assertEqual('foo/bla', inventory[inventory.path2id("bar")].symlink_target)

    def test_not_executable(self):
        self.assertFalse(self.inventory[
            self.inventory.path2id("foo/bla")].executable)

class RevisionIdMappingTest(TestCase):
    def test_generate_revid(self):
        self.assertEqual("svn-v%d:5@myuuid-branch" % MAPPING_VERSION, 
                         generate_svn_revision_id("myuuid", 5, "branch"))

    def test_generate_revid_nested(self):
        self.assertEqual("svn-v%d:5@myuuid-branch%%2fpath" % MAPPING_VERSION, 
                         generate_svn_revision_id("myuuid", 5, "branch/path"))

    def test_generate_revid_special_char(self):
        self.assertEqual(u"svn-v%d:5@myuuid-branch\x2c" % MAPPING_VERSION, 
                         generate_svn_revision_id("myuuid", 5, u"branch\x2c"))

    def test_parse_revid_simple(self):
        self.assertEqual(("uuid", "", 4),
                         parse_svn_revision_id(
                             "svn-v%d:4@uuid-" % MAPPING_VERSION))

    def test_parse_revid_nested(self):
        self.assertEqual(("uuid", "bp/data", 4),
                         parse_svn_revision_id(
                             "svn-v%d:4@uuid-bp%%2fdata" % MAPPING_VERSION))

    def test_svk_revid_map_root(self):
        self.assertEqual("svn-v%d:6@auuid-" % MAPPING_VERSION,
                         svk_feature_to_revision_id("auuid:/:6"))

    def test_svk_revid_map_nested(self):
        self.assertEqual("svn-v%d:6@auuid-bp" % MAPPING_VERSION,
                         svk_feature_to_revision_id("auuid:/bp:6"))

    def test_revid_svk_map(self):
        self.assertEqual("auuid:/:6", 
              revision_id_to_svk_feature("svn-v%d:6@auuid-" % MAPPING_VERSION))


class EscapeTest(TestCase):
    def test_escape_svn_path_none(self):      
        self.assertEqual("", escape_svn_path(""))

    def test_escape_svn_path_simple(self):
        self.assertEqual("ab", escape_svn_path("ab"))

    def test_escape_svn_path_percent(self):
        self.assertEqual("a%25b", escape_svn_path("a%b"))

    def test_escape_svn_path_whitespace(self):
        self.assertEqual("foobar%20", escape_svn_path("foobar "))

    def test_escape_svn_path_slash(self):
        self.assertEqual("foobar%2f", escape_svn_path("foobar/"))

    def test_unescape_svn_path_slash(self):
        self.assertEqual("foobar/", unescape_svn_path("foobar%2f"))

    def test_unescape_svn_path_none(self):
        self.assertEqual("foobar", unescape_svn_path("foobar"))

    def test_unescape_svn_path_percent(self):
        self.assertEqual("foobar%b", unescape_svn_path("foobar%25b"))

class SvnRepositoryFormatTests(TestCase):
    def setUp(self):
        self.format = SvnRepositoryFormat()

    def test_initialize(self):
        self.assertRaises(UninitializableFormat, self.format.initialize, None)

    def test_get_format_description(self):
        self.assertEqual("Subversion Repository", 
                         self.format.get_format_description())
