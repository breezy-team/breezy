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

"""Subversion transport tests."""

from tests import TestCaseWithSubversionRepository
from bzrlib.errors import NotBranchError, NoSuchFile, FileExists
from transport import SvnRaTransport, bzr_to_svn_url
from unittest import TestCase

import os

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

    def test_reparent(self):
        repos_url = self.make_client('d', 'dc')
        t = SvnRaTransport(repos_url)
        t.mkdir("foo")
        t.reparent("%s/foo" % repos_url)
        self.assertEqual("%s/foo" % repos_url, t.base)

    def test_listable(self):
        repos_url = self.make_client('d', 'dc')
        t = SvnRaTransport(repos_url)
        self.assertTrue(t.listable())

    def test_get_dir_rev(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bar': 'Data'})
        self.client_add("dc/foo")
        self.client_commit("dc", "MSG")
        self.client_delete("dc/foo")
        self.client_commit("dc", "MSG2")
        t = SvnRaTransport(repos_url)
        lists = t.get_dir("foo", 1, 0)
        self.assertTrue("bar" in lists[0])

    def test_list_dir(self):
        repos_url = self.make_client('d', 'dc')
        t = SvnRaTransport(repos_url)
        self.assertEqual([], t.list_dir("."))
        t.mkdir("foo")
        self.assertEqual(["foo"], t.list_dir("."))
        self.assertEqual([], t.list_dir("foo"))
        t.mkdir("foo/bar")
        self.assertEqual(["bar"], t.list_dir("foo"))

    def test_list_dir_file(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({"dc/file": "data"})
        self.client_add("dc/file")
        self.client_commit("dc", "Bla")

        t = SvnRaTransport(repos_url)
        self.assertEqual(["file"], t.list_dir("."))
        self.assertRaises(NoSuchFile, t.list_dir, "file")

    def test_clone(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({"dc/dir": None, "dc/bl": "data"})
        self.client_add("dc/dir")
        self.client_add("dc/bl")
        self.client_commit("dc", "Bla")

        t = SvnRaTransport(repos_url)
        self.assertEqual("%s/dir" % repos_url, t.clone('dir').base)

    def test_clone_none(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({"dc/dir": None, "dc/bl": "data"})
        self.client_add("dc/dir")
        self.client_add("dc/bl")
        self.client_commit("dc", "Bla")

        t = SvnRaTransport(repos_url)
        tt = t.clone()
        self.assertEqual(tt.base, t.base)
        tt.reparent(os.path.join(t.base, "dir"))
        self.assertNotEqual(tt.base, t.base)

    def test_mkdir(self):
        repos_url = self.make_client('d', 'dc')
        t = SvnRaTransport(repos_url)
        t.mkdir("bla")
        self.client_update("dc")
        self.assertTrue(os.path.isdir("dc/bla"))
        t.mkdir("bla/subdir")
        self.client_update("dc")
        self.assertTrue(os.path.isdir("dc/bla/subdir"))

    def test_has_dot(self):
        t = SvnRaTransport(self.make_client('d', 'dc'))
        self.assertEqual(False, t.has("."))

    def test_has_nonexistent(self):
        t = SvnRaTransport(self.make_client('d', 'dc'))
        self.assertEqual(False, t.has("bar"))

    def test_mkdir_missing_parent(self):
        repos_url = self.make_client('d', 'dc')
        t = SvnRaTransport(repos_url)
        self.assertRaises(NoSuchFile, t.mkdir, "bla/subdir")
        self.client_update("dc")
        self.assertFalse(os.path.isdir("dc/bla/subdir"))

    def test_mkdir_twice(self):
        repos_url = self.make_client('d', 'dc')
        t = SvnRaTransport(repos_url)
        t.mkdir("bla")
        self.assertRaises(FileExists, t.mkdir, "bla")

    def test_clone2(self):
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
        root = t.get_repos_root()
        self.assertEqual(repos_url, root)

    def test_local_abspath(self):
        repos_url = self.make_client('d', 'dc')
        t = SvnRaTransport("%s" % repos_url)
        self.assertEquals(os.path.join(self.test_dir, "d"), t.local_abspath('.'))
 

class UrlConversionTest(TestCase):
    def test_bzr_to_svn_url(self):
        self.assertEqual("svn://host/location", 
                         bzr_to_svn_url("svn://host/location"))
        self.assertEqual("svn+ssh://host/location", 
                         bzr_to_svn_url("svn+ssh://host/location"))
        self.assertEqual("http://host/location", 
                         bzr_to_svn_url("http://host/location"))
        self.assertEqual("http://host/location", 
                         bzr_to_svn_url("svn+http://host/location"))
