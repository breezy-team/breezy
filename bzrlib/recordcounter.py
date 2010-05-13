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

"""Record counting support for showing progress of revision fetch"""

def _gen_printer(stream):
    count = 0
    for s in stream:
        count = count + 1
        yield s
    print "count is:", count, "###########"

class RecordCounter(object):
    def __init__(self):
        self.initialized = False
        self.current = 0
        self.key_count = 0
        self.max = 0
        self.STEP = 71

    def is_initialized(self):
        return self.initialized

    def setup(self, key_count, current):
        self.current = current
        self.key_count = key_count
        self.max = key_count * 10.3
        self.initialized = True

    def increment(self, count):
        self.current += count
        if self.current > self.max:
            self.max += self.key_count

