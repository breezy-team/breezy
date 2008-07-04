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

"""Remote access tests."""

from bzrlib import osutils
from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir, format_registry
from bzrlib.errors import (NoRepositoryPresent, NotBranchError, NotLocalUrl,
                           NoWorkingTree, AlreadyBranchError)

from bzrlib.plugins.svn import core, ra
from bzrlib.plugins.svn.format import SvnRemoteFormat
from bzrlib.plugins.svn.tests import TestCaseWithSubversionRepository
from bzrlib.plugins.svn.transport import SvnRaTransport

class TestRemoteAccess(TestCaseWithSubversionRepository):
    def test_clone(self):
        repos_url = self.make_client("d", "dc")

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("foo")
        dc.close()

        x = self.open_checkout_bzrdir("dc")
        self.assertRaises(NotImplementedError, x.clone, "dir")

    def test_break_lock(self):
        repos_url = self.make_repository("d")

        x = BzrDir.open(repos_url)
        x.break_lock()

    def test_open_workingtree(self):
        repos_url = self.make_repository("d")
        x = BzrDir.open(repos_url)
        self.assertRaises(NoWorkingTree, x.open_workingtree)

    def test_open_workingtree_recommend_arg(self):
        repos_url = self.make_repository("d")
        x = BzrDir.open(repos_url)
        self.assertRaises(NoWorkingTree, lambda: x.open_workingtree(recommend_upgrade=True))

    def test_create_workingtree(self):
        repos_url = self.make_repository("d")
        x = BzrDir.open(repos_url)
        self.assertRaises(NotLocalUrl, x.create_workingtree)

    def test_create_branch_top(self):
        repos_url = self.make_repository("d")
        x = BzrDir.open(repos_url)
        b = x.create_branch()
        self.assertEquals(repos_url, b.base)

    def test_create_branch_top_already_branch(self):
        repos_url = self.make_repository("d")

        dc = self.get_commit_editor(repos_url)
        dc.add_file("bla").modify("contents")
        dc.close()
        x = BzrDir.open(repos_url)
        self.assertRaises(AlreadyBranchError, x.create_branch)

    def test_create_branch_nested(self):
        repos_url = self.make_repository("d")
        x = BzrDir.open(repos_url+"/trunk")
        b = x.create_branch()
        self.assertEquals(repos_url+"/trunk", b.base)
        transport = SvnRaTransport(repos_url)
        self.assertEquals(core.NODE_DIR, 
                transport.check_path("trunk", 1))

    def test_bad_dir(self):
        repos_url = self.make_repository("d")

        dc = self.get_commit_editor(repos_url)
        dc.add_file("foo")
        dc.close()

        BzrDir.open(repos_url+"/foo")

    def test_create(self):
        repos_url = self.make_repository("d")
        x = BzrDir.open(repos_url)
        self.assertTrue(hasattr(x, 'svn_root_url'))

    def test_import_branch(self):
        repos_url = self.make_repository("d")
        x = BzrDir.open(repos_url+"/trunk")
        origb = BzrDir.create_standalone_workingtree("origb")
        self.build_tree({'origb/twin': 'bla', 'origb/peaks': 'bloe'})
        origb.add(["twin", "peaks"])
        origb.commit("Message")
        b = x.import_branch(source=origb.branch)
        self.assertEquals(origb.branch.revision_history(), b.revision_history())
        self.assertEquals(origb.branch.revision_history(), 
                Branch.open(repos_url+"/trunk").revision_history())

    def test_open_repos_root(self):
        repos_url = self.make_repository("d")
        x = BzrDir.open(repos_url)
        repos = x.open_repository()
        self.assertTrue(hasattr(repos, 'uuid'))

    def test_find_repos_nonroot(self):
        repos_url = self.make_repository("d")

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("trunk")
        dc.close()

        x = BzrDir.open(repos_url+"/trunk")
        repos = x.find_repository()
        self.assertTrue(hasattr(repos, 'uuid'))

    def test_find_repos_root(self):
        repos_url = self.make_repository("d")
        x = BzrDir.open(repos_url)
        repos = x.find_repository()
        self.assertTrue(hasattr(repos, 'uuid'))

    def test_open_repos_nonroot(self):
        repos_url = self.make_repository("d")

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("trunk")
        dc.close()

        x = BzrDir.open(repos_url+"/trunk")
        self.assertRaises(NoRepositoryPresent, x.open_repository)

    def test_needs_format_upgrade_other(self):
        repos_url = self.make_repository("d")
        x = BzrDir.open(repos_url+"/trunk")
        self.assertTrue(x.needs_format_conversion(format_registry.make_bzrdir("rich-root")))

    def test_needs_format_upgrade_default(self):
        repos_url = self.make_repository("d")
        x = BzrDir.open(repos_url+"/trunk")
        self.assertTrue(x.needs_format_conversion())

    def test_needs_format_upgrade_self(self):
        repos_url = self.make_repository("d")
        x = BzrDir.open(repos_url+"/trunk")
        self.assertFalse(x.needs_format_conversion(SvnRemoteFormat()))

    def test_find_repository_not_found(self):
        repos_url = self.make_client('d', 'dc')
        osutils.rmtree("d")
        self.assertRaises(NoRepositoryPresent, 
                lambda: BzrDir.open("dc").find_repository())

