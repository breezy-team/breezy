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

MODULES_TO_TEST = []
MODULES_TO_DOCTEST = []

def selftest(verbose=False):
    from unittest import TestLoader, TestSuite
    import bzrlib, bzrlib.store, bzrlib.inventory, bzrlib.branch
    import bzrlib.osutils, bzrlib.commands, bzrlib.merge3, bzrlib.plugin
    global MODULES_TO_TEST, MODULES_TO_DOCTEST

    import bzrlib.selftest.whitebox
    import bzrlib.selftest.blackbox
    import bzrlib.selftest.versioning
    import bzrlib.selftest.testmerge3
    import bzrlib.selftest.testhashcache
    import bzrlib.selftest.testrevisionnamespaces
    import bzrlib.selftest.testbranch
    import bzrlib.selftest.teststatus
    import bzrlib.selftest.testinv
    import bzrlib.merge_core
    from doctest import DocTestSuite
    import os
    import shutil
    import time
    import sys
    import unittest

    for m in (bzrlib.store, bzrlib.inventory, bzrlib.branch,
              bzrlib.osutils, bzrlib.commands, bzrlib.merge3):
        if m not in MODULES_TO_DOCTEST:
            MODULES_TO_DOCTEST.append(m)
            
    for m in (bzrlib.selftest.whitebox,
              bzrlib.selftest.versioning,
              bzrlib.selftest.testinv,
              bzrlib.selftest.testmerge3,
              bzrlib.selftest.testhashcache,
              bzrlib.selftest.teststatus,
              bzrlib.selftest.blackbox,
              bzrlib.selftest.testhashcache,
              bzrlib.selftest.testrevisionnamespaces,
              bzrlib.selftest.testbranch,
              ):
        if m not in MODULES_TO_TEST:
            MODULES_TO_TEST.append(m)


    TestBase.BZRPATH = os.path.join(os.path.realpath(os.path.dirname(bzrlib.__path__[0])), 'bzr')
    print '%-30s %s' % ('bzr binary', TestBase.BZRPATH)

    print

    suite = TestSuite()

    # should also test bzrlib.merge_core, but they seem to be out of date with
    # the code.


    # XXX: python2.3's TestLoader() doesn't seem to find all the
    # tests; don't know why
    for m in MODULES_TO_TEST:
         suite.addTest(TestLoader().loadTestsFromModule(m))

    for m in (MODULES_TO_DOCTEST):
        suite.addTest(DocTestSuite(m))

    for p in bzrlib.plugin.all_plugins:
        if hasattr(p, 'test_suite'):
            suite.addTest(p.test_suite())

    suite.addTest(unittest.makeSuite(bzrlib.merge_core.MergeTest, 'test_'))

    return run_suite(suite, 'testbzr', verbose=verbose)



