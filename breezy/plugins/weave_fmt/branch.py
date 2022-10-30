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

from ... import (
    controldir as _mod_controldir,
    errors,
    lockable_files,
    )

from ...decorators import (
    only_raises,
    )
from ...lock import LogicalLockResult
from ...trace import mutter

from ...branch import (
    BindingUnsupported,
    BranchFormat,
    BranchWriteLockResult,
    )
from ...bzr.fullhistory import (
    FullHistoryBzrBranch,
    )


class BzrBranch4(FullHistoryBzrBranch):
    """Branch format 4."""

    def lock_write(self, token=None):
        """Lock the branch for write operations.

        :param token: A token to permit reacquiring a previously held and
            preserved lock.
        :return: A BranchWriteLockResult.
        """
        if not self.is_locked():
            self._note_lock('w')
        # All-in-one needs to always unlock/lock.
        self.repository._warn_if_deprecated(self)
        self.repository.lock_write()
        try:
            return BranchWriteLockResult(self.unlock,
                                         self.control_files.lock_write(token=token))
        except:
            self.repository.unlock()
            raise

    def lock_read(self):
        """Lock the branch for read operations.

        :return: A breezy.lock.LogicalLockResult.
        """
        if not self.is_locked():
            self._note_lock('r')
        # All-in-one needs to always unlock/lock.
        self.repository._warn_if_deprecated(self)
        self.repository.lock_read()
        try:
            self.control_files.lock_read()
            return LogicalLockResult(self.unlock)
        except:
            self.repository.unlock()
            raise

    @only_raises(errors.LockNotHeld, errors.LockBroken)
    def unlock(self):
        if self.control_files._lock_count == 2 and self.conf_store is not None:
            self.conf_store.save_changes()
        try:
            self.control_files.unlock()
        finally:
            # All-in-one needs to always unlock/lock.
            self.repository.unlock()
            if not self.control_files.is_locked():
                # we just released the lock
                self._clear_cached_state()

    def _get_checkout_format(self, lightweight=False):
        """Return the most suitable metadir for a checkout of this branch.
        """
        from .repository import RepositoryFormat7
        from ...bzr.bzrdir import BzrDirMetaFormat1
        format = BzrDirMetaFormat1()
        if lightweight:
            format.set_branch_format(self._format)
            format.repository_format = self.controldir._format.repository_format
        else:
            format.repository_format = RepositoryFormat7()
        return format

    def unbind(self):
        raise errors.UpgradeRequired(self.user_url)

    def bind(self, other):
        raise BindingUnsupported(self)

    def set_bound_location(self, location):
        raise NotImplementedError(self.set_bound_location)

    def get_bound_location(self):
        return None

    def update(self):
        return None

    def get_master_branch(self, possible_transports=None):
        return None


class BzrBranchFormat4(BranchFormat):
    """Bzr branch format 4.

    This format has:
     - a revision-history file.
     - a branch-lock lock file [ to be shared with the bzrdir ]

    It does not support binding.
    """

    def initialize(self, a_controldir, name=None, repository=None,
                   append_revisions_only=None):
        """Create a branch of this format in a_controldir.

        :param a_controldir: The bzrdir to initialize the branch in
        :param name: Name of colocated branch to create, if any
        :param repository: Repository for this branch (unused)
        """
        if append_revisions_only:
            raise errors.UpgradeRequired(a_controldir.user_url)
        if repository is not None:
            raise NotImplementedError(
                "initialize(repository=<not None>) on %r" % (self,))
        if not [isinstance(a_controldir._format, format) for format in
                self._compatible_bzrdirs]:
            raise errors.IncompatibleFormat(self, a_controldir._format)
        utf8_files = [('revision-history', b''),
                      ('branch-name', b''),
                      ]
        mutter('creating branch %r in %s', self, a_controldir.user_url)
        branch_transport = a_controldir.get_branch_transport(self, name=name)
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
                    mode=a_controldir._get_file_mode())
        finally:
            if lock_taken:
                control_files.unlock()
        branch = self.open(a_controldir, name, _found=True,
                           found_repository=None)
        self._run_post_branch_init_hooks(a_controldir, name, branch)
        return branch

    def __init__(self):
        super(BzrBranchFormat4, self).__init__()
        from .bzrdir import (
            BzrDirFormat4, BzrDirFormat5, BzrDirFormat6,
            )
        self._matchingcontroldir = BzrDirFormat6()
        self._compatible_bzrdirs = [BzrDirFormat4, BzrDirFormat5,
                                    BzrDirFormat6]

    def network_name(self):
        """The network name for this format is the control dirs disk label."""
        return self._matchingcontroldir.get_format_string()

    def get_format_description(self):
        return "Branch format 4"

    def open(self, a_controldir, name=None, _found=False, ignore_fallbacks=False,
             found_repository=None, possible_transports=None):
        """See BranchFormat.open()."""
        if name is None:
            name = a_controldir._get_selected_branch()
        if name != "":
            raise _mod_controldir.NoColocatedBranchSupport(self)
        if not _found:
            # we are being called directly and must probe.
            raise NotImplementedError
        if found_repository is None:
            found_repository = a_controldir.open_repository()
        return BzrBranch4(_format=self,
                          _control_files=a_controldir._control_files,
                          a_controldir=a_controldir,
                          name=name,
                          _repository=found_repository,
                          possible_transports=possible_transports)

    def __str__(self):
        return "Bazaar-NG branch format 4"

    def supports_leaving_lock(self):
        return False

    supports_reference_locations = False
