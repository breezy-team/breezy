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
from bzrlib.plugins.svn.client import Client
from bzrlib.plugins.svn.ra import Auth, RemoteAccess, txdelta_send_stream

class TestFileEditor(object):
    def __init__(self, file):
        self.file = file

    def change_prop(self, name, value):
        self.file.change_prop(name, value)

    def modify(self, contents=None):
        if contents is None:
            contents = osutils.rand_chars(100)
        txdelta = self.apply_textdelta()
        txdelta_send_stream(StringIO(contents), txdelta)

    def close(self):
        self.file.close()


class TestDirEditor(object):
    def __init__(self, dir, baseurl, revnum):
        self.dir = dir
        self.baseurl = baseurl
        self.revnum = revnum

    def close(self):
        self.dir.close()

    def change_prop(self, name, value):
        self.dir.change_prop(name, value)

    def open_dir(self, path):
        return TestDirEditor(self.dir.open_directory(path, -1), self.baseurl, self.revnum)

    def open_file(self, path):
        return TestFileEditor(self.dir.open_file(path, -1))

    def add_dir(self, path, copyfrom_path=None, copyfrom_rev=-1):
        if copyfrom_path is not None:
            copyfrom_path = urlutils.join(self.baseurl, copyfrom_path)
        if copyfrom_path is not None and copyfrom_rev == -1:
            copyfrom_rev = self.revnum
        return TestDirEditor(self.dir.add_directory(path, copyfrom_path, copyfrom_rev), self.baseurl, self.revnum)

    def add_file(self, path, copyfrom_path=None, copyfrom_rev=-1):
        return TestFileEditor(self.dir.add_file(path, copyfrom_path, copyfrom_rev))

    def delete(self, path):
        self.dir.delete_path(path)


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

    def make_remote_bzrdir(self, relpath):
        """Create a repository."""

        repos_url = self.make_repository(relpath)

        return BzrDir.open("svn+%s" % repos_url)

    def open_local_bzrdir(self, repos_url, relpath):
        """Open a local BzrDir."""

        self.make_checkout(repos_url, relpath)

        return BzrDir.open(relpath)

    def make_local_bzrdir(self, repos_path, relpath):
        """Create a repository and checkout."""

        repos_url = self.make_repository(repos_path)

        return self.open_local_bzrdir(repos_url, relpath)

    def make_checkout(self, repos_url, relpath):
        self.client_ctx.checkout(repos_url, relpath, "HEAD") 

    @staticmethod
    def create_checkout(branch, path, revision_id=None, lightweight=False):
        return branch.create_checkout(path, revision_id=revision_id,
                                          lightweight=lightweight)

    @staticmethod
    def open_checkout(url):
        return WorkingTree.open(url)

    @staticmethod
    def open_checkout_bzrdir(url):
        return BzrDir.open(url)

    @staticmethod
    def create_branch_convenience(url):
        return BzrDir.create_branch_convenience(url)

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
        return self.client_ctx.revprop_get(name, url, revnum)[0]

    def client_set_revprop(self, url, revnum, name, value):
        self.client_ctx.revprop_set(name, value, url, revnum, True)
        
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

    def revnum_to_opt_rev(self, revnum):
        if revnum is None:
            rev = "HEAD"
        else:
            assert isinstance(revnum, int)
            rev = revnum
        return rev

    def client_log(self, path, start_revnum=None, stop_revnum=None):
        assert isinstance(path, str)
        ret = {}
        def rcvr(orig_paths, rev, revprops, has_children):
            ret[rev] = (orig_paths, revprops.get(properties.PROP_REVISION_AUTHOR), revprops.get(properties.PROP_REVISION_DATE), revprops.get(properties.PROP_REVISION_LOG))
        self.client_ctx.log([path], rcvr, None, self.revnum_to_opt_rev(start_revnum),
                       self.revnum_to_opt_rev(stop_revnum), 0,
                       True, True)
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

    def dumpfile(self, repos):
        """Create a dumpfile for the specified repository.

        :return: File name of the dumpfile.
        """
        raise NotImplementedError(self.dumpfile)

    def open_fs(self, relpath):
        """Open a fs.

        :return: FS.
        """
        return repos.Repository(relpath).fs()

    def get_commit_editor(self, url, message="Test commit"):
        ra = RemoteAccess(url.encode("utf-8"))
        revnum = ra.get_latest_revnum()
        return TestCommitEditor(ra.get_commit_editor({"svn:log": message}), ra.url, revnum)

    def commit_editor(self, url, message="Test commit"):
        ra = RemoteAccess(url.encode('utf8'))
        class CommitEditor(object):
            def __init__(self, ra, editor, base_revnum, base_url):
                self._used = False
                self.ra = ra
                self.base_revnum = base_revnum
                self.editor = editor
                self.data = {}
                self.create = set()
                self.props = {}
                self.copyfrom = {}
                self.base_url = base_url

            def _parts(self, path):
                return path.strip("/").split("/")

            def add_dir(self, path, copyfrom_path=None, copyfrom_rev=-1):
                self.create.add(path)
                if copyfrom_path is not None:
                    if copyfrom_rev == -1:
                        copyfrom_rev = self.base_revnum
                    copyfrom_path = os.path.join(self.base_url, copyfrom_path)
                self.copyfrom[path] = (copyfrom_path, copyfrom_rev)
                self.open_dir(path)

            def open_dir(self, path):
                x = self.data
                for p in self._parts(path):
                    if not p in x:
                        x[p] = {}
                    x = x[p]
                return x

            def add_file(self, path, contents=None):
                self.create.add(path)
                self.change_file(path, contents)
                
            def change_file(self, path, contents=None):
                parts = self._parts(path)
                x = self.open_dir("/".join(parts[:-1]))
                if contents is None:
                    contents = osutils.rand_chars(100)
                x[parts[-1]] = contents

            def delete(self, path):
                parts = self._parts(path)
                x = self.open_dir("/".join(parts[:-1]))
                x[parts[-1]] = None
                
            def change_dir_prop(self, path, propname, propval):
                self.open_dir(path)
                if not path in self.props:
                    self.props[path] = {}
                self.props[path][propname] = propval

            def change_file_prop(self, path, propname, propval):
                parts = self._parts(path)
                x = self.open_dir("/".join(parts[:-1]))
                x[parts[-1]] = ()
                if not path in self.props:
                    self.props[path] = {}
                self.props[path][propname] = propval

            def _process_dir(self, dir_baton, dir_dict, path):
                for name, contents in dir_dict.items():
                    subpath = urlutils.join(path, name).strip("/")
                    if contents is None:
                        dir_baton.delete_entry(subpath, -1)
                    elif isinstance(contents, dict):
                        if subpath in self.create:
                            child_baton = dir_baton.add_directory(subpath, self.copyfrom[subpath][0], self.copyfrom[subpath][1])
                        else:
                            child_baton = dir_baton.open_directory(subpath, -1)
                        if subpath in self.props:
                            for k, v in self.props[subpath].items():
                                child_baton.change_prop(k, v)

                        self._process_dir(child_baton, dir_dict[name], subpath)

                        child_baton.close()
                    else:
                        if subpath in self.create:
                            child_baton = dir_baton.add_file(subpath, None, -1)
                        else:
                            child_baton = dir_baton.open_file(subpath)
                        if isinstance(contents, str):
                            txdelta = child_baton.apply_textdelta()
                            txdelta_send_stream(StringIO(contents), txdelta)
                        if subpath in self.props:
                            for k, v in self.props[subpath].items():
                                child_baton.change_prop(k, v)
                        child_baton.close()

            def done(self):
                assert self._used == False
                self._used = True
                root_baton = self.editor.open_root(self.base_revnum)
                self._process_dir(root_baton, self.data, "")
                root_baton.close()
                self.editor.close()

                my_revnum = ra.get_latest_revnum()
                assert my_revnum > self.base_revnum

                return my_revnum

        base_revnum = ra.get_latest_revnum()
        editor = ra.get_commit_editor({"svn:log": message})
        return CommitEditor(ra, editor, base_revnum, url)


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
            'test_logwalker',
            'test_mapping',
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
            'test_wc',
            'test_workingtree',
            'test_blackbox']
    suite.addTest(loader.loadTestsFromModuleNames(["%s.%s" % (__name__, i) for i in testmod_names]))

    return suite
