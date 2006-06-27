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

from bzrlib.bzrdir import BzrDir
from bzrlib.errors import NoSuchRevision
from bzrlib.inventory import Inventory
from bzrlib.repository import Repository
from bzrlib.tests.repository_implementations.test_repository import TestCaseWithRepository
from bzrlib.transport.local import LocalTransport

import svn
import format
from tests import TestCaseWithSubversionRepository

class TestSubversionRepositoryWorks(TestCaseWithSubversionRepository):
    def test_format(self):
        """ Test repository format is correct """
        bzrdir = self.make_local_bzrdir('a', 'ac')
        self.assertEqual(bzrdir._format.get_format_string(), \
                "Subversion Local Checkout")
        
        self.assertEqual(bzrdir._format.get_format_description(), \
                "Subversion Local Checkout")

    def test_url(self):
        """ Test repository URL is kept """
        bzrdir = self.make_local_bzrdir('b', 'bc')
        self.assertTrue(isinstance(bzrdir, BzrDir))

    def test_uuid(self):
        """ Test UUID is retrieved correctly """
        bzrdir = self.make_local_bzrdir('c', 'cc')
        self.assertTrue(isinstance(bzrdir, BzrDir))
        repository = bzrdir.open_repository()
        fs = self.open_fs('c')
        self.assertEqual(svn.fs.get_uuid(fs), repository.uuid)

    def test_has_revision(self):
        bzrdir = self.make_client_and_bzrdir('d', 'dc')
        repository = bzrdir.open_repository()
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.assertTrue(repository.has_revision("svn:1@%s-" % repository.uuid))
        self.assertFalse(repository.has_revision("some-other-revision"))

    def test_revision_parents(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo': "data2"})
        self.client_commit("dc", "Second Message")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual([],
                repository.revision_parents("svn:1@%s-" % repository.uuid))
        self.assertEqual(["svn:1@%s-" % repository.uuid], 
                repository.revision_parents("svn:2@%s-" % repository.uuid))

    def test_revision_ghost_parents(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo': "data2"})
        self.client_commit("dc", "Second Message")
        self.client_set_revprops(repos_url, 2, "bzr:parents", "ghostparent")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual([],
                repository.revision_parents("svn:1@%s-" % repository.uuid))
        self.assertEqual(["svn:1@%s-" % repository.uuid, "ghostparent"], 
                repository.revision_parents("svn:2@%s-" % repository.uuid))
 
    
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
        rev = repository.get_revision("svn:2@%s-" % repository.uuid)
        self.assertEqual(["svn:1@%s-" % repository.uuid],
                rev.parent_ids)
        self.assertEqual(rev.revision_id,"svn:2@%s-" % repository.uuid)
        self.assertEqual(author, rev.committer)

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
        self.assertEqual([None, "svn:1@%s-" % repository.uuid, "svn:2@%s-" % repository.uuid],
                repository.get_ancestry("svn:3@%s-" % repository.uuid))
        self.assertEqual([None, "svn:1@%s-" % repository.uuid], 
                repository.get_ancestry("svn:2@%s-" % repository.uuid))
        self.assertEqual([None],
                repository.get_ancestry("svn:1@%s-" % repository.uuid))
        self.assertEqual([None], repository.get_ancestry(None))

    def test_get_inventory(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.assertRaises(NoSuchRevision, repository.get_inventory, "nonexisting")
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo': "data2", "dc/bar/foo": "data3"})
        self.client_add("dc/bar")
        self.client_commit("dc", "Second Message")
        self.build_tree({'dc/foo': "data3"})
        self.client_commit("dc", "Third Message")
        repository = Repository.open("svn+%s" % repos_url)
        inv = repository.get_inventory("svn:1@%s-" % repository.uuid)
        self.assertIsInstance(inv, Inventory)
        self.assertIsInstance(inv.path2id("foo"), basestring)
        inv = repository.get_inventory("svn:2@%s-" % repository.uuid)
        self.assertIsInstance(inv, Inventory)
        self.assertIsInstance(inv.path2id("foo"), basestring)
        self.assertIsInstance(inv.path2id("bar"), basestring)
        self.assertIsInstance(inv.path2id("bar/foo"), basestring)

    def test_generate_revision_id(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.assertEqual("svn:0@%s-bla/bloe" % repository.uuid, 
            repository.generate_revision_id(0, "bla/bloe"))

    def test_parse_revision_id(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.assertRaises(NoSuchRevision, repository.parse_revision_id, 
            "nonexisting")
        self.assertEqual(("bloe", 0), 
            repository.parse_revision_id("svn:0@%s-bloe" % repository.uuid))
        
    def test_check(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        repository = Repository.open("svn+%s" % repos_url)
        repository.check([
            "svn:0@%s-" % repository.uuid, 
            "svn:1@%s-" % repository.uuid])

    def test_get_file(self):
        repos_url = self.make_client('d', 'dc')
        repository = Repository.open("svn+%s" % repos_url)
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo': "data2", "dc/bar/foo": "data3"})
        self.client_add("dc/bar")
        self.client_commit("dc", "Second Message")
        self.build_tree({'dc/foo': "data3"})
        self.client_commit("dc", "Third Message")
        stream = repository._cache_get_file("foo", 1)[1]
        stream.seek(0)
        self.assertEqual("data", stream.read())
        stream = repository._cache_get_file("foo", 2)[1]
        stream.seek(0)
        self.assertEqual("data2", stream.read())
        self.assertEqual(repository.uuid, 
                repository._cache_get_file("foo", 1)[0]['svn:entry:uuid'])
        self.assertEqual('1', 
            repository._cache_get_file("foo", 1)[0]['svn:entry:committed-rev'])
        self.assertTrue(repository._cache_get_file("foo", 1)[0].has_key(
            'svn:entry:last-author'))
        self.assertTrue(repository._cache_get_file("foo", 1)[0].has_key(
            'svn:entry:committed-date'))

    def test_get_dir(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo/blo': "data2", "dc/bar/foo": "data3"})
        self.client_add("dc/foo/blo")
        self.client_add("dc/bar")
        self.client_commit("dc", "Second Message")
        repository = Repository.open("svn+%s" % repos_url)
        (_, dirents) = repository._cache_get_dir("foo", 1)
        self.assertTrue(dirents.has_key("bla"))
        self.assertFalse(dirents.has_key("foo"))
        self.assertRaises(NoSuchRevision, repository._cache_get_dir, "bar", 4)
        (_, dirents) = repository._cache_get_dir("foo", 2)
        self.assertTrue(dirents.has_key("bla"))
        self.assertTrue(dirents.has_key("blo"))
        self.assertFalse(dirents.has_key("foox"))
        (_, dirents) = repository._cache_get_dir("bar", 2)
        self.assertTrue(dirents.has_key("foo"))
        self.assertFalse(dirents.has_key("foox"))

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
                "svn:2@%s-" % repository.uuid)

        self.assertTrue(repository.has_revision("svn:2@%s-" % repository.uuid))
        self.assertTrue(repository.has_revision("svn:1@%s-" % repository.uuid))
        self.assertTrue(repository.has_revision("svn:0@%s-" % repository.uuid))
        self.assertFalse(repository.has_revision("svn:4@%s-" % repository.uuid))

    def test_is_shared(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        repository = Repository.open("svn+%s" % repos_url)
        self.assertTrue(repository.is_shared())

    def test_fetch_local(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo/blo': "data2", "dc/bar/foo": "data3", 'dc/foo/bla': "data"})
        self.client_add("dc/foo/blo")
        self.client_add("dc/bar")
        self.client_commit("dc", "Second Message")
        oldrepos = Repository.open("dc")
        dir = BzrDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        self.assertTrue(newrepos.has_revision("svn:1@%s-" % oldrepos.uuid))
        self.assertTrue(newrepos.has_revision("svn:2@%s-" % oldrepos.uuid))
        tree = newrepos.revision_tree("svn:2@%s-" % oldrepos.uuid)
        self.assertTrue(tree.has_filename("foo/bla"))
        self.assertTrue(tree.has_filename("foo"))
        self.assertEqual("data", tree.get_file_by_path("foo/bla").read())


class TestSvnRevisionTree(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestSvnRevisionTree, self).setUp()
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        self.repos = Repository.open("dc")
        self.inventory = self.repos.get_inventory("svn:1@%s-" % self.repos.uuid)
        self.tree = self.repos.revision_tree("svn:1@%s-" % self.repos.uuid)

    def test_inventory(self):
        self.assertIsInstance(self.tree.inventory, Inventory)
        self.assertEqual(self.inventory, self.tree.inventory)

    def test_get_parent_ids(self):
        self.assertEqual([], self.tree.get_parent_ids())

    def test_get_revision_id(self):
        self.assertEqual("svn:1@%s-" % self.repos.uuid, 
                         self.tree.get_revision_id())

    def test_get_file_lines(self):
        self.assertEqual(["data"], 
                self.tree.get_file_lines(self.inventory.path2id("foo/bla")))
