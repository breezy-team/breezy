# Copyright (C) 2004, 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib.selftest import TestCase
from bzrlib.commands import display_command
import errno

class TestCommands(TestCase):
    def test_display_command(self):
        """EPIPE message is selectively suppressed"""
        def pipe_thrower():
            raise IOError(errno.EPIPE, "Bogus pipe error")
        self.assertRaises(IOError, pipe_thrower)
        @display_command
        def non_thrower():
            pipe_thrower()
        non_thrower()
        @display_command
        def other_thrower():
            raise IOError(errno.ESPIPE, "Bogus pipe error")
        self.assertRaises(IOError, other_thrower)

