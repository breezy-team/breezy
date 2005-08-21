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
import bzrlib.commands
import bzrlib.fetch

MODULES_TO_TEST = []
MODULES_TO_DOCTEST = []


class BzrTestBase(InTempDir):
    """bzr-specific test base class"""
    def run_bzr(self, *args, **kwargs):
        retcode = kwargs.get('retcode', 0)
        self.assertEquals(bzrlib.commands.run_bzr(args), retcode)
        

def selftest(verbose=False):
    from unittest import TestLoader, TestSuite
    import bzrlib, bzrlib.store, bzrlib.inventory, bzrlib.branch
    import bzrlib.osutils, bzrlib.commands, bzrlib.merge3, bzrlib.plugin
    from doctest import DocTestSuite
    import os
    import shutil
    import time
    import sys
    import unittest

    global MODULES_TO_TEST, MODULES_TO_DOCTEST

    testmod_names = \
                  ['bzrlib.selftest.whitebox',
                   'bzrlib.selftest.versioning',
                   'bzrlib.selftest.testinv',
                   'bzrlib.selftest.testmerge3',
                   'bzrlib.selftest.testhashcache',
                   'bzrlib.selftest.teststatus',
                   'bzrlib.selftest.testlog',
                   'bzrlib.selftest.blackbox',
                   'bzrlib.selftest.testrevisionnamespaces',
                   'bzrlib.selftest.testbranch',
                   'bzrlib.selftest.testrevision',
                   'bzrlib.merge_core',
                   'bzrlib.selftest.testdiff',
                   'bzrlib.fetch'
                   ]

    # XXX: should also test bzrlib.merge_core, but they seem to be out
    # of date with the code.

    for m in (bzrlib.store, bzrlib.inventory, bzrlib.branch,
              bzrlib.osutils, bzrlib.commands, bzrlib.merge3):
        if m not in MODULES_TO_DOCTEST:
            MODULES_TO_DOCTEST.append(m)

    
    TestBase.BZRPATH = os.path.join(os.path.realpath(os.path.dirname(bzrlib.__path__[0])), 'bzr')
    print '%-30s %s' % ('bzr binary', TestBase.BZRPATH)

    print

    suite = TestSuite()

    suite.addTest(TestLoader().loadTestsFromNames(testmod_names))

    for m in MODULES_TO_TEST:
         suite.addTest(TestLoader().loadTestsFromModule(m))

    for m in (MODULES_TO_DOCTEST):
        suite.addTest(DocTestSuite(m))

    for p in bzrlib.plugin.all_plugins:
        if hasattr(p, 'test_suite'):
            suite.addTest(p.test_suite())

    import bzrlib.merge_core
    suite.addTest(unittest.makeSuite(bzrlib.merge_core.MergeTest, 'test_'))

    return run_suite(suite, 'testbzr', verbose=verbose)



