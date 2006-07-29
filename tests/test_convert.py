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
from bzrlib.delta import compare_trees
from bzrlib.errors import NotBranchError
from bzrlib.repository import Repository

import os
from convert import convert_repository
from scheme import TrunkBranchingScheme
from tests import TestCaseWithSubversionRepository

class TestConversion(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestConversion, self).setUp()
        self.repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/trunk/file': 'data', 'dc/branches/abranch/anotherfile': 'data2'})
        self.client_add("dc/trunk")
        self.client_add("dc/branches")
        self.client_commit("dc", "create repos")
        self.build_tree({'dc/trunk/file': 'otherdata'})
        self.client_commit("dc", "change")

    def test_shared_import(self):
        convert_repository("svn+"+self.repos_url, "e", 
                TrunkBranchingScheme(), True)

        self.assertTrue(Repository.open("e").is_shared())
    
    def test_simple(self):
        convert_repository("svn+"+self.repos_url, os.path.join(self.test_dir, "e"), TrunkBranchingScheme())
        self.assertTrue(os.path.isdir(os.path.join(self.test_dir, "e", "trunk")))
        self.assertTrue(os.path.isdir(os.path.join(self.test_dir, "e", "branches", "abranch")))

    def test_notshared_import(self):
        convert_repository("svn+"+self.repos_url, "e", TrunkBranchingScheme(), 
                           False)

        self.assertRaises(NotBranchError, Repository.open, "e")
