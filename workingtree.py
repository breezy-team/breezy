# Copyright (C) 2008 Jelmer Vernooij <jelmer@samba.org>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""An adapter between a Git index and a Bazaar Working Tree"""


from dulwich.index import (
    Index,
    )
import os

from bzrlib import (
    inventory,
    lockable_files,
    lockdir,
    osutils,
    transport,
    urlutils,
    workingtree,
    )
from bzrlib.decorators import (
    needs_read_lock,
    needs_write_lock,
    )


def inventory_from_index(basis_inventory, index):
    inventory = basis_inventory.copy()
    return inventory


class GitWorkingTree(workingtree.WorkingTree):
    """A Git working tree."""

    def __init__(self, bzrdir, repo, branch):
        self.basedir = bzrdir.root_transport.local_abspath('.')
        self.bzrdir = bzrdir
        self.repository = repo
        self._branch = branch
        self._transport = bzrdir.transport

        self.controldir = urlutils.join(self.repository._git._controldir, 'bzr')

        try:
            os.makedirs(self.controldir)
            os.makedirs(os.path.join(self.controldir, 'lock'))
        except OSError:
            pass

        self._control_files = lockable_files.LockableFiles(
            transport.get_transport(self.controldir), 'lock', lockdir.LockDir)

        self._format = GitWorkingTreeFormat()

        self.index = Index(os.path.join(self.repository._git.controldir(), 
            "index"))
        self.views = self._make_views()
        self._detect_case_handling()

    def unlock(self):
        # non-implementation specific cleanup
        self._cleanup()

        # reverse order of locking.
        try:
            return self._control_files.unlock()
        finally:
            self.branch.unlock()

    def is_control_filename(self, path):
        return os.path.basename(path) == ".git"

    def _reset_data(self):
        self._inventory_is_modified = False
        basis_inv = self.repository.get_inventory(self.repository.get_mapping().revision_id_foreign_to_bzr(self.repository._git.head()))
        result = inventory_from_index(basis_inv, self.index)
        self._set_inventory(result, dirty=False)

    @needs_read_lock
    def get_file_sha1(self, file_id, path=None, stat_value=None):
        if not path:
            path = self._inventory.id2path(file_id)
        return osutils.fingerprint_file(open(self.abspath(path).encode(osutils._fs_enc)))['sha1']


class GitWorkingTreeFormat(workingtree.WorkingTreeFormat):

    def get_format_description(self):
        return "Git Working Tree"
