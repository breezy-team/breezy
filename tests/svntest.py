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

from bzrlib.tests import TestCaseInTempDir

import svn.ra, svn.repos, svn.wc

class TestCaseWithSvnRepository(TestCaseInTempDir):
    """A test case that provides the ability to build Subversion 
    repositories."""

    def make_repository(self):
        """Create a repository.

        :return: Handle to the repository.
        """
        pass

    def make_fs(self, relpath):
        """Create repository in relpath.

        :param relpath: Path to create repository in.
        :return: Subversion fs handle.
        """
        raise NotImplementedError(self.make_fs)

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

    def make_wc(self, relpath, reppath=""):
        """Create a repository and a checkout. Return the checkout.

        :param relpath: Optional relpath to check out if not the full 
            repository.
        :return: Subversion wc handle.
        """
        raise NotImplementedError(self.make_fs_and_wc)

    def make_ra(self, relpath):
        """Create a repository and a ra connection to it. 
        
        :param relpath: Path to create repository at.
        :return: The ra connection.
        """
        raise NotImplementedError(self.make_ra)

    def dumpfile(self, repos):
        """Create a dumpfile for the specified repository.

        :return: File name of the dumpfile.
        """
        raise NotImplementedError(self.dumpfile)

    def make_wc(self, relpath=""):
        """Create a repository and a checkout. Return the checkout.

        :param relpath: Optional relpath to check out if not the full 
            repository.
        """
        raise NotImplementedError(self.make_wc)

