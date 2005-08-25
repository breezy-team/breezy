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


from testsweet import TestCase, run_suite, InTempDir, FunctionalTestCase
import bzrlib.commands
import bzrlib.fetch

MODULES_TO_TEST = []
MODULES_TO_DOCTEST = []


class BzrTestBase(InTempDir):
    """bzr-specific test base class"""
    def run_bzr(self, *args, **kwargs):
        retcode = kwargs.get('retcode', 0)
        result = self.apply_redirected(None, None, None,
                                       bzrlib.commands.run_bzr, args)
        self.assertEquals(result, retcode)
        

def selftest(verbose=False, pattern=".*"):
    return run_suite(test_suite(), 'testbzr', verbose=verbose, pattern=pattern)


def test_suite():
    from bzrlib.selftest.TestUtil import TestLoader, TestSuite
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
                   'bzrlib.selftest.testfetch',
                   'bzrlib.selftest.testinv',
                   'bzrlib.selftest.testmerge3',
                   'bzrlib.selftest.testhashcache',
                   'bzrlib.selftest.teststatus',
                   'bzrlib.selftest.testlog',
                   'bzrlib.selftest.blackbox',
                   'bzrlib.selftest.testrevisionnamespaces',
                   'bzrlib.selftest.testbranch',
                   'bzrlib.selftest.testrevision',
                   'bzrlib.selftest.test_merge_core',
                   'bzrlib.selftest.test_smart_add',
                   'bzrlib.selftest.testdiff',
                   'bzrlib.fetch'
                   ]

    for m in (bzrlib.store, bzrlib.inventory, bzrlib.branch,
              bzrlib.osutils, bzrlib.commands, bzrlib.merge3):
        if m not in MODULES_TO_DOCTEST:
            MODULES_TO_DOCTEST.append(m)

    TestCase.BZRPATH = os.path.join(os.path.realpath(os.path.dirname(bzrlib.__path__[0])), 'bzr')
    print '%-30s %s' % ('bzr binary', TestCase.BZRPATH)
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
    return suite

