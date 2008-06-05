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
from bzrlib import osutils, urlutils
from bzrlib.bzrdir import BzrDir
from bzrlib.tests import TestCaseInTempDir, TestSkipped
from bzrlib.trace import mutter
from bzrlib.urlutils import local_path_to_url
from bzrlib.workingtree import WorkingTree

import svn.repos, svn.wc
from bzrlib.plugins.svn.errors import NoCheckoutSupport

class TestCaseWithSubversionRepository(TestCaseInTempDir):
    """A test case that provides the ability to build Subversion 
    repositories."""

    def setUp(self):
        super(TestCaseWithSubversionRepository, self).setUp()
        self.client_ctx = svn.client.create_context()
        self.client_ctx.log_msg_func2 = svn.client.svn_swig_py_get_commit_log_func
        self.client_ctx.log_msg_baton2 = self.log_message_func

    def log_message_func(self, items, pool):
        return self.next_message

    def make_repository(self, relpath, allow_revprop_changes=True):
        """Create a repository.

        :return: Handle to the repository.
        """
        abspath = os.path.join(self.test_dir, relpath)

        svn.repos.create(abspath, '', '', None, None)

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

        try:
            return self.open_local_bzrdir(repos_url, relpath)
        except NoCheckoutSupport:
            raise TestSkipped('No Checkout Support')


    def make_checkout(self, repos_url, relpath):
        rev = svn.core.svn_opt_revision_t()
        rev.kind = svn.core.svn_opt_revision_head

        svn.client.checkout2(repos_url, relpath, 
                rev, rev, True, False, self.client_ctx)

    @staticmethod
    def create_checkout(branch, path, revision_id=None, lightweight=False):
        try:
            return branch.create_checkout(path, revision_id=revision_id,
                                          lightweight=lightweight)
        except NoCheckoutSupport:
            raise TestSkipped('No Checkout Support')

    @staticmethod
    def open_checkout(url):
        try:
            return WorkingTree.open(url)
        except NoCheckoutSupport:
           raise TestSkipped('No Checkout Support')

    @staticmethod
    def open_checkout_bzrdir(url):
        try:
            return BzrDir.open(url)
        except NoCheckoutSupport:
           raise TestSkipped('No Checkout Support')

    @staticmethod
    def create_branch_convenience(url):
        try:
            return BzrDir.create_branch_convenience(url)
        except NoCheckoutSupport:
           raise TestSkipped('No Checkout Support')

    def client_set_prop(self, path, name, value):
        if value is None:
            value = ""
        svn.client.propset2(name, value, path, False, True, self.client_ctx)

    def client_get_prop(self, path, name, revnum=None, recursive=False):
        rev = svn.core.svn_opt_revision_t()

        if revnum is None:
            rev.kind = svn.core.svn_opt_revision_working
        else:
            rev.kind = svn.core.svn_opt_revision_number
            rev.value.number = revnum
        ret = svn.client.propget2(name, path, rev, rev, recursive, 
                                  self.client_ctx)
        if recursive:
            return ret
        else:
            return ret.values()[0]

    def client_get_revprop(self, url, revnum, name):
        rev = svn.core.svn_opt_revision_t()
        rev.kind = svn.core.svn_opt_revision_number
        rev.value.number = revnum
        return svn.client.revprop_get(name, url, rev, self.client_ctx)[0]

    def client_set_revprop(self, url, revnum, name, value):
        rev = svn.core.svn_opt_revision_t()
        rev.kind = svn.core.svn_opt_revision_number
        rev.value.number = revnum
        svn.client.revprop_set(name, value, url, rev, True, self.client_ctx)
        
    def client_commit(self, dir, message=None, recursive=True):
        """Commit current changes in specified working copy.
        
        :param relpath: List of paths to commit.
        """
        olddir = os.path.abspath('.')
        self.next_message = message
        os.chdir(dir)
        info = svn.client.commit2(["."], recursive, False, self.client_ctx)
        os.chdir(olddir)
        assert info is not None
        return (info.revision, info.date, info.author)

    def client_add(self, relpath, recursive=True):
        """Add specified files to working copy.
        
        :param relpath: Path to the files to add.
        """
        svn.client.add3(relpath, recursive, False, False, self.client_ctx)

    def revnum_to_opt_rev(self, revnum):
        rev = svn.core.svn_opt_revision_t()
        if revnum is None:
            rev.kind = svn.core.svn_opt_revision_head
        else:
            assert isinstance(revnum, int)
            rev.kind = svn.core.svn_opt_revision_number
            rev.value.number = revnum
        return rev

    def client_log(self, path, start_revnum=None, stop_revnum=None):
        assert isinstance(path, str)
        ret = {}
        def rcvr(orig_paths, rev, author, date, message, pool):
            ret[rev] = (orig_paths, author, date, message)
        svn.client.log([path], self.revnum_to_opt_rev(start_revnum),
                       self.revnum_to_opt_rev(stop_revnum),
                       True,
                       True,
                       rcvr,
                       self.client_ctx)
        return ret

    def client_delete(self, relpath):
        """Remove specified files from working copy.

        :param relpath: Path to the files to remove.
        """
        svn.client.delete2([relpath], True, self.client_ctx)

    def client_copy(self, oldpath, newpath, revnum=None):
        """Copy file in working copy.

        :param oldpath: Relative path to original file.
        :param newpath: Relative path to new file.
        """
        rev = svn.core.svn_opt_revision_t()
        if revnum is None:
            rev.kind = svn.core.svn_opt_revision_head
        else:
            rev.kind = svn.core.svn_opt_revision_number
            rev.value.number = revnum
        svn.client.copy2(oldpath, rev, newpath, self.client_ctx)

    def client_update(self, path):
        rev = svn.core.svn_opt_revision_t()
        rev.kind = svn.core.svn_opt_revision_head
        svn.client.update(path, rev, True, self.client_ctx)

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
        repos = svn.repos.open(relpath)

        return svn.repos.fs(repos)

    def commit_editor(self, url, message="Test commit"):
        ra = svn.client.open_ra_session(url.encode('utf8'), 
                    self.client_ctx)
        class CommitEditor:
            def __init__(self, ra, editor, edit_baton, base_revnum):
                self.ra = ra
                self.base_revnum = base_revnum
                self.editor = editor
                self.edit_baton = edit_baton
                self.data = {}
                self.create = set()
                self.props = {}

            def _parts(self, path):
                return path.strip("/").split("/")

            def add_dir(self, path):
                self.create.add(path)
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
                self.open_file(path)
                if not path in self.props:
                    self.props[path] = {}
                self.props[path][propname] = propval

            def _process_dir(self, dir_baton, dir_dict, path):
                for name, contents in dir_dict.items():
                    subpath = urlutils.join(path, name).strip("/")
                    if contents is None:
                        svn.delta.editor_invoke_delete_entry(self.editor, dir_baton, subpath)
                    elif isinstance(contents, dict):
                        if subpath in self.create:
                            child_baton = svn.delta.editor_invoke_add_directory(self.editor, subpath, dir_baton, -1)
                        else:
                            child_baton = svn.delta.editor_invoke_open_directory(self.editor, subpath, dir_baton, -1)
                        if subpath in self.props:
                            for k, v in self.props[subpath].items():
                                svn.delta_editor_invoke_change_dir_prop(self.editor, child_baton, k, v)

                        self._process_dir(child_baton, dir_dict[name], subpath)

                        svn.delta.editor_invoke_close_directory(self.editor, child_baton)
                    elif isinstance(contents, str):
                        if subpath in self.create:
                            child_baton = svn.delta.editor_invoke_add_file(self.editor, subpath, dir_baton, None, -1)
                        else:
                            child_baton = svn.delta.editor_invoke_open_file(self.editor, subpath, dir_baton, -1)
                         # FIXME
                        if subpath in self.props:
                            for k, v in self.props[subpath].items():
                                svn.delta.editor_invoke_change_file_prop(self.editor, child_baton, k, v)
                        svn.delta.editor_invoke_close_file(self.editor, child_baton, None)

            def done(self):
                root_baton = svn.delta.editor_invoke_open_root(self.editor, self.edit_baton, 
                                                               self.base_revnum)
                self._process_dir(root_baton, self.data, "")
                svn.delta.editor_invoke_close_directory(self.editor, root_baton)
                svn.delta.editor_invoke_close_edit(self.editor, self.edit_baton)

        base_revnum = svn.ra.get_latest_revnum(ra)
        editor, edit_baton = svn.ra.get_commit_editor(ra, message, None, None, True)
        return CommitEditor(ra, editor, edit_baton, base_revnum)


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
            'test_commit',
            'test_config',
            'test_convert',
            'test_errors',
            'test_fetch',
            'test_fileids', 
            'test_logwalker',
            'test_mapping',
            'test_push',
            'test_radir',
            'test_repos', 
            'test_revids',
            'test_revspec',
            'test_scheme', 
            'test_svk',
            'test_transport',
            'test_tree',
            'test_upgrade',
            'test_workingtree',
            'test_blackbox']
    suite.addTest(loader.loadTestsFromModuleNames(["%s.%s" % (__name__, i) for i in testmod_names]))

    return suite
