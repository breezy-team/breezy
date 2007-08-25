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

"""Subversion repository tests."""

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir, format_registry
from bzrlib.errors import NoSuchRevision, UninitializableFormat, BzrError
from bzrlib.inventory import Inventory
from bzrlib.repository import Repository
from bzrlib.revision import NULL_REVISION, Revision
from bzrlib.tests import TestCase

import os

import svn.fs

from errors import InvalidPropertyValue
from fileids import generate_svn_file_id, generate_file_id
import format
from scheme import (TrunkBranchingScheme, NoBranchingScheme, 
                    ListBranchingScheme)
from transport import SvnRaTransport
from tests import TestCaseWithSubversionRepository
from tests.test_fileids import MockRepo
from repository import (revision_id_to_svk_feature,
                        SvnRepositoryFormat, SVN_PROP_BZR_REVISION_ID,
                        generate_revision_metadata, parse_revision_metadata,
                        parse_revid_property, SVN_PROP_BZR_BRANCHING_SCHEME)
from revids import (MAPPING_VERSION, escape_svn_path, unescape_svn_path,
                    parse_svn_revision_id, generate_svn_revision_id)


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

        self.assertEqual(2, 
             len(list(repos.follow_branch_history("", 1, NoBranchingScheme()))))

    def test_make_working_trees(self):
        repos_url = self.make_client("a", "dc")
        repos = Repository.open(repos_url)
        self.assertFalse(repos.make_working_trees())

    def test_get_physical_lock_status(self):
        repos_url = self.make_client("a", "dc")
        repos = Repository.open(repos_url)
        self.assertFalse(repos.get_physical_lock_status())

    def test_set_make_working_trees(self):
        repos_url = self.make_client("a", "dc")
        repos = Repository.open(repos_url)
        repos.set_make_working_trees(True)
        self.assertFalse(repos.make_working_trees())

    def test_get_fileid_map(self):
        repos_url = self.make_client("a", "dc")
        repos = Repository.open(repos_url)
        revid = repos.generate_revision_id(0, "", "none")
        self.assertEqual({"": (generate_file_id(MockRepo(repos.uuid), revid, ""), revid)}, repos.get_fileid_map(0, "", NoBranchingScheme()))

    def test_generate_revision_id_forced_revid(self):
        repos_url = self.make_client("a", "dc")
        self.client_set_prop("dc", SVN_PROP_BZR_REVISION_ID+"none", 
                             "2 someid\n")
        self.client_commit("dc", "set id")
        repos = Repository.open(repos_url)
        revid = repos.generate_revision_id(1, "", "none")
        self.assertEquals("someid", revid)

    def test_generate_revision_id_forced_revid_invalid(self):
        repos_url = self.make_client("a", "dc")
        self.client_set_prop("dc", SVN_PROP_BZR_REVISION_ID+"none", 
                             "corrupt-id\n")
        self.client_commit("dc", "set id")
        repos = Repository.open(repos_url)
        revid = repos.generate_revision_id(1, "", "undefined")
        self.assertEquals(
               u"svn-v%d-undefined:%s::1" % (MAPPING_VERSION, repos.uuid),
               revid)

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
               repos.follow_branch_history("/", 20, NoBranchingScheme()))

    def test_history_all(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/file': "data", "dc/foo/file":"data"})
        self.client_add("dc/trunk")
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        repos = Repository.open(repos_url)

        self.assertEqual(2, 
                   len(list(repos.follow_history(1, NoBranchingScheme()))))

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
            repos.generate_revision_id(2, "branches/somebranch", "trunk0"),
            repos.generate_revision_id(1, "trunk", "trunk0")], 
            list(repos.all_revision_ids()))

    def test_follow_history_empty(self):
        repos_url = self.make_client("a", "dc")
        self.assertEqual([('', 0)], 
              list(Repository.open(repos_url).follow_history(0, 
                  NoBranchingScheme())))

    def test_follow_history_empty_branch(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/afile': "data", "dc/branches": None})
        self.client_add("dc/trunk")
        self.client_add("dc/branches")
        self.client_commit("dc", "My Message")
        repos = Repository.open(repos_url)
        self.assertEqual([('trunk', 1)], 
                list(repos.follow_history(1, TrunkBranchingScheme())))

    def test_follow_history_follow(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/afile': "data", "dc/branches": None})
        self.client_add("dc/trunk")
        self.client_add("dc/branches")
        self.client_commit("dc", "My Message")

        self.client_copy("dc/trunk", "dc/branches/abranch")
        self.client_commit("dc", "Create branch")

        repos = Repository.open(repos_url)

        items = list(repos.follow_history(2, TrunkBranchingScheme()))
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
            1, TrunkBranchingScheme()))))

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
            2, TrunkBranchingScheme()))))

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
                list(repos.find_branches(TrunkBranchingScheme(), 2)))

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
                list(repos.find_branches(TrunkBranchingScheme(1), 2)))

    def test_find_branches_no(self):
        repos_url = self.make_client("a", "dc")

        repos = Repository.open(repos_url)
        repos.set_branching_scheme(NoBranchingScheme())

        self.assertEqual([("", 0, True)], 
                list(repos.find_branches(NoBranchingScheme(), 0)))

    def test_find_branches_no_later(self):
        repos_url = self.make_client("a", "dc")

        repos = Repository.open(repos_url)
        repos.set_branching_scheme(NoBranchingScheme())

        self.assertEqual([("", 0, True)], 
                list(repos.find_branches(NoBranchingScheme(), 0)))

    def test_find_branches_trunk_empty(self):
        repos_url = self.make_client("a", "dc")

        repos = Repository.open(repos_url)
        repos.set_branching_scheme(TrunkBranchingScheme())

        self.assertEqual([], 
                list(repos.find_branches(TrunkBranchingScheme(), 0)))

    def test_find_branches_trunk_one(self):
        repos_url = self.make_client("a", "dc")

        repos = Repository.open(repos_url)
        repos.set_branching_scheme(TrunkBranchingScheme())

        self.build_tree({'dc/trunk/foo': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")

        self.assertEqual([("trunk", 1, True)], 
                list(repos.find_branches(TrunkBranchingScheme(), 1)))

    def test_find_branches_removed(self):
        repos_url = self.make_client("a", "dc")

        repos = Repository.open(repos_url)
        repos.set_branching_scheme(TrunkBranchingScheme())

        self.build_tree({'dc/trunk/foo': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")

        self.client_delete("dc/trunk")
        self.client_commit("dc", "remove")

        self.assertEqual([("trunk", 1, True)], 
                list(repos.find_branches(TrunkBranchingScheme(), 1)))
        self.assertEqual([("trunk", 1, False)], 
                list(repos.find_branches(TrunkBranchingScheme(), 2)))

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
            repository.generate_revision_id(1, "", "none")))
        self.assertFalse(repository.has_revision("some-other-revision"))

    def test_has_revision_none(self):
        bzrdir = self.make_client_and_bzrdir('d', 'dc')
        repository = bzrdir.find_repository()
        self.assertTrue(repository.has_revision(None))

    def test_has_revision_future(self):
        bzrdir = self.make_client_and_bzrdir('d', 'dc')
        repository = bzrdir.find_repository()
        self.assertFalse(repository.has_revision(
            generate_svn_revision_id(repository.uuid, 5, "", "none")))

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
                    repository.generate_revision_id(0, "", "none")))
        self.assertEqual([repository.generate_revision_id(0, "", "none")],
                repository.revision_parents(
                    repository.generate_revision_id(1, "", "none")))
        self.assertEqual([
            repository.generate_revision_id(1, "", "none")],
            repository.revision_parents(
                repository.generate_revision_id(2, "", "none")))

    def test_revision_fileidmap(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_set_prop("dc", "bzr:revision-info", "")
        self.client_set_prop("dc", "bzr:file-ids", "foo\tsomeid\n")
        self.client_commit("dc", "My Message")
        repository = Repository.open("svn+%s" % repos_url)
        tree = repository.revision_tree(Branch.open(repos_url).last_revision())
        self.assertEqual("someid", tree.inventory.path2id("foo"))
        self.assertFalse("1@%s::foo" % repository.uuid in tree.inventory)

    def test_revision_ghost_parents(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.client_update("dc")
        self.build_tree({'dc/foo': "data2"})
        self.client_set_prop("dc", "bzr:ancestry:v3-none", "ghostparent\n")
        self.client_commit("dc", "Second Message")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual([],
                repository.revision_parents(
                    repository.generate_revision_id(0, "", "none")))
        self.assertEqual([repository.generate_revision_id(0, "", "none")],
                repository.revision_parents(
                    repository.generate_revision_id(1, "", "none")))
        self.assertEqual([repository.generate_revision_id(1, "", "none"),
            "ghostparent"], 
                repository.revision_parents(
                    repository.generate_revision_id(2, "", "none")))
 
    def test_revision_svk_parent(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/trunk/foo': "data", 'dc/branches/foo': None})
        self.client_add("dc/trunk")
        self.client_add("dc/branches")
        self.client_commit("dc", "My Message")
        self.client_update("dc")
        self.build_tree({'dc/trunk/foo': "data2"})
        repository = Repository.open("svn+%s" % repos_url)
        self.client_set_prop("dc/trunk", "svk:merge", 
            "%s:/branches/foo:1\n" % repository.uuid)
        self.client_commit("dc", "Second Message")
        self.assertEqual([repository.generate_revision_id(1, "trunk", "trunk0"),
            repository.generate_revision_id(1, "branches/foo", "trunk0")], 
                repository.revision_parents(
                    repository.generate_revision_id(2, "trunk", "trunk0")))
 
    
    def test_get_revision(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.assertRaises(NoSuchRevision, repository.get_revision, 
                "nonexisting")
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.client_update("dc")
        self.build_tree({'dc/foo': "data2"})
        (num, date, author) = self.client_commit("dc", "Second Message")
        repository = Repository.open("svn+%s" % repos_url)
        rev = repository.get_revision(
            repository.generate_revision_id(2, "", "none"))
        self.assertEqual([repository.generate_revision_id(1, "", "none")],
                rev.parent_ids)
        self.assertEqual(rev.revision_id, 
                repository.generate_revision_id(2, "", "none"))
        self.assertEqual(author, rev.committer)
        self.assertIsInstance(rev.properties, dict)

    def test_get_revision_id_overriden(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.assertRaises(NoSuchRevision, repository.get_revision, "nonexisting")
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo': "data2"})
        self.client_set_prop("dc", "bzr:revision-id:v%d-none" % MAPPING_VERSION, 
                            "3 myrevid\n")
        self.client_update("dc")
        (num, date, author) = self.client_commit("dc", "Second Message")
        repository = Repository.open("svn+%s" % repos_url)
        revid = generate_svn_revision_id(repository.uuid, 2, "", "none")
        rev = repository.get_revision("myrevid")
        self.assertEqual([repository.generate_revision_id(1, "", "none")],
                rev.parent_ids)
        self.assertEqual(rev.revision_id, 
                         repository.generate_revision_id(2, "", "none"))
        self.assertEqual(author, rev.committer)
        self.assertIsInstance(rev.properties, dict)

    def test_get_revision_zero(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        rev = repository.get_revision(
            repository.generate_revision_id(0, "", "none"))
        self.assertEqual(repository.generate_revision_id(0, "", "none"), 
                         rev.revision_id)
        self.assertEqual("", rev.committer)
        self.assertEqual({}, rev.properties)
        self.assertEqual(None, rev.timezone)
        self.assertEqual(0.0, rev.timestamp)

    def test_store_branching_scheme(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open(repos_url)
        repository.set_branching_scheme(TrunkBranchingScheme(42))
        repository = Repository.open(repos_url)
        self.assertEquals("trunk42", str(repository.get_scheme()))

    def test_get_ancestry(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.assertRaises(NoSuchRevision, repository.get_revision, "nonexisting")
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.client_update("dc")
        self.build_tree({'dc/foo': "data2"})
        self.client_commit("dc", "Second Message")
        self.client_update("dc")
        self.build_tree({'dc/foo': "data3"})
        self.client_commit("dc", "Third Message")
        self.client_update("dc")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual([None, 
            repository.generate_revision_id(0, "", "none"),
            repository.generate_revision_id(1, "", "none"),
            repository.generate_revision_id(2, "", "none"),
            repository.generate_revision_id(3, "", "none")],
                repository.get_ancestry(
                    repository.generate_revision_id(3, "", "none")))
        self.assertEqual([None, 
            repository.generate_revision_id(0, "", "none"),
            repository.generate_revision_id(1, "", "none"),
            repository.generate_revision_id(2, "", "none")],
                repository.get_ancestry(
                    repository.generate_revision_id(2, "", "none")))
        self.assertEqual([None,
                    repository.generate_revision_id(0, "", "none"),
                    repository.generate_revision_id(1, "", "none")],
                repository.get_ancestry(
                    repository.generate_revision_id(1, "", "none")))
        self.assertEqual([None, repository.generate_revision_id(0, "", "none")],
                repository.get_ancestry(
                    repository.generate_revision_id(0, "", "none")))
        self.assertEqual([None], repository.get_ancestry(None))

    def test_get_revision_graph_empty(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual({}, 
                repository.get_revision_graph(NULL_REVISION))

    def test_get_revision_graph_invalid(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.assertRaises(NoSuchRevision, repository.get_revision_graph, 
                          "nonexisting")

    def test_get_revision_graph_all_empty(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open(repos_url)
        self.assertEqual({repository.generate_revision_id(0, "", "none"): []}, 
                repository.get_revision_graph())

    def test_get_revision_graph_zero(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open(repos_url)
        self.assertEqual({repository.generate_revision_id(0, "", "none"): []}, 
                repository.get_revision_graph(
                    repository.generate_revision_id(0, "", "none")))

    def test_get_revision_graph_all(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/trunk/a': 'data', 'dc/branches/foo/b': 'alsodata'})
        self.client_add("dc/trunk")
        self.client_add("dc/branches")
        self.client_commit("dc", "initial commit")
        self.build_tree({'dc/trunk/a': "bloe"})
        self.client_commit("dc", "second commit")
        repository = Repository.open(repos_url)
        repository.set_branching_scheme(TrunkBranchingScheme())
        self.assertEqual({repository.generate_revision_id(1, "trunk", "trunk0"): [],
                          repository.generate_revision_id(2, "trunk", "trunk0"): [repository.generate_revision_id(1, "trunk", "trunk0")],
                          repository.generate_revision_id(1, "branches/foo", "trunk0"): []
                          }, repository.get_revision_graph())

    def test_get_revision_graph(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.client_update("dc")
        self.build_tree({'dc/foo': "data2"})
        self.client_commit("dc", "Second Message")
        self.client_update("dc")
        self.build_tree({'dc/foo': "data3"})
        self.client_commit("dc", "Third Message")
        self.client_update("dc")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual({
            repository.generate_revision_id(0, "", "none"): [],
           repository.generate_revision_id(3, "", "none"): [
               repository.generate_revision_id(2, "", "none")],
           repository.generate_revision_id(2, "", "none"): [
               repository.generate_revision_id(1, "", "none")], 
           repository.generate_revision_id(1, "", "none"): [
               repository.generate_revision_id(0, "", "none")]},
                repository.get_revision_graph(
                    repository.generate_revision_id(3, "", "none")))
        self.assertEqual({
            repository.generate_revision_id(0, "", "none"): [],
           repository.generate_revision_id(2, "", "none"): [
               repository.generate_revision_id(1, "", "none")],
           repository.generate_revision_id(1, "", "none"): [
                repository.generate_revision_id(0, "", "none")
               ]},
                repository.get_revision_graph(
                    repository.generate_revision_id(2, "", "none")))
        self.assertEqual({
            repository.generate_revision_id(0, "", "none"): [],
            repository.generate_revision_id(1, "", "none"): [
                repository.generate_revision_id(0, "", "none")
                ]},
                repository.get_revision_graph(
                    repository.generate_revision_id(1, "", "none")))

    def test_get_ancestry2(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo': "data2"})
        self.client_commit("dc", "Second Message")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual([None, repository.generate_revision_id(0, "", "none")],
                repository.get_ancestry(
                    repository.generate_revision_id(0, "", "none")))
        self.assertEqual([None, repository.generate_revision_id(0, "", "none"),
            repository.generate_revision_id(1, "", "none")],
                repository.get_ancestry(
                    repository.generate_revision_id(1, "", "none")))
        self.assertEqual([None, 
            repository.generate_revision_id(0, "", "none"),
            repository.generate_revision_id(1, "", "none"),
            repository.generate_revision_id(2, "", "none")], 
                repository.get_ancestry(
                    repository.generate_revision_id(2, "", "none")))

    def test_get_ancestry_merged(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.client_update("dc")
        self.client_set_prop("dc", "bzr:ancestry:v3-none", "a-parent\n")
        self.build_tree({'dc/foo': "data2"})
        self.client_commit("dc", "Second Message")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual([None, repository.generate_revision_id(0, "", "none")],
                repository.get_ancestry(
                    repository.generate_revision_id(0, "", "none")))
        self.assertEqual([None, repository.generate_revision_id(0, "", "none"),
            repository.generate_revision_id(1, "", "none")],
                repository.get_ancestry(
                    repository.generate_revision_id(1, "", "none")))
        self.assertEqual([None, 
            repository.generate_revision_id(0, "", "none"),
            repository.generate_revision_id(1, "", "none"), 
                  "a-parent", repository.generate_revision_id(2, "", "none")], 
                repository.get_ancestry(
                    repository.generate_revision_id(2, "", "none")))

    def test_get_inventory(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.assertRaises(NoSuchRevision, repository.get_inventory, 
                "nonexisting")
        self.build_tree({'dc/foo': "data", 'dc/blah': "other data"})
        self.client_add("dc/foo")
        self.client_add("dc/blah")
        self.client_commit("dc", "My Message") #1
        self.client_update("dc")
        self.build_tree({'dc/foo': "data2", "dc/bar/foo": "data3"})
        self.client_add("dc/bar")
        self.client_commit("dc", "Second Message") #2
        self.client_update("dc")
        self.build_tree({'dc/foo': "data3"})
        self.client_commit("dc", "Third Message") #3
        self.client_update("dc")
        repository = Repository.open("svn+%s" % repos_url)
        inv = repository.get_inventory(
                repository.generate_revision_id(1, "", "none"))
        self.assertIsInstance(inv, Inventory)
        self.assertIsInstance(inv.path2id("foo"), basestring)
        inv = repository.get_inventory(
            repository.generate_revision_id(2, "", "none"))
        self.assertEqual(repository.generate_revision_id(2, "", "none"), 
                         inv[inv.path2id("foo")].revision)
        self.assertEqual(repository.generate_revision_id(1, "", "none"), 
                         inv[inv.path2id("blah")].revision)
        self.assertIsInstance(inv, Inventory)
        self.assertIsInstance(inv.path2id("foo"), basestring)
        self.assertIsInstance(inv.path2id("bar"), basestring)
        self.assertIsInstance(inv.path2id("bar/foo"), basestring)

    def test_generate_revision_id(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/bla/bloe': None})
        self.client_add("dc/bla")
        self.client_commit("dc", "bla")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual(
               u"svn-v%d-none:%s:bla%%2Fbloe:1" % (MAPPING_VERSION, repository.uuid), 
            repository.generate_revision_id(1, "bla/bloe", "none"))

    def test_generate_revision_id_zero(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual("svn-v%d-none:%s::0" % (MAPPING_VERSION, repository.uuid), 
                repository.generate_revision_id(0, "", "none"))

    def test_lookup_revision_id(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/bloe': None})
        self.client_add("dc/bloe")
        self.client_commit("dc", "foobar")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertRaises(NoSuchRevision, repository.lookup_revision_id, 
            "nonexisting")
        self.assertEqual(("bloe", 1), 
            repository.lookup_revision_id(
                repository.generate_revision_id(1, "bloe", "none"))[:2])

    def test_lookup_revision_id_overridden(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/bloe': None})
        self.client_add("dc/bloe")
        self.client_set_prop("dc", SVN_PROP_BZR_REVISION_ID+"none", "2 myid\n")
        self.client_commit("dc", "foobar")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual(("", 1), repository.lookup_revision_id( 
            generate_svn_revision_id(repository.uuid, 1, "", "none"))[:2])
        self.assertEqual(("", 1), 
                repository.lookup_revision_id("myid")[:2])

    def test_lookup_revision_id_overridden_invalid(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/bloe': None})
        self.client_add("dc/bloe")
        self.client_set_prop("dc", SVN_PROP_BZR_REVISION_ID+"none", 
                             "corrupt-entry\n")
        self.client_commit("dc", "foobar")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual(("", 1), repository.lookup_revision_id( 
            generate_svn_revision_id(repository.uuid, 1, "", "none"))[:2])
        self.assertRaises(NoSuchRevision, repository.lookup_revision_id, 
            "corrupt-entry")

    def test_lookup_revision_id_overridden_invalid_dup(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/bloe': None})
        self.client_add("dc/bloe")
        self.client_set_prop("dc", SVN_PROP_BZR_REVISION_ID+"none", 
                             "corrupt-entry\n")
        self.client_commit("dc", "foobar")
        self.build_tree({'dc/bla': None})
        self.client_add("dc/bla")
        self.client_set_prop("dc", SVN_PROP_BZR_REVISION_ID+"none", 
                "corrupt-entry\n2 corrupt-entry\n")
        self.client_commit("dc", "foobar")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual(("", 2), repository.lookup_revision_id( 
            generate_svn_revision_id(repository.uuid, 2, "", "none"))[:2])
        self.assertEqual(("", 1), repository.lookup_revision_id( 
            generate_svn_revision_id(repository.uuid, 1, "", "none"))[:2])
        self.assertEqual(("", 2), repository.lookup_revision_id( 
            "corrupt-entry")[:2])

    def test_lookup_revision_id_overridden_not_found(self):
        """Make sure a revision id that is looked up but doesn't exist 
        doesn't accidently end up in the revid cache."""
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/bloe': None})
        self.client_add("dc/bloe")
        self.client_set_prop("dc", SVN_PROP_BZR_REVISION_ID+"none", "2 myid\n")
        self.client_commit("dc", "foobar")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertRaises(NoSuchRevision, 
                repository.lookup_revision_id, "foobar")

    def test_set_branching_scheme_property(self):
        repos_url = self.make_client('d', 'dc')
        self.client_set_prop("dc", SVN_PROP_BZR_BRANCHING_SCHEME, 
            "trunk\nbranches/*\nbranches/tmp/*")
        self.client_commit("dc", "set scheme")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEquals(ListBranchingScheme(["trunk", "branches/*", "branches/tmp/*"]).branch_list,
                          repository.get_scheme().branch_list)

    def test_set_property_scheme(self):
        repos_url = self.make_client('d', 'dc')
        repos = Repository.open(repos_url)
        repos.set_property_scheme(ListBranchingScheme(["bla/*"]))
        self.client_update("dc")
        self.assertEquals("bla/*\n", 
                   self.client_get_prop("dc", SVN_PROP_BZR_BRANCHING_SCHEME))
        self.assertEquals("Updating branching scheme for Bazaar.", 
                self.client_log("dc", 1, 1)[1][3])

    def test_lookup_revision_id_invalid_uuid(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.assertRaises(NoSuchRevision, 
            repository.lookup_revision_id, 
                generate_svn_revision_id("invaliduuid", 0, "", "none"))
        
    def test_check(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        repository = Repository.open("svn+%s" % repos_url)
        repository.check([
            repository.generate_revision_id(0, "", "none"), 
            repository.generate_revision_id(1, "", "none")])

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

        to_bzrdir = BzrDir.create("e", format.get_rich_root_format())
        to_repos = to_bzrdir.create_repository()

        repository.copy_content_into(to_repos, 
                repository.generate_revision_id(2, "", "none"))

        self.assertTrue(repository.has_revision(
            repository.generate_revision_id(2, "", "none")))
        self.assertTrue(repository.has_revision(
            repository.generate_revision_id(1, "", "none")))
        self.assertFalse(repository.has_revision(
            generate_svn_revision_id(repository.uuid, 4, "", "trunk0")))

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
        self.client_set_prop("dc", "bzr:revision-info", "")
        self.client_set_prop("dc", "bzr:file-ids", "test\tbla\n")
        self.client_commit("dc", "Msg")

        repos = Repository.open(repos_url)
        renames = repos.revision_fileid_renames(
                repos.generate_revision_id(1, "", "none"))
        self.assertEqual({"test": "bla"}, renames)

    def test_fetch_property_change_only_trunk(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/trunk/bla': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")
        self.client_set_prop("dc/trunk", "some:property", "some data\n")
        self.client_commit("dc", "My 3")
        self.client_set_prop("dc/trunk", "some2:property", "some data\n")
        self.client_commit("dc", "My 2")
        self.client_set_prop("dc/trunk", "some:property", "some other data\n")
        self.client_commit("dc", "My 4")
        oldrepos = Repository.open("svn+"+repos_url)
        self.assertEquals([('trunk', 3), ('trunk', 2), ('trunk', 1)], list(oldrepos.follow_branch("trunk", 3, TrunkBranchingScheme())))

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
        dir = BzrDir.create("f",format=format.get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)

        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, "trunk", "trunk0")))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(2, "trunk", "trunk0")))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(3, "trunk", "trunk0")))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(4, "branches/foobranch", "trunk0")))
        self.assertFalse(newrepos.has_revision(
            oldrepos.generate_revision_id(4, "trunk", "trunk0")))
        self.assertFalse(newrepos.has_revision(
            oldrepos.generate_revision_id(2, "", "trunk0")))

        rev = newrepos.get_revision(oldrepos.generate_revision_id(1, "trunk", "trunk0"))
        self.assertEqual("$", rev.message)

        rev = newrepos.get_revision(
            oldrepos.generate_revision_id(2, "trunk", "trunk0"))
        self.assertEqual(u'bla\xfcbla', rev.message)

        rev = newrepos.get_revision(oldrepos.generate_revision_id(3, "trunk", "trunk0"))
        self.assertEqual(u"a\\x0cb", rev.message)

    def test_set_branching_scheme(self):
        repos_url = self.make_client('d', 'dc')
        repos = Repository.open(repos_url)
        repos.set_branching_scheme(NoBranchingScheme())

    def test_mainline_revision_parent_none(self):
        repos_url = self.make_client('d', 'dc')
        repos = Repository.open(repos_url)
        repos.set_branching_scheme(NoBranchingScheme())
        self.assertEquals(None, repos._mainline_revision_parent("", 0, NoBranchingScheme()))

    def test_mainline_revision_parent_first(self):
        repos_url = self.make_client('d', 'dc')
        repos = Repository.open(repos_url)
        repos.set_branching_scheme(NoBranchingScheme())
        self.build_tree({'dc/adir/afile': "data"})
        self.client_add("dc/adir")
        self.client_commit("dc", "Initial commit")
        self.assertEquals(repos.generate_revision_id(0, "", "none"), \
                repos._mainline_revision_parent("", 1, NoBranchingScheme()))

    def test_mainline_revision_parent_simple(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/trunk/adir/afile': "data", 
                         'dc/trunk/adir/stationary': None,
                         'dc/branches/abranch': None})
        self.client_add("dc/trunk")
        self.client_add("dc/branches")
        self.client_commit("dc", "Initial commit")
        self.build_tree({'dc/trunk/adir/afile': "bla"})
        self.client_commit("dc", "Incremental commit")
        repos = Repository.open(repos_url)
        repos.set_branching_scheme(TrunkBranchingScheme())
        self.assertEquals(repos.generate_revision_id(1, "trunk", "trunk0"), \
                repos._mainline_revision_parent("trunk", 2, TrunkBranchingScheme()))

    def test_mainline_revision_parent_copied(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/py/trunk/adir/afile': "data", 
                         'dc/py/trunk/adir/stationary': None})
        self.client_add("dc/py")
        self.client_commit("dc", "Initial commit")
        self.client_copy("dc/py", "dc/de")
        self.client_commit("dc", "Incremental commit")
        self.build_tree({'dc/de/trunk/adir/afile': "bla"})
        self.client_commit("dc", "Change de")
        repos = Repository.open(repos_url)
        repos.set_branching_scheme(TrunkBranchingScheme(1))
        self.assertEquals(repos.generate_revision_id(1, "py/trunk", "trunk1"), \
                repos._mainline_revision_parent("de/trunk", 3, TrunkBranchingScheme(1)))

    def test_mainline_revision_copied(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/py/trunk/adir/afile': "data", 
                         'dc/py/trunk/adir/stationary': None})
        self.client_add("dc/py")
        self.client_commit("dc", "Initial commit")
        self.build_tree({'dc/de':None})
        self.client_add("dc/de")
        self.client_copy("dc/py/trunk", "dc/de/trunk")
        self.client_commit("dc", "Copy trunk")
        repos = Repository.open(repos_url)
        repos.set_branching_scheme(TrunkBranchingScheme(1))
        self.assertEquals(repos.generate_revision_id(1, "py/trunk", "trunk1"), \
                repos._mainline_revision_parent("de/trunk", 2, TrunkBranchingScheme(1)))

    def test_mainline_revision_nested_deleted(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/py/trunk/adir/afile': "data", 
                         'dc/py/trunk/adir/stationary': None})
        self.client_add("dc/py")
        self.client_commit("dc", "Initial commit")
        self.client_copy("dc/py", "dc/de")
        self.client_commit("dc", "Incremental commit")
        self.client_delete("dc/de/trunk/adir")
        self.client_commit("dc", "Another incremental commit")
        repos = Repository.open(repos_url)
        repos.set_branching_scheme(TrunkBranchingScheme(1))
        self.assertEquals(repos.generate_revision_id(1, "py/trunk", "trunk1"), \
                repos._mainline_revision_parent("de/trunk", 3, TrunkBranchingScheme(1)))

    def test_mainline_revision_missing(self):
        repos_url = self.make_client('d', 'dc')
        repos = Repository.open(repos_url)
        self.build_tree({'dc/py/trunk/adir/afile': "data", 
                         'dc/py/trunk/adir/stationary': None})
        self.client_add("dc/py")
        self.client_commit("dc", "Initial commit")
        self.assertRaises(NoSuchRevision, 
                lambda: repos._mainline_revision_parent("trunk", 2, NoBranchingScheme()))


class TestSvnRevisionTree(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestSvnRevisionTree, self).setUp()
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.repos = Repository.open(repos_url)
        self.inventory = self.repos.get_inventory(
                self.repos.generate_revision_id(1, "", "none"))
        self.tree = self.repos.revision_tree(
                self.repos.generate_revision_id(1, "", "none"))

    def test_inventory(self):
        self.assertIsInstance(self.tree.inventory, Inventory)
        self.assertEqual(self.inventory, self.tree.inventory)

    def test_get_parent_ids(self):
        self.assertEqual([self.repos.generate_revision_id(0, "", "none")], self.tree.get_parent_ids())

    def test_get_parent_ids_zero(self):
        tree = self.repos.revision_tree(
                self.repos.generate_revision_id(0, "", "none"))
        self.assertEqual([], tree.get_parent_ids())

    def test_get_revision_id(self):
        self.assertEqual(self.repos.generate_revision_id(1, "", "none"),
                         self.tree.get_revision_id())

    def test_get_file_lines(self):
        self.assertEqual(["data"], 
                self.tree.get_file_lines(self.inventory.path2id("foo/bla")))

    def test_executable(self):
        self.client_set_prop("dc/foo/bla", "svn:executable", "*")
        self.client_commit("dc", "My Message")
        
        inventory = self.repos.get_inventory(
                self.repos.generate_revision_id(2, "", "none"))

        self.assertTrue(inventory[inventory.path2id("foo/bla")].executable)

    def test_symlink(self):
        os.symlink('foo/bla', 'dc/bar')
        self.client_add('dc/bar')
        self.client_commit("dc", "My Message")
        
        inventory = self.repos.get_inventory(
                self.repos.generate_revision_id(2, "", "none"))

        self.assertEqual('symlink', inventory[inventory.path2id("bar")].kind)
        self.assertEqual('foo/bla', 
                inventory[inventory.path2id("bar")].symlink_target)

    def test_not_executable(self):
        self.assertFalse(self.inventory[
            self.inventory.path2id("foo/bla")].executable)


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
        self.assertEqual("foobar%2F", escape_svn_path("foobar/"))

    def test_escape_svn_path_special_char(self):
        self.assertEqual("foobar%8A", escape_svn_path("foobar\x8a"))

    def test_unescape_svn_path_slash(self):
        self.assertEqual("foobar/", unescape_svn_path("foobar%2F"))

    def test_unescape_svn_path_none(self):
        self.assertEqual("foobar", unescape_svn_path("foobar"))

    def test_unescape_svn_path_percent(self):
        self.assertEqual("foobar%b", unescape_svn_path("foobar%25b"))

    def test_escape_svn_path_nordic(self):
        self.assertEqual("foobar%C3%A6", escape_svn_path(u"foobar\xe6"))


class SvnRepositoryFormatTests(TestCase):
    def setUp(self):
        self.format = SvnRepositoryFormat()

    def test_initialize(self):
        self.assertRaises(UninitializableFormat, self.format.initialize, None)

    def test_get_format_description(self):
        self.assertEqual("Subversion Repository", 
                         self.format.get_format_description())

    def test_conversion_target_self(self):
        self.assertTrue(self.format.check_conversion_target(self.format))

    def test_conversion_target_incompatible(self):
        self.assertFalse(self.format.check_conversion_target(
              format_registry.make_bzrdir('weave').repository_format))

    def test_conversion_target_compatible(self):
        self.assertTrue(self.format.check_conversion_target(
          format_registry.make_bzrdir('dirstate-with-subtree').repository_format))


class MetadataMarshallerTests(TestCase):
    def test_generate_revision_metadata_none(self):
        self.assertEquals("", 
                generate_revision_metadata(None, None, None, None))

    def test_generate_revision_metadata_committer(self):
        self.assertEquals("committer: bla\n", 
                generate_revision_metadata(None, None, "bla", None))

    def test_generate_revision_metadata_timestamp(self):
        self.assertEquals("timestamp: 2005-06-30 17:38:52.350850105 +0000\n", 
                generate_revision_metadata(1120153132.350850105, 0, 
                    None, None))
            
    def test_generate_revision_metadata_properties(self):
        self.assertEquals("properties: \n" + 
                "\tpropbla: bloe\n" +
                "\tpropfoo: bla\n",
                generate_revision_metadata(None, None,
                    None, {"propbla": "bloe", "propfoo": "bla"}))

    def test_parse_revision_metadata_empty(self):
        parse_revision_metadata("", None)

    def test_parse_revision_metadata_committer(self):
        rev = Revision('someid')
        parse_revision_metadata("committer: somebody\n", rev)
        self.assertEquals("somebody", rev.committer)

    def test_parse_revision_metadata_timestamp(self):
        rev = Revision('someid')
        parse_revision_metadata("timestamp: 2005-06-30 12:38:52.350850105 -0500\n", rev)
        self.assertEquals(1120153132.3508501, rev.timestamp)
        self.assertEquals(-18000, rev.timezone)

    def test_parse_revision_metadata_timestamp_day(self):
        rev = Revision('someid')
        parse_revision_metadata("timestamp: Thu 2005-06-30 12:38:52.350850105 -0500\n", rev)
        self.assertEquals(1120153132.3508501, rev.timestamp)
        self.assertEquals(-18000, rev.timezone)

    def test_parse_revision_metadata_properties(self):
        rev = Revision('someid')
        parse_revision_metadata("properties: \n" + 
                                "\tfoo: bar\n" + 
                                "\tha: ha\n", rev)
        self.assertEquals({"foo": "bar", "ha": "ha"}, rev.properties)

    def test_parse_revision_metadata_no_colon(self):
        rev = Revision('someid')
        self.assertRaises(InvalidPropertyValue, 
                lambda: parse_revision_metadata("bla", rev))

    def test_parse_revision_metadata_invalid_name(self):
        rev = Revision('someid')
        self.assertRaises(InvalidPropertyValue, 
                lambda: parse_revision_metadata("bla: b", rev))

    def test_parse_revid_property(self):
        self.assertEquals((1, "bloe"), parse_revid_property("1 bloe"))

    def test_parse_revid_property_space(self):
        self.assertEquals((42, "bloe bla"), parse_revid_property("42 bloe bla"))

    def test_parse_revid_property_invalid(self):
        self.assertRaises(InvalidPropertyValue, 
                lambda: parse_revid_property("blabla"))

    def test_parse_revid_property_empty_revid(self):
        self.assertRaises(InvalidPropertyValue, 
                lambda: parse_revid_property("2 "))



