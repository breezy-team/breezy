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


from testsweet import TestBase, run_suite, InTempDir


def selftest():
    from unittest import TestLoader, TestSuite
    import bzrlib, bzrlib.store, bzrlib.inventory, bzrlib.branch, bzrlib.osutils, bzrlib.commands

    import bzrlib.selftest.whitebox
    import bzrlib.selftest.blackbox
    import bzrlib.selftest.versioning
    import bzrlib.selftest.testmerge3
    import bzrlib.merge_core
    from doctest import DocTestSuite
    import os
    import shutil
    import time
    import sys

    TestBase.BZRPATH = os.path.join(os.path.realpath(os.path.dirname(bzrlib.__path__[0])), 'bzr')
    print '%-30s %s' % ('bzr binary', TestBase.BZRPATH)

    print

    suite = TestSuite()

    # should also test bzrlib.merge_core, but they seem to be out of date with
    # the code.


    # python2.3's TestLoader() doesn't seem to work well; don't know why

    for m in (bzrlib.store,
              bzrlib.inventory,
              bzrlib.branch,
              bzrlib.osutils, 
              bzrlib.commands, 
              bzrlib.merge3):
        suite.addTest(DocTestSuite(m))

    for cl in (bzrlib.selftest.whitebox.TEST_CLASSES 
               + bzrlib.selftest.versioning.TEST_CLASSES
               + bzrlib.selftest.testmerge3.TEST_CLASSES
               + bzrlib.selftest.blackbox.TEST_CLASSES):
        suite.addTest(cl())

    return run_suite(suite)



