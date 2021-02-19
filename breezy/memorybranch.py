# Copyright (C) 2020 Breezy Developers
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

"""MemoryBranch object.
"""

from __future__ import absolute_import

from . import config as _mod_config, errors, osutils
from .branch import Branch
from .lock import LogicalLockResult, _RelockDebugMixin
from .revision import NULL_REVISION
from .tag import DisabledTags, MemoryTags


class MemoryBranch(Branch, _RelockDebugMixin):

    def __init__(self, repository, last_revision_info, tags=None):
        self.repository = repository
        self._last_revision_info = last_revision_info
        self._revision_history_cache = None
        if tags is not None:
            self.tags = MemoryTags(tags)
        else:
            self.tags = DisabledTags(self)
        self._partial_revision_history_cache = []
        self._last_revision_info_cache = None
        self._revision_id_to_revno_cache = None
        self._partial_revision_id_to_revno_cache = {}
        self.base = 'memory://' + osutils.rand_chars(10)

    def get_config(self):
        return _mod_config.Config()

    def lock_read(self):
        self.repository.lock_read()
        return LogicalLockResult(self.unlock)

    def lock_write(self, token=None):
        self.repository.lock_write()
        return BranchWriteLockResult(self.unlock, None)

    def unlock(self):
        self.repository.unlock()

    def last_revision_info(self):
        return self._last_revision_info

    def _gen_revision_history(self):
        """Generate the revision history from last revision
        """
        last_revno, last_revision = self.last_revision_info()
        with self.lock_read():
            self._extend_partial_history()
            return list(reversed(self._partial_revision_history_cache))

    def get_rev_id(self, revno, history=None):
        """Find the revision id of the specified revno."""
        with self.lock_read():
            if revno == 0:
                return NULL_REVISION
            last_revno, last_revid = self.last_revision_info()
            if revno == last_revno:
                return last_revid
            if last_revno is None:
                self._extend_partial_history()
                return self._partial_revision_history_cache[
                    len(self._partial_revision_history_cache) - revno]
            else:
                if revno <= 0 or revno > last_revno:
                    raise errors.NoSuchRevision(self, revno)
                distance_from_last = last_revno - revno
                if len(self._partial_revision_history_cache) <= \
                        distance_from_last:
                    self._extend_partial_history(distance_from_last)
                return self._partial_revision_history_cache[distance_from_last]
