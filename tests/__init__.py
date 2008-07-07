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

"""Tests for the bzr-svn plugin."""

import os
import sys
import bzrlib

from cStringIO import StringIO

from bzrlib import osutils, urlutils
from bzrlib.bzrdir import BzrDir
from bzrlib.tests import TestCaseInTempDir, TestSkipped
from bzrlib.trace import mutter
from bzrlib.urlutils import local_path_to_url
from bzrlib.workingtree import WorkingTree

from bzrlib.plugins.svn import properties, ra, repos
from bzrlib.plugins.svn.delta import send_stream
from bzrlib.plugins.svn.client import Client
from bzrlib.plugins.svn.ra import Auth, RemoteAccess

class TestFileEditor(object):
    def __init__(self, file):
        self.file = file
        self.is_closed = False

    def change_prop(self, name, value):
        self.file.change_prop(name, value)

    def modify(self, contents=None):
        if contents is None:
            contents = osutils.rand_chars(100)
        txdelta = self.file.apply_textdelta()
        send_stream(StringIO(contents), txdelta)

    def close(self):
        assert not self.is_closed
        self.is_closed = True
        self.file.close()


class TestDirEditor(object):
    def __init__(self, dir, baseurl, revnum):
        self.dir = dir
        self.baseurl = baseurl
        self.revnum = revnum
        self.is_closed = False
        self.children = []

    def close_children(self):
        for c in reversed(self.children):
            if not c.is_closed:
                c.close()

    def close(self):
        assert not self.is_closed
        self.is_closed = True
        self.close_children()
        self.dir.close()

    def change_prop(self, name, value):
        self.dir.change_prop(name, value)

    def open_dir(self, path):
        self.close_children()
        child = TestDirEditor(self.dir.open_directory(path, -1), self.baseurl, self.revnum)
        self.children.append(child)
        return child

    def open_file(self, path):
        self.close_children()
        child = TestFileEditor(self.dir.open_file(path, -1))
        self.children.append(child)
        return child

    def add_dir(self, path, copyfrom_path=None, copyfrom_rev=-1):
        self.close_children()
        if copyfrom_path is not None:
            copyfrom_path = urlutils.join(self.baseurl, copyfrom_path)
        if copyfrom_path is not None and copyfrom_rev == -1:
            copyfrom_rev = self.revnum
        child = TestDirEditor(self.dir.add_directory(path, copyfrom_path, copyfrom_rev), self.baseurl, self.revnum)
        self.children.append(child)
        return child

    def add_file(self, path, copyfrom_path=None, copyfrom_rev=-1):
        self.close_children()
        if copyfrom_path is not None:
            copyfrom_path = urlutils.join(self.baseurl, copyfrom_path)
        if copyfrom_path is not None and copyfrom_rev == -1:
            copyfrom_rev = self.revnum
        child = TestFileEditor(self.dir.add_file(path, copyfrom_path, copyfrom_rev))
        self.children.append(child)
        return child

    def delete(self, path):
        self.dir.delete_entry(path)


class TestCommitEditor(TestDirEditor):
    def __init__(self, editor, baseurl, revnum):
        self.editor = editor
        TestDirEditor.__init__(self, self.editor.open_root(), baseurl, revnum)

    def close(self):
        TestDirEditor.close(self)
        self.editor.close()


