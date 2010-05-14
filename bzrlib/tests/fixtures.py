# Copyright (C) 2005-2010 Canonical Ltd
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


"""Fixtures that can be used within tests.

Fixtures can be created during a test as a way to separate out creation of
objects to test.  Fixture objects can hold some state so that different 
objects created during a test instance can be related.  Normally a fixture
should live only for the duration of a single test.
"""


class UnicodeFactory(object):

    def __init__(self):
        self._counter = 0

    def make_short_string(self):
        """Return a new short unicode string."""
        self._counter += 1
        # use a mathematical symbol unlikely to be in 8-bit encodings
        return u"\N{SINE WAVE}%d" % self._counter
