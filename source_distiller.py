#    source_distiller.py -- Getting the source to build from a branch
#    Copyright (C) 2008 Canonical Ltd.
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA


import os
import shutil

from bzrlib import errors as bzr_errors
from bzrlib.export import export


class SourceDistiller(object):
    """A source distiller extracts the source to build from a location.

    It does whatever is needed to give you a source you can build at
    a location of your choice.
    """

    def __init__(self):
        """Create a SourceDistiller to distill from the specified branch.

        See the specific subclass for required arguments.
        """
        raise NotImplementedError(self.__init__)

    def distill(self, target):
        """Extract the source to a tree rooted at the given location.

        The passed location cannot already exist. If it does then
        FileExists will be raised.

        :param target: a string containing the location at which to 
            place the tree containing the buildable source.
        """
        if os.path.exists(target):
            raise bzr_errors.FileExists(target)
        self._distill(target)

    def _distill(self, target):
        """Subclasses should override this to implement distill."""
        raise NotImplementedError(self._distill)


class NativeSourceDistiller(SourceDistiller):
    """A SourceDistiller for unpacking a native package from a branch."""

    def __init__(self, tree):
        """Create a NativeSourceDistiller.

        :param tree: the tree containing the native package source. Should
            be locked at least for read.
        """
        self.tree = tree

    def _distill(self, target):
        export(self.tree, target, None, None)


class FullSourceDistiller(SourceDistiller):
    """A SourceDistiller for full-source branches, a.k.a. normal mode"""

    def __init__(self, tree, tarfile_path):
        """Create a FullSourceDistiller.

        :param tree: the tree to export with all of the source code. Should
            be locked at least for read.
        :param tarfile_path: a string containg the path to a tarfile
            containing the upstream code. This will be placed in the parent
            directory of the target when distill() is called.
        """
        self.tree = tree
        self.tarfile_path = tarfile_path

    def _copy_tarfile_to_parent(self, target):
        parent_dir = os.path.dirname(target)
        tarfile_name = os.path.basename(self.tarfile_path)
        target_location = os.path.join(parent_dir, tarfile_name)
        if (os.path.exists(self.tarfile_path)
                and os.path.exists(target_location)
                and os.path.samefile(self.tarfile_path, target_location)):
            return
        try:
            shutil.copyfile(self.tarfile_path, target_location)
        except IOError, e:
            if e.errno == 2:
                raise bzr_errors.NoSuchFile(self.tarfile_path)
            raise

    def _distill(self, target):
        self._copy_tarfile_to_parent(target)
        export(self.tree, target, None, None)
