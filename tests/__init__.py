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

import svn.repos
import os
from bzrlib import osutils
from bzrlib.bzrdir import BzrDir
from bzrlib.tests import TestCaseInTempDir

import svn.ra, svn.repos, svn.wc

class TestCaseWithSubversionRepository(TestCaseInTempDir):
    """A test case that provides the ability to build Subversion 
    repositories."""

    def make_repository(self, relpath):
        """Create a repository.

        :return: Handle to the repository.
        """
        abspath = os.path.join(self.test_dir, relpath)
        repos_url = "file://%s" % abspath

        repos = svn.repos.create(abspath, '', '', None, None)

        return repos_url

    def make_remote_bzrdir(self, relpath):
        """Create a repository."""

        repos_url = self.make_repository(relpath)

        return BzrDir.open(repos_url)

    def open_local_bzrdir(self, repos_url, relpath):
        """Open a local BzrDir."""

        ctx = svn.client.create_context()
        
        rev = svn.core.svn_opt_revision_t()
        rev.kind = svn.core.svn_opt_revision_head

        svn.client.checkout2(repos_url, relpath, 
                rev, rev, True, False, ctx)

        return BzrDir.open(relpath)

    def make_local_bzrdir(self, repos_path, relpath):
        """Create a repository and checkout."""

        repos_url = self.make_repository(repos_path)

        return self.open_local_bzrdir(repos_url, relpath)
        
    def wc_commit(self, relpaths):
        """Commit current changes in specified working copy.
        
        :param relpath: List of paths to commit.
        """
        raise NotImplementedError(self.wc_commit)

    def wc_add(self, relpath):
        """Add specified files to working copy.
        
        :param relpath: Path to the files to add.
        """
        raise NotImplementedError(self.wc_add)

    def wc_remove(self, relpaths):
        """Remove specified files from working copy.

        :param relpath: Path to the files to remove.
        """
        raise NotImplementedError(self.wc_add)

    def wc_copy(self, oldpath, newpath):
        """Copy file in working copy.

        :param oldpath: Relative path to original file.
        :param newpath: Relative path to new file.
        """
        raise NotImplementedError(self.wc_copy)

    def build_tree(self, files):
        """Create a directory tree.
        
        :param files: Dictionary with filenames as keys, contents as 
            values. None as value indicates a directory.
        """
        raise NotImplementedError(self.build_tree)

    def make_wc(self, relpath, repos_url=None):
        """Create a repository and a checkout. Return the checkout.

        :param relpath: Optional relpath to check out if not the full 
            repository.
        :return: Subversion wc handle.
        """
        # FIXME
        raise NotImplementedError(self.make_wc)

    def make_ra(self, relpath):
        """Create a repository and a ra connection to it. 
        
        :param relpath: Path to create repository at.
        :return: The ra connection.
        """

        repos_url = self.make_repository(relpath)

        return svn.ra.open2(repos_url, svn.ra.callbacks2_t(), None)

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
    from unittest import TestSuite, TestLoader
    import tests.test_repos, tests.test_branch, tests.test_scheme

    suite = TestSuite()

    suite.addTest(TestLoader().loadTestsFromModule(tests.test_repos))
    suite.addTest(TestLoader().loadTestsFromModule(tests.test_branch))
    suite.addTest(TestLoader().loadTestsFromModule(tests.test_scheme))

    return suite
