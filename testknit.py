# Copyright (C) 2005 by Canonical Ltd

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




"""test case for knit/weave algorithm"""


from testsweet import TestBase
from knit import Knit


# texts for use in testing
TEXT_0 = ["Hello world"]
TEXT_1 = ["Hello world",
          "A second line"]


class Easy(TestBase):
    def runTest(self):
        k = Knit()


class StoreText(TestBase):
    """Store and retrieve a simple text."""
    def runTest(self):
        k = Knit()
        k.add(TEXT_0)
        self.assertEqual(k.get(), TEXT_0)


def testknit():
    import testsweet
    from unittest import TestSuite, TestLoader
    import testknit

    tl = TestLoader()
    suite = TestSuite()
    suite.addTest(tl.loadTestsFromModule(testknit))
    
    return testsweet.run_suite(suite)


if __name__ == '__main__':
    import sys
    sys.exit(testknit())
    
