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

from bzrlib.branch import Branch, BranchReferenceFormat
from bzrlib.bzrdir import BzrDir, BzrDirFormat
from bzrlib.errors import DivergedBranches
from bzrlib.inventory import Inventory
from bzrlib.workingtree import WorkingTree

import os
import format
import checkout
import svn.core
from repository import MAPPING_VERSION
from tests import TestCaseWithSubversionRepository

class TestNativeCommit(TestCaseWithSubversionRepository):
    def test_simple_commit(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        wt = WorkingTree.open("dc")
        self.assertEqual(
            "svn-v%d:1@%s-" % (MAPPING_VERSION, wt.branch.repository.uuid), 
                         wt.commit(message="data"))
        self.client_update("dc")
        self.assertEqual(
            "svn-v%d:1@%s-" % (MAPPING_VERSION, wt.branch.repository.uuid), 
                         wt.branch.last_revision())
        wt = WorkingTree.open("dc")
        new_inventory = wt.branch.repository.get_inventory(
                            wt.branch.last_revision())
        self.assertTrue(new_inventory.has_filename("foo"))
        self.assertTrue(new_inventory.has_filename("foo/bla"))

    def test_commit_message(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        wt = WorkingTree.open("dc")
        self.assertEqual(
            "svn-v%d:1@%s-" % (MAPPING_VERSION, wt.branch.repository.uuid), 
                         wt.commit(message="data"))
        self.assertEqual(
                "svn-v%d:1@%s-" % (MAPPING_VERSION, wt.branch.repository.uuid), 
                         wt.branch.last_revision())
        new_revision = wt.branch.repository.get_revision(
                            wt.branch.last_revision())
        self.assertEqual(wt.branch.last_revision(), new_revision.revision_id)
        self.assertEqual("data", new_revision.message)

    def test_commit_update(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        wt = WorkingTree.open("dc")
        wt.set_pending_merges(["some-ghost-revision"])
        wt.commit(message="data")
        self.assertEqual(
                'svn-v%d:1@%s-' % (MAPPING_VERSION, wt.branch.repository.uuid), 
                wt.branch.last_revision())

    def test_commit_parents(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        wt = WorkingTree.open("dc")
        wt.set_pending_merges(["some-ghost-revision"])
        wt.commit(message="data")
        self.assertEqual(["some-ghost-revision"],
                         wt.branch.repository.revision_parents(
                             wt.branch.last_revision()))
        self.assertEqual("some-ghost-revision\n", 
                self.client_get_prop(repos_url, "bzr:merge", 1))

class TestCommitFromBazaar(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestCommitFromBazaar, self).setUp()
        self.repos_url = self.make_repository('d')
        source = BzrDir.open("svn+"+self.repos_url)
        os.mkdir('dc')
        self.checkout = BzrDirFormat.get_default_format().initialize('dc')
        BranchReferenceFormat().initialize(self.checkout, source.open_branch())

    def test_simple_commit(self):
        wt = self.checkout.create_workingtree()
        self.build_tree({'dc/bla': "data"})
        wt.add('bla')
        wt.commit(message='commit from Bazaar')
        self.assertNotEqual(None, wt.branch.last_revision())

    def test_commit_executable(self):
        wt = self.checkout.create_workingtree()
        self.build_tree({'dc/bla': "data"})
        wt.add('bla')
        os.chmod(os.path.join(self.test_dir, 'dc', 'bla'), 0755)
        wt.commit(message='commit from Bazaar')

        inv = wt.branch.repository.get_inventory(wt.branch.last_revision())
        self.assertTrue(inv[inv.path2id("bla")].executable)

    def test_commit_symlink(self):
        wt = self.checkout.create_workingtree()
        self.build_tree({'dc/bla': "data"})
        wt.add('bla')
        os.symlink('bla', 'dc/foo')
        wt.add('foo')
        wt.commit(message='commit from Bazaar')

        inv = wt.branch.repository.get_inventory(wt.branch.last_revision())
        self.assertEqual('symlink', inv[inv.path2id("foo")].kind)
        self.assertEqual('bla', inv[inv.path2id("foo")].symlink_target)

    def test_commit_remove_executable(self):
        wt = self.checkout.create_workingtree()
        self.build_tree({'dc/bla': "data"})
        wt.add('bla')
        os.chmod(os.path.join(self.test_dir, 'dc', 'bla'), 0755)
        wt.commit(message='commit from Bazaar')

        os.chmod(os.path.join(self.test_dir, 'dc', 'bla'), 0644)
        wt.commit(message='remove executable')

        inv = wt.branch.repository.get_inventory(wt.branch.last_revision())
        self.assertFalse(inv[inv.path2id("bla")].executable)

    def test_commit_parents(self):
        wt = self.checkout.create_workingtree()
        self.build_tree({'dc/foo/bla': "data", 'dc/bla': "otherdata"})
        wt.add('bla')
        wt.commit(message="data")
        wt.add('foo')
        wt.add('foo/bla')
        self.assertTrue(wt.inventory.has_filename("bla"))
        self.assertTrue(wt.inventory.has_filename("foo/bla"))
        wt.set_pending_merges(["some-ghost-revision"])
        wt.commit(message="data")
        self.assertEqual([
            "svn-v%d:1@%s-" % (MAPPING_VERSION, wt.branch.repository.uuid), 
            "some-ghost-revision"],
            wt.branch.repository.revision_parents(wt.branch.last_revision()))
        self.assertEqual("some-ghost-revision\n", 
                self.client_get_prop(self.repos_url, "bzr:merge", 2))

    def test_commit_fileids(self):
        wt = self.checkout.create_workingtree()
        self.build_tree({'dc/file': 'data'})
        wt.add('file')
        wt.commit(message="Commit from Bzr")
        self.assertEqual("\t%s\nfile\t%s\n" % (wt.inventory.root.file_id, wt.inventory.path2id("file")), 
                self.client_get_prop(self.repos_url, "bzr:file-ids", 1))

    def test_commit_fileids_added(self):
    
        rev = svn.core.svn_opt_revision_t()
        rev.kind = svn.core.svn_opt_revision_head

        svn.client.checkout2(self.repos_url, "db", 
                rev, rev, True, False, self.client_ctx)

        self.build_tree({'dc/file1': 'data', 'db/file2': "otherdata"})
        self.client_add("db/file2")
        self.client_commit("db", "amesg")
        branch = Branch.open(self.repos_url)
        inv = branch.repository.get_inventory(branch.last_revision())
        wt = self.checkout.create_workingtree()
        self.assertEqual(wt.inventory.root.file_id, inv.root.file_id)
        wt.add('file1')
        wt.commit(message="Commit from Bzr")
        self.assertEqual("file1\t%s\n" % wt.inventory.path2id("file1"), 
                self.client_get_prop(self.repos_url, "bzr:file-ids", 2))

    def test_commit_branchnick(self):
        wt = self.checkout.create_workingtree()
        self.build_tree({'dc/foo/bla': "data", 'dc/bla': "otherdata"})
        wt.add('bla')
        wt.commit(message="data")
        wt.add('foo')
        wt.add('foo/bla')
        wt.commit(message="data", revprops={"branch-nick": "mybranch"})
        self.assertEqual("mybranch", 
                self.client_get_prop(self.repos_url, "bzr:revprop:branch-nick", 2))

class TestPush(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestPush, self).setUp()
        self.repos_url = self.make_client('d', 'sc')

        self.build_tree({'sc/foo/bla': "data"})
        self.client_add("sc/foo")
        self.client_commit("sc", "foo")

        self.olddir = BzrDir.open("sc")
        os.mkdir("dc")
        self.newdir = self.olddir.sprout("dc")

    def test_empty(self):
        self.assertEqual(0, self.olddir.open_branch().pull(
                                self.newdir.open_branch()))

    def test_child(self):
        self.build_tree({'sc/foo/bar': "data"})
        self.client_add("sc/foo/bar")
        self.client_commit("sc", "second message")

        self.assertEqual(0, self.olddir.open_branch().pull(
                                self.newdir.open_branch()))

    def test_diverged(self):
        self.build_tree({'sc/foo/bar': "data"})
        self.client_add("sc/foo/bar")
        self.client_commit("sc", "second message")

        olddir = BzrDir.open("sc")

        self.build_tree({'dc/file': 'data'})
        wt = self.newdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.assertRaises(DivergedBranches, 
                          olddir.open_branch().pull,
                          self.newdir.open_branch())

    def test_change(self):
        self.build_tree({'dc/foo/bla': 'other data'})
        wt = self.newdir.open_workingtree()
        wt.commit(message="Commit from Bzr")

        self.olddir.open_branch().pull(self.newdir.open_branch())

        repos = self.olddir.find_repository()
        inv = repos.get_inventory("svn-v%d:2@%s-" % (MAPPING_VERSION, repos.uuid))
        self.assertEqual("svn-v%d:2@%s-" % (MAPPING_VERSION, repos.uuid), 
                         inv[inv.path2id('foo/bla')].revision)
        self.assertTrue(wt.branch.last_revision() in 
         repos.revision_parents("svn-v%d:2@%s-" % (MAPPING_VERSION, repos.uuid)))
        self.assertEqual("svn-v%d:2@%s-" % (MAPPING_VERSION, repos.uuid), 
                        self.olddir.open_branch().last_revision())
        self.assertEqual("other data", 
            repos.revision_tree("svn-v%d:2@%s-" % (MAPPING_VERSION, repos.uuid)).get_file_text( inv.path2id("foo/bla")))

    def test_simple(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.newdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.olddir.open_branch().pull(self.newdir.open_branch())

        repos = self.olddir.find_repository()
        inv = repos.get_inventory("svn-v%d:2@%s-" % (MAPPING_VERSION, repos.uuid))
        self.assertTrue(inv.has_filename('file'))
        self.assertTrue(wt.branch.last_revision() in 
            repos.revision_parents(
                "svn-v%d:2@%s-" % (MAPPING_VERSION, repos.uuid)))
        self.assertEqual("svn-v%d:2@%s-" % (MAPPING_VERSION, repos.uuid), 
                        self.olddir.open_branch().last_revision())

    def test_pull_after_push(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.newdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.olddir.open_branch().pull(self.newdir.open_branch())

        repos = self.olddir.find_repository()
        inv = repos.get_inventory("svn-v%d:2@%s-" % (MAPPING_VERSION, repos.uuid))
        self.assertTrue(inv.has_filename('file'))
        self.assertTrue(wt.branch.last_revision() in 
                         repos.revision_parents("svn-v%d:2@%s-" % (MAPPING_VERSION, repos.uuid)))
        self.assertEqual("svn-v%d:2@%s-" % (MAPPING_VERSION, repos.uuid), 
                        self.olddir.open_branch().last_revision())

        self.newdir.open_branch().pull(self.olddir.open_branch())

        self.assertEqual("svn-v%d:2@%s-" % (MAPPING_VERSION, repos.uuid), 
                        self.newdir.open_branch().last_revision())

    def test_message(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.newdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.olddir.open_branch().pull(self.newdir.open_branch())

        repos = self.olddir.find_repository()
        self.assertEqual("Commit from Bzr",
            repos.get_revision("svn-v%d:2@%s-" % (MAPPING_VERSION, repos.uuid)).message)

    def test_multiple(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.newdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.build_tree({'dc/file': 'data2', 'dc/adir': None})
        wt.add('adir')
        wt.commit(message="Another commit from Bzr")

        self.olddir.open_branch().pull(self.newdir.open_branch())

        repos = self.olddir.find_repository()

        self.assertEqual("svn-v%d:3@%s-" % (MAPPING_VERSION, repos.uuid), 
                        self.olddir.open_branch().last_revision())

        inv = repos.get_inventory("svn-v%d:2@%s-" % (MAPPING_VERSION, repos.uuid))
        self.assertTrue(inv.has_filename('file'))
        self.assertFalse(inv.has_filename('adir'))

        inv = repos.get_inventory("svn-v%d:3@%s-" % (MAPPING_VERSION, repos.uuid))
        self.assertTrue(inv.has_filename('file'))
        self.assertTrue(inv.has_filename('adir'))

        self.assertTrue(wt.branch.last_revision() in 
             repos.get_ancestry("svn-v%d:3@%s-" % (MAPPING_VERSION, repos.uuid)))

