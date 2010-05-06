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

"""Matchers for bzrlib.

Primarily test support, Matchers are used by self.assertThat in the bzrlib
test suite. A matcher is a stateful test helper which can be used to determine
if a passed object 'matches', much like a regex. If the object does not match
the mismatch can be described in a human readable fashion. assertThat then
raises if a mismatch occurs, showing the description as the assertion error.

Matchers are designed to be more reusable and composable than layered
assertions in Test Case objects, so they are recommended for new testing work.
"""

__all__ = [
    'ReturnsCallableLeavingObjectUnlocked',
    ]

from testtools.matchers import Mismatch, Matcher


class ReturnsCallableLeavingObjectUnlocked(Matcher):
    """A matcher that checks for the pattern we want lock* methods to have:

    They should return a callable.
    Calling that callable should unlock the original object.

    :ivar lockable_thing: The object which can be locked that will be
        inspected.
    """

    def __init__(self, lockable_thing):
        Matcher.__init__(self)
        self.lockable_thing = lockable_thing

    def __str__(self):
        return ('ReturnsCallableLeavingObjectUnlocked(lockable_thing=%s)' % 
            self.lockable_thing)

    def match(self, lock_method):
        lock_method()()
        if self.lockable_thing.is_locked():
            return _IsLocked(self.lockable_thing)
        return None


class _IsLocked(Mismatch):
    """Something is locked."""

    def __init__(self, lockable_thing):
        self.lockable_thing = lockable_thing

    def describe(self):
        return "%s is locked" % self.lockable_thing
