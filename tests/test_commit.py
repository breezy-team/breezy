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

from bzrlib.branch import BranchReferenceFormat
from bzrlib.bzrdir import BzrDir, BzrDirMetaFormat1
from bzrlib.delta import compare_trees
from bzrlib.inventory import Inventory
from bzrlib.workingtree import WorkingTree

import os
import format
import checkout
from tests import TestCaseWithSubversionRepository

class TestNativeCommit(TestCaseWithSubversionRepository):
    def test_push(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "foo")

    def test_push_diverged(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "rev1 log")

        branch = BzrDir.create_branch_convenience("br")

        self.build_tree({'dc/foo/bla': "data2"})
        self.client_commit("dc", "rev2 log")

    def test_simple_commit(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        wt = WorkingTree.open("dc")
        self.assertEqual("svn-v1:1@%s-" % wt.branch.repository.uuid, 
                         wt.commit(message="data"))
        self.assertEqual("svn-v1:1@%s-" % wt.branch.repository.uuid, 
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
        self.assertEqual("svn-v1:1@%s-" % wt.branch.repository.uuid, 
                         wt.commit(message="data"))
        self.assertEqual("svn-v1:1@%s-" % wt.branch.repository.uuid, 
                         wt.branch.last_revision())
        new_revision = wt.branch.repository.get_revision(
                            wt.branch.last_revision())
        self.assertEqual(wt.branch.last_revision(), new_revision.revision_id)
        self.assertEqual("data", new_revision.message)

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
        self.checkout = BzrDirMetaFormat1().initialize('dc')
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
        self.build_tree({'dc/foo/bla': "data"})
        wt.add('foo')
        wt.add('foo/bla')
        wt.set_pending_merges(["some-ghost-revision"])
        wt.commit(message="data")
        self.assertEqual(["some-ghost-revision"],
                         wt.branch.repository.revision_parents(
                             wt.branch.last_revision()))
        self.assertEqual("some-ghost-revision\n", 
                self.client_get_prop(self.repos_url, "bzr:merge", 1))
