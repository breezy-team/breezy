# Copyright (C) 2006 by Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Document what this test file is expecting to test here.

If you need more than one line, make the first line a good sentence on its
own and add more explanation here, like this.

Be sure to register your new test script in bzrlib/tests/__init__.py -
search for sampler in there.
"""

# import system imports here
import os
import sys

#import bzrlib specific imports here
from bzrlib.tests import TestCaseInTempDir


# Now we need a test script:
class DemoTest(TestCaseInTempDir):

    def test_nothing(self):
        self.assertEqual(1,1)
