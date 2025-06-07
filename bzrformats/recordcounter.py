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

"""Record counting support for showing progress of revision fetch."""


class RecordCounter:
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

        # Users of RecordCounter instance update progress bar every
        # _STEP_ records. We choose are reasonably high number to keep
        # display updates from being too frequent. This is an odd number
        # to ensure that the last digit of the records fetched in
        # fetches vs estimate ratio changes periodically.
        self.STEP = 7

    def is_initialized(self):
        return self.initialized

    def _estimate_max(self, key_count):
        """Estimate the maximum amount of 'inserting stream' work.

        This is just an estimate.
        """
        # Note: The magic number below is based of empirical data
        # based on 3 seperate projects. Estimatation can probably
        # be improved but this should work well for most cases.
        # The project used for the estimate (with approx. numbers) were:
        # lp:bzr with records_fetched = 7 * revs_required
        # lp:emacs with records_fetched = 8 * revs_required
        # bzr-svn checkout of lp:parrot = 10.63 * revs_required
        # Hence, 10.3 was chosen as for a realistic progress bar as:
        # 1. If records fetched is is lower than 10.3x then we simply complete
        #    with 10.3x. Under promise, over deliver.
        # 2. In case of remote fetch, when we start the count fetch vs estimate
        #    display with revs_required/estimate, having a multiplier with a
        #    decimal point produces a realistic looking _estimate_ number rather
        #    than using something like 3125/31250 (for 10x)
        # 3. Based on the above data, the possibility of overshooting this
        #    factor is minimal, and in case of an overshoot the estimate value
        #    should not need to be corrected too many times.
        return int(key_count * 10.3)

    def setup(self, key_count, current=0):
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
