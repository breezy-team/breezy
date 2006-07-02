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

from tests import TestCaseWithSubversionRepository
from bzrlib.bzrdir import BzrDir
from bzrlib.errors import NotBranchError
from transport import SvnRaTransport, svn_to_bzr_url, bzr_to_svn_url
from unittest import TestCase

class SvnRaTest(TestCaseWithSubversionRepository):
    def test_open_nonexisting(self):
        self.assertRaises(NotBranchError, SvnRaTransport, "svn+nonexisting://foo/bar")

    def test_create(self):
        repos_url = self.make_client('a', 'ac')
        t = SvnRaTransport("svn+%s" % repos_url)
        self.assertIsInstance(t, SvnRaTransport)
        self.assertEqual(t.base, "svn+%s" % repos_url)

    def test_create_direct(self):
        repos_url = self.make_client('a', 'ac')
        t = SvnRaTransport(repos_url)
        self.assertIsInstance(t, SvnRaTransport)
        self.assertEqual(t.base, repos_url)

    def test_clone(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({"dc/dir": None, "dc/bl": "data"})
        self.client_add("dc/dir")
        self.client_add("dc/bl")
        self.client_commit("dc", "Bla")

        t = SvnRaTransport(repos_url)
        self.assertEqual("%s/dir" % repos_url, t.clone('dir').base)

    def test_clone(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({"dc/dir": None, "dc/bl": "data"})
        self.client_add("dc/dir")
        self.client_add("dc/bl")
        self.client_commit("dc", "Bla")

        t = SvnRaTransport(repos_url)
        self.assertEqual("%s/dir" % repos_url, t.clone('dir').base)
        
    def test_get_root(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({"dc/dir": None, "dc/bl": "data"})
        self.client_add("dc/dir")
        self.client_add("dc/bl")
        self.client_commit("dc", "Bla")

        t = SvnRaTransport("%s/dir" % repos_url)
        root = t.get_root()
        self.assertEqual(repos_url, root.base)
 

class UrlConversionTest(TestCase):
    def test_svn_to_bzr_url(self):
        self.assertEqual("svn://host/location", 
                         svn_to_bzr_url("svn://host/location"))
        self.assertEqual("svn+http://host/location", 
                         svn_to_bzr_url("http://host/location"))
        self.assertEqual("svn+http://host/location", 
                         svn_to_bzr_url("svn+http://host/location"))

    def test_bzr_to_svn_url(self):
        self.assertEqual("svn://host/location", 
                         bzr_to_svn_url("svn://host/location"))
        self.assertEqual("svn+ssh://host/location", 
                         bzr_to_svn_url("svn+ssh://host/location"))
        self.assertEqual("http://host/location", 
                         bzr_to_svn_url("http://host/location"))
        self.assertEqual("http://host/location", 
                         bzr_to_svn_url("svn+http://host/location"))
