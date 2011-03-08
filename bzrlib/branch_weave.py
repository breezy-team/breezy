# Copyright (C) 2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Weave-era branch implementations."""

from bzrlib import (
    errors,
    lockable_files,
    )

from bzrlib.trace import mutter

from bzrlib.branch import (
    BranchFormat,
    BzrBranch,
    )


class PreSplitOutBzrBranch(BzrBranch):

    def _get_checkout_format(self):
        """Return the most suitable metadir for a checkout of this branch.
        """
        from bzrlib.repofmt.weaverepo import RepositoryFormat7
        from bzrlib.bzrdir import BzrDirMetaFormat1
        format = BzrDirMetaFormat1()
        format.repository_format = RepositoryFormat7()
        return format


class BzrBranchFormat4(BranchFormat):
    """Bzr branch format 4.

    This format has:
     - a revision-history file.
     - a branch-lock lock file [ to be shared with the bzrdir ]
    """

    def initialize(self, a_bzrdir, name=None, repository=None):
        """Create a branch of this format in a_bzrdir.

        :param a_bzrdir: The bzrdir to initialize the branch in
        :param name: Name of colocated branch to create, if any
        :param repository: Repository for this branch (unused)
        """
        if repository is not None:
            raise NotImplementedError(
                "initialize(repository=<not None>) on %r" % (self,))
        if not [isinstance(a_bzrdir._format, format) for format in
                self._compatible_bzrdirs]:
            raise errors.IncompatibleFormat(self, a_bzrdir._format)
        utf8_files = [('revision-history', ''),
                      ('branch-name', ''),
                      ]
        mutter('creating branch %r in %s', self, a_bzrdir.user_url)
        branch_transport = a_bzrdir.get_branch_transport(self, name=name)
        control_files = lockable_files.LockableFiles(branch_transport,
            'branch-lock', lockable_files.TransportLock)
        control_files.create_lock()
        try:
            control_files.lock_write()
        except errors.LockContention:
            lock_taken = False
        else:
            lock_taken = True
        try:
            for (filename, content) in utf8_files:
                branch_transport.put_bytes(
                    filename, content,
                    mode=a_bzrdir._get_file_mode())
        finally:
            if lock_taken:
                control_files.unlock()
        branch = self.open(a_bzrdir, name, _found=True,
                found_repository=None)
        self._run_post_branch_init_hooks(a_bzrdir, name, branch)
        return branch

    def __init__(self):
        super(BzrBranchFormat4, self).__init__()
        from bzrlib.bzrdir import BzrDirFormat4, BzrDirFormat5, BzrDirFormat6
        self._matchingbzrdir = BzrDirFormat6()
        self._compatible_bzrdirs = [BzrDirFormat4, BzrDirFormat5,
            BzrDirFormat6]

    def network_name(self):
        """The network name for this format is the control dirs disk label."""
        return self._matchingbzrdir.get_format_string()

    def get_format_description(self):
        return "Branch format 4"

    def open(self, a_bzrdir, name=None, _found=False, ignore_fallbacks=False,
            found_repository=None):
        """See BranchFormat.open()."""
        if name is not None:
            raise errors.NoColocatedBranchSupport(self)
        if not _found:
            # we are being called directly and must probe.
            raise NotImplementedError
        if found_repository is None:
            found_repository = a_bzrdir.open_repository()
        return PreSplitOutBzrBranch(_format=self,
                         _control_files=a_bzrdir._control_files,
                         a_bzrdir=a_bzrdir,
                         name=name,
                         _repository=found_repository)

    def __str__(self):
        return "Bazaar-NG branch format 4"

    def supports_leaving_lock(self):
        return False
