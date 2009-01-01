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

import os

from bzrlib import (
    inventory,
    lockable_files,
    lockdir,
    transport,
    urlutils,
    workingtree,
    )

from dulwich.index import Index

class GitWorkingTree(workingtree.WorkingTree):
    """A Git working tree."""

    def __init__(self, bzrdir, repo, branch):
        self.basedir = bzrdir.transport.base
        self.bzrdir = bzrdir
        self.repository = repo
        self._branch = branch
        self._transport = bzrdir.transport

        self.controldir = urlutils.join(self.repository._git.path, 'bzr')

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

    def lock_read(self):
        pass

    def unlock(self):
        pass

    def is_control_filename(self, path):
        return os.path.basename(path) == ".git"

    def _get_inventory(self):
        return inventory.Inventory()

    inventory = property(_get_inventory,
                         doc="Inventory of this Tree")


class GitWorkingTreeFormat(workingtree.WorkingTreeFormat):

    def get_format_description(self):
        return "Git Working Tree"
