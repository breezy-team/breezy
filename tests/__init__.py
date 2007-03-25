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

import os
import bzrlib
from bzrlib import osutils
from bzrlib.bzrdir import BzrDir
from bzrlib.tests import TestCaseInTempDir
from bzrlib.trace import mutter

RENAMES = False

import svn.repos, svn.wc

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

    def make_repository(self, relpath):
        """Create a repository.

        :return: Handle to the repository.
        """
        abspath = os.path.join(self.test_dir, relpath)
        repos_url = "file://%s" % abspath

        svn.repos.create(abspath, '', '', None, None)

        revprop_hook = os.path.join(abspath, "hooks", "pre-revprop-change")

        open(revprop_hook, 'w').write("#!/bin/sh")

        os.chmod(revprop_hook, os.stat(revprop_hook).st_mode | 0111)

        return repos_url

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
        rev = svn.core.svn_opt_revision_t()
        rev.kind = svn.core.svn_opt_revision_head

        svn.client.checkout2(repos_url, relpath, 
                rev, rev, True, False, self.client_ctx)

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
        
    def client_commit(self, dir, message=None, recursive=True):
        """Commit current changes in specified working copy.
        
        :param relpath: List of paths to commit.
        """
        olddir = os.path.abspath('.')
        self.next_message = message
        os.chdir(dir)
        info = svn.client.commit3(["."], recursive, False, self.client_ctx)
        os.chdir(olddir)
        return (info.revision, info.date, info.author)

    def client_add(self, relpath, recursive=True):
        """Add specified files to working copy.
        
        :param relpath: Path to the files to add.
        """
        svn.client.add3(relpath, recursive, False, False, self.client_ctx)

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

    def make_client(self, repospath, clientpath):
        """Create a repository and a checkout. Return the checkout.

        :param relpath: Optional relpath to check out if not the full 
            repository.
        :return: Repository URL.
        """
        repos_url = self.make_repository(repospath)
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


def test_suite():
    from unittest import TestSuite
    
    from bzrlib.tests import TestUtil

    loader = TestUtil.TestLoader()

    suite = TestSuite()

    testmod_names = [
            'test_blackbox',
            'test_branch', 
            'test_branchprops', 
            'test_checkout',
            'test_commit',
            'test_convert',
            'test_errors',
            'test_fileids', 
            'test_logwalker',
            'test_radir',
            'test_repos', 
            'test_scheme', 
            'test_transport',
            'test_tree',
            'test_upgrade',
            'test_workingtree']
    suite.addTest(loader.loadTestsFromModuleNames(["%s.%s" % (__name__, i) for i in testmod_names]))

    return suite
