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
from bzrlib.trace import mutter
from bzrlib.tests import TestSkipped

import format
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

        inv1 = repository.get_inventory("svn-v1:1@%s-" % repository.uuid)
        inv2 = repository.get_inventory("svn-v1:2@%s-" % repository.uuid)
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
        repository = bzrdir.open_repository()

        inv1 = repository.get_inventory("svn-v1:1@%s-" % repository.uuid)
        inv2 = repository.get_inventory("svn-v1:2@%s-" % repository.uuid)
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
        repository = bzrdir.open_repository()

        inv1 = repository.get_inventory("svn-v1:1@%s-" % repository.uuid)
        inv2 = repository.get_inventory("svn-v1:2@%s-" % repository.uuid)
        self.assertNotEqual(None, inv1.path2id("foo"))
        self.assertIs(None, inv2.path2id("foo"))
