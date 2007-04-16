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

class TestPush(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestPush, self).setUp()
        self.repos_url = self.make_client('d', 'sc')

        self.build_tree({'sc/foo/bla': "data"})
        self.client_add("sc/foo")
        self.client_commit("sc", "foo")

        self.svndir = BzrDir.open("sc")
        os.mkdir("dc")
        self.bzrdir = self.svndir.sprout("dc")

    def test_empty(self):
        svnbranch = self.svndir.open_branch()
        bzrbranch = self.bzrdir.open_branch()
        result = svnbranch.pull(bzrbranch)
        self.assertEqual(0, result.new_revno - result.old_revno)
        self.assertEqual(svnbranch.revision_history(),
                         bzrbranch.revision_history())

    def test_child(self):
        self.build_tree({'sc/foo/bar': "data"})
        self.client_add("sc/foo/bar")
        self.client_commit("sc", "second message")

        svnbranch = self.svndir.open_branch()
        bzrbranch = self.bzrdir.open_branch()
        result = svnbranch.pull(bzrbranch)
        self.assertEqual(0, result.new_revno - result.old_revno)

    def test_diverged(self):
        self.build_tree({'sc/foo/bar': "data"})
        self.client_add("sc/foo/bar")
        self.client_commit("sc", "second message")

        svndir = BzrDir.open("sc")

        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.assertRaises(DivergedBranches, 
                          svndir.open_branch().pull,
                          self.bzrdir.open_branch())

    def test_change(self):
        self.build_tree({'dc/foo/bla': 'other data'})
        wt = self.bzrdir.open_workingtree()
        wt.commit(message="Commit from Bzr")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        repos = self.svndir.find_repository()
        inv = repos.get_inventory(repos.generate_revision_id(2, ""))
        self.assertEqual(repos.generate_revision_id(2, ""),
                         inv[inv.path2id('foo/bla')].revision)
        self.assertTrue(wt.branch.last_revision() in 
          repos.revision_parents(repos.generate_revision_id(2, "")))
        self.assertEqual(repos.generate_revision_id(2, ""),
                        self.svndir.open_branch().last_revision())
        self.assertEqual("other data", 
            repos.revision_tree(repos.generate_revision_id(2, "")).get_file_text( inv.path2id("foo/bla")))

    def test_simple(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        repos = self.svndir.find_repository()
        inv = repos.get_inventory(repos.generate_revision_id(2, ""))
        self.assertTrue(inv.has_filename('file'))
        self.assertTrue(wt.branch.last_revision() in 
            repos.revision_parents(
                repos.generate_revision_id(2, "")))
        self.assertEqual(repos.generate_revision_id(2, ""),
                        self.svndir.open_branch().last_revision())

    def test_pull_after_push(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        repos = self.svndir.find_repository()
        inv = repos.get_inventory(repos.generate_revision_id(2, ""))
        self.assertTrue(inv.has_filename('file'))
        self.assertTrue(wt.branch.last_revision() in 
                         repos.revision_parents(repos.generate_revision_id(2, "")))
        self.assertEqual(repos.generate_revision_id(2, ""),
                        self.svndir.open_branch().last_revision())

        self.bzrdir.open_branch().pull(self.svndir.open_branch())

        self.assertEqual(repos.generate_revision_id(2, ""),
                        self.bzrdir.open_branch().last_revision())

    def test_message(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        repos = self.svndir.find_repository()
        self.assertEqual("Commit from Bzr",
            repos.get_revision(repos.generate_revision_id(2, "")).message)

    def test_multiple(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.build_tree({'dc/file': 'data2', 'dc/adir': None})
        wt.add('adir')
        wt.commit(message="Another commit from Bzr")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        repos = self.svndir.find_repository()

        self.assertEqual(repos.generate_revision_id(3, ""), 
                        self.svndir.open_branch().last_revision())

        inv = repos.get_inventory(repos.generate_revision_id(2, ""))
        self.assertTrue(inv.has_filename('file'))
        self.assertFalse(inv.has_filename('adir'))

        inv = repos.get_inventory(repos.generate_revision_id(3, ""))
        self.assertTrue(inv.has_filename('file'))
        self.assertTrue(inv.has_filename('adir'))

        self.assertEqual(self.svndir.open_branch().revision_history(),
                         self.bzrdir.open_branch().revision_history())
        self.assertTrue(wt.branch.last_revision() in 
             repos.get_ancestry(repos.generate_revision_id(3, "")))

