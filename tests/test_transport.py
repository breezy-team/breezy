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

"""Subversion transport tests."""

from bzrlib.errors import NotBranchError, NoSuchFile, FileExists, InvalidURL
from bzrlib import urlutils

from bzrlib.plugins.svn import core, ra
from bzrlib.plugins.svn.tests import TestCaseWithSubversionRepository
from bzrlib.plugins.svn.transport import SvnRaTransport, bzr_to_svn_url, _url_unescape_uri

import os
from unittest import TestCase

class SvnRaTest(TestCaseWithSubversionRepository):
    def test_open_nonexisting(self):
        self.assertRaises(InvalidURL, SvnRaTransport, 
                          "svn+nonexisting://foo/bar")

    def test_create(self):
        repos_url = self.make_repository('a')
        t = SvnRaTransport("svn+%s" % repos_url)
        self.assertIsInstance(t, SvnRaTransport)
        self.assertEqual(t.base, "svn+%s" % repos_url)

    def test_create_direct(self):
        repos_url = self.make_repository('a')
        t = SvnRaTransport(repos_url)
        self.assertIsInstance(t, SvnRaTransport)
        self.assertEqual(t.base, repos_url)

    def test_lock_read(self):
        repos_url = self.make_repository('a')
        t = SvnRaTransport(repos_url)
        lock = t.lock_read(".")
        lock.unlock()

    def test_lock_write(self):
        repos_url = self.make_repository('a')
        t = SvnRaTransport(repos_url)
        lock = t.lock_write(".")
        lock.unlock()

    def test_listable(self):
        repos_url = self.make_repository('a')
        t = SvnRaTransport(repos_url)
        self.assertTrue(t.listable())

    def test_get_dir_rev(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        foo = dc.add_dir("foo")
        foo.add_file("foo/bar").modify("Data")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.delete("foo")
        dc.close()

        t = SvnRaTransport(repos_url)
        lists = t.get_dir("foo", 1, 0)
        self.assertTrue("bar" in lists[0])

    def test_list_dir(self):
        repos_url = self.make_repository('a')
        t = SvnRaTransport(repos_url)
        self.assertEqual([], t.list_dir("."))
        t.mkdir("foo")
        self.assertEqual(["foo"], t.list_dir("."))
        self.assertEqual([], t.list_dir("foo"))
        t.mkdir("foo/bar")
        self.assertEqual(["bar"], t.list_dir("foo"))

    def test_list_dir_file(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.add_file("file").modify("data")
        dc.close()

        t = SvnRaTransport(repos_url)
        self.assertEqual(["file"], t.list_dir("."))
        self.assertRaises(NoSuchFile, t.list_dir, "file")

    def test_clone(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("dir")
        dc.add_file("bl").modify("data")
        dc.close()

        t = SvnRaTransport(repos_url)
        self.assertEqual("%s/dir" % repos_url, t.clone('dir').base)

    def test_clone_none(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("dir")
        dc.add_file("bl").modify("data")
        dc.close()

        t = SvnRaTransport(repos_url)
        tt = t.clone()
        self.assertEqual(tt.base, t.base)

    def test_mkdir(self):
        repos_url = self.make_repository('a')
        t = SvnRaTransport(repos_url)
        t.mkdir("bla")

        c = ra.RemoteAccess(repos_url)
        self.assertEquals(c.check_path("bla", c.get_latest_revnum()), 
                          core.NODE_DIR)
        t.mkdir("bla/subdir")
        self.assertEquals(c.check_path("bla/subdir", c.get_latest_revnum()), 
                          core.NODE_DIR)

    def test_has_dot(self):
        t = SvnRaTransport(self.make_repository('a'))
        self.assertEqual(False, t.has("."))

    def test_has_nonexistent(self):
        t = SvnRaTransport(self.make_repository('a'))
        self.assertEqual(False, t.has("bar"))

    def test_mkdir_missing_parent(self):
        repos_url = self.make_repository('a')
        t = SvnRaTransport(repos_url)
        self.assertRaises(NoSuchFile, t.mkdir, "bla/subdir")
        c = ra.RemoteAccess(repos_url)
        self.assertEquals(c.check_path("bla/subdir", c.get_latest_revnum()), 
                          core.NODE_NONE)

    def test_mkdir_twice(self):
        repos_url = self.make_repository('a')
        t = SvnRaTransport(repos_url)
        t.mkdir("bla")
        self.assertRaises(FileExists, t.mkdir, "bla")

    def test_clone2(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("dir")
        dc.add_file("bl").modify("data")
        dc.close()

        t = SvnRaTransport(repos_url)
        self.assertEqual("%s/dir" % repos_url, t.clone('dir').base)
        
    def test_get_root(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("dir")
        dc.add_file("bl").modify("data")
        dc.close()

        t = SvnRaTransport("%s/dir" % repos_url)
        root = t.get_svn_repos_root()
        self.assertEqual(repos_url, root)

    def test_local_abspath(self):
        repos_url = self.make_repository('a')
        t = SvnRaTransport("%s" % repos_url)
        self.assertEquals(urlutils.join(self.test_dir, "a"), t.local_abspath('.'))
 

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
        self.assertEqual("http://host/gtk+/location", 
                         bzr_to_svn_url("svn+http://host/gtk%2B/location"))

    def test_url_unescape_uri(self):
        self.assertEquals("http://svn.gnome.org/svn/gtk+/trunk",
                _url_unescape_uri("http://svn.gnome.org/svn/gtk%2B/trunk"))
