# Copyright (C) 2006 Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

"""Document what this test file is expecting to test here.

If you need more than one line, make the first line a good sentence on its
own and add more explanation here, like this.

Be sure to register your new test script in breezy/tests/__init__.py -
search for sampler in there.
"""

from breezy.tests import TestCaseInTempDir


# Now we need a test script:
class DemoTest(TestCaseInTempDir):
    """A demo test class used as a template for new test modules."""

    def test_nothing(self):
        """A simple test that always passes to demonstrate test structure."""
        self.assertEqual(1, 1)
