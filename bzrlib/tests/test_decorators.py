# Copyright (C) 2006 Canonical Ltd

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


"""Tests for decorator functions"""

from bzrlib.decorators import needs_read_lock
from bzrlib.tests import TestCase


class DecoratorSample(object):
    """Sample class that uses decorators.

    This doesn't actually work because the class doesn't have the 
    requiste lock_read()/unlock() methods.
    """

    @needs_read_lock
    def frob(self):
        """Frob the sample object"""


class TestDecoratorDocs(TestCase):
    """Test method decorators"""

    def test_read_lock_passthrough(self):
        """@needs_read_lock exposes underlying name and doc."""
        sam = DecoratorSample()
        self.assertEqual(sam.frob.__name__, 'frob')
        self.assertEqual(sam.frob.__doc__, 
                'Frob the sample object')
