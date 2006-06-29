# Copyright (C) 2005-2006 Jelmer Vernooij <jelmer@samba.org>

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

from binascii import hexlify
from bzrlib.bzrdir import BzrDirFormat
from bzrlib.errors import NotBranchError, NoSuchFile
from bzrlib.inventory import Inventory, InventoryDirectory, InventoryFile
from bzrlib.lockable_files import TransportLock, LockableFiles
from bzrlib.lockdir import LockDir
from bzrlib.osutils import rand_bytes, fingerprint_file
from bzrlib.progress import DummyProgress
from bzrlib.tree import RevisionTree, EmptyTree

import os

import svn.core, svn.wc
from svn.core import SubversionException

class SvnRevisionTree(RevisionTree):
    def __init__(self, repository, revision_id, inventory=None):
        self._repository = repository
        self._revision_id = revision_id
        if inventory:
            self._inventory = inventory
        else:
            self._inventory = repository.get_inventory(revision_id)
        (self._branch_path, self._revnum) = repository.parse_revision_id(revision_id)
        # FIXME: Use checkout

    def get_file_lines(self, file_id):
        path = "%s/%s" % (self._branch_path, self.id2path(file_id))
        stream = self._repository._get_file(path, self._revnum)
        return stream.readlines()

class SvnBasisTree(SvnRevisionTree):
    """Optimized version of SvnRevisionTree."""
    def __init__(self, workingtree, revid):
        super(SvnBasisTree, self).__init__(workingtree.branch.repository,
                                           revid)
        self.workingtree = workingtree

    def get_file_lines(self, file_id):
        path = self.id2path(file_id)
        base_copy = svn.wc.get_pristine_copy_path(self.workingtree.abspath(path))
        return open(base_copy).readlines()