class TestCaseWithSubversionRepository(TestCaseInTempDir):
    """A test case that provides the ability to build Subversion 
    repositories."""

    def setUp(self):
        super(TestCaseWithSubversionRepository, self).setUp()
        self.client_ctx = Client()
        self.client_ctx.auth = Auth([ra.get_simple_provider(), 
                                     ra.get_username_provider(),
                                     ra.get_ssl_client_cert_file_provider(),
                                     ra.get_ssl_client_cert_pw_file_provider(),
                                     ra.get_ssl_server_trust_file_provider()])
        self.client_ctx.log_msg_func = self.log_message_func
        #self.client_ctx.notify_func = lambda err: mutter("Error: %s" % err)

    def log_message_func(self, items):
        return self.next_message

    def make_repository(self, relpath, allow_revprop_changes=True):
        """Create a repository.

        :return: Handle to the repository.
        """
        abspath = os.path.join(self.test_dir, relpath)

        repos.create(abspath)

        if allow_revprop_changes:
            if sys.platform == 'win32':
                revprop_hook = os.path.join(abspath, "hooks", "pre-revprop-change.bat")
                open(revprop_hook, 'w').write("exit 0\n")
            else:
                revprop_hook = os.path.join(abspath, "hooks", "pre-revprop-change")
                open(revprop_hook, 'w').write("#!/bin/sh\n")
                os.chmod(revprop_hook, os.stat(revprop_hook).st_mode | 0111)

        return local_path_to_url(abspath)

    def make_local_bzrdir(self, repos_path, relpath):
        """Create a repository and checkout."""

        repos_url = self.make_repository(repos_path)

        self.make_checkout(repos_url, relpath)

        return BzrDir.open(relpath)

    def make_checkout(self, repos_url, relpath):
        self.client_ctx.checkout(repos_url, relpath, "HEAD") 

    @staticmethod
    def open_checkout(url):
        return WorkingTree.open(url)

    @staticmethod
    def open_checkout_bzrdir(url):
        return BzrDir.open(url)

    def client_set_prop(self, path, name, value):
        if value is None:
            value = ""
        self.client_ctx.propset(name, value, path, False, True)

    def client_get_prop(self, path, name, revnum=None, recursive=False):
        if revnum is None:
            rev = "WORKING"
        else:
            rev = revnum
        ret = self.client_ctx.propget(name, path, rev, rev, recursive)
        if recursive:
            return ret
        else:
            return ret.values()[0]

    def client_get_revprop(self, url, revnum, name):
        r = ra.RemoteAccess(url)
        return r.rev_proplist(revnum)[name]

    def client_set_revprop(self, url, revnum, name, value):
        r = ra.RemoteAccess(url)
        r.change_rev_prop(revnum, name, value)
        
    def client_commit(self, dir, message=None, recursive=True):
        """Commit current changes in specified working copy.
        
        :param relpath: List of paths to commit.
        """
        olddir = os.path.abspath('.')
        self.next_message = message
        os.chdir(dir)
        info = self.client_ctx.commit(["."], recursive, False)
        os.chdir(olddir)
        assert info is not None
        return info

    def client_add(self, relpath, recursive=True):
        """Add specified files to working copy.
        
        :param relpath: Path to the files to add.
        """
        self.client_ctx.add(relpath, recursive, False, False)

    def client_log(self, url, start_revnum, stop_revnum):
        r = ra.RemoteAccess(url)
        assert isinstance(url, str)
        ret = {}
        def rcvr(orig_paths, rev, revprops, has_children):
            ret[rev] = (orig_paths, revprops.get(properties.PROP_REVISION_AUTHOR), revprops.get(properties.PROP_REVISION_DATE), revprops.get(properties.PROP_REVISION_LOG))
        r.get_log(rcvr, [""], start_revnum, stop_revnum, 0, True, True)
        return ret

    def client_delete(self, relpath):
        """Remove specified files from working copy.

        :param relpath: Path to the files to remove.
        """
        self.client_ctx.delete([relpath], True)

    def client_copy(self, oldpath, newpath, revnum=None):
        """Copy file in working copy.

        :param oldpath: Relative path to original file.
        :param newpath: Relative path to new file.
        """
        if revnum is None:
            rev = "HEAD"
        else:
            rev = revnum
        self.client_ctx.copy(oldpath, newpath, rev)

    def client_update(self, path):
        self.client_ctx.update([path], "HEAD", True)

    def build_tree(self, files):
        """Create a directory tree.
        
        :param files: Dictionary with filenames as keys, contents as 
            values. None as value indicates a directory.
        """
        for f in files:
            if files[f] is None:
                try:
                    os.makedirs(f)
                except OSError:
                    pass
            else:
                try:
                    os.makedirs(os.path.dirname(f))
                except OSError:
                    pass
                open(f, 'w').write(files[f])

    def make_client_and_bzrdir(self, repospath, clientpath):
        repos_url = self.make_client(repospath, clientpath)

        return BzrDir.open("svn+%s" % repos_url)

    def make_client(self, repospath, clientpath, allow_revprop_changes=True):
        """Create a repository and a checkout. Return the checkout.

        :param relpath: Optional relpath to check out if not the full 
            repository.
        :param clientpath: Path to checkout
        :return: Repository URL.
        """
        repos_url = self.make_repository(repospath, 
            allow_revprop_changes=allow_revprop_changes)
        self.make_checkout(repos_url, clientpath)
        return repos_url

    def open_fs(self, relpath):
        """Open a fs.

        :return: FS.
        """
        return repos.Repository(relpath).fs()

    def get_commit_editor(self, url, message="Test commit"):
        ra = RemoteAccess(url.encode("utf-8"))
        revnum = ra.get_latest_revnum()
        return TestCommitEditor(ra.get_commit_editor({"svn:log": message}), ra.url, revnum)


def test_suite():
    from unittest import TestSuite
    
    from bzrlib.tests import TestUtil

    loader = TestUtil.TestLoader()

    suite = TestSuite()

    testmod_names = [
            'test_branch', 
            'test_branchprops', 
            'test_changes',
            'test_checkout',
            'test_client',
            'test_commit',
            'test_config',
            'test_convert',
            'test_core',
            'test_errors',
            'test_fetch',
            'test_fileids', 
            'test_log',
            'test_logwalker',
            'test_mapping',
            'test_properties',
            'test_push',
            'test_ra',
            'test_radir',
            'test_repos', 
            'test_repository', 
            'test_revids',
            'test_revspec',
            'test_scheme', 
            'test_svk',
            'test_transport',
            'test_tree',
            'test_upgrade',
            'test_versionedfiles',
            'test_wc',
            'test_workingtree',
            'test_blackbox']
    suite.addTest(loader.loadTestsFromModuleNames(["%s.%s" % (__name__, i) for i in testmod_names]))

    return suite
