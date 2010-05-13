# Copyright (C) 2006-2010 Canonical Ltd
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
"""Record counting support for showing progress of revision fetch."""

class RecordCounter(object):
    """Container for maintains estimates of work requires for fetch.

    Instance of this class is used along with a progress bar to provide
    the user an estimate of the amount of work pending for a fetch (push,
    pull, branch, checkout) operation.
    """
    def __init__(self):
        self.initialized = False
        self.current = 0
        self.key_count = 0
        self.max = 0
        self.STEP = 71

    def is_initialized(self):
        return self.initialized

    def _estimate_max(self, key_count):
        """Estimate the maximum amount of 'inserting stream' work.

        This is just an estimate.
        """
        # Note: The magic number below is based of empirical data
        # based on 3 seperate projects. Estimatation can probably
        # be improved but this should work well for most cases.
        return int(key_count * 10.3)

    def setup(self, key_count, current):
        """Setup RecordCounter with basic estimate of work pending.

        Setup self.max and self.current to reflect the amount of work
        pending for a fetch.
        """
        self.current = current
        self.key_count = key_count
        self.max = self._estimate_max(key_count)
        self.initialized = True

    def increment(self, count):
        """Increment self.current by count.

        Apart from incrementing self.current by count, also ensure
        that self.max > self.current.
        """
        self.current += count
        if self.current > self.max:
            self.max += self.key_count

