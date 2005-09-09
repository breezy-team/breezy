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


"""Enhanced layer on unittest.

This does several things:

* nicer reporting as tests run

* test code can log messages into a buffer that is recorded to disk
  and displayed if the test fails

* tests can be run in a separate directory, which is useful for code that
  wants to create files

* utilities to run external commands and check their return code
  and/or output

Test cases should normally subclass testsweet.TestCase.  The test runner should
call runsuite().

This is meant to become independent of bzr, though that's not quite
true yet.
"""  

import unittest
import sys
from bzrlib.selftest import TestUtil

# XXX: Don't need this anymore now we depend on python2.4
def _need_subprocess():
    sys.stderr.write("sorry, this test suite requires the subprocess module\n"
                     "this is shipped with python2.4 and available separately for 2.3\n")
    

class CommandFailed(Exception):
    pass


class TestSkipped(Exception):
    """Indicates that a test was intentionally skipped, rather than failing."""
    # XXX: Not used yet


class EarlyStoppingTestResultAdapter(object):
    """An adapter for TestResult to stop at the first first failure or error"""

    def __init__(self, result):
        self._result = result

    def addError(self, test, err):
        self._result.addError(test, err)
        self._result.stop()

    def addFailure(self, test, err):
        self._result.addFailure(test, err)
        self._result.stop()

    def __getattr__(self, name):
        return getattr(self._result, name)

    def __setattr__(self, name, value):
        if name == '_result':
            object.__setattr__(self, name, value)
        return setattr(self._result, name, value)


class _MyResult(unittest._TextTestResult):
    """
    Custom TestResult.

    No special behaviour for now.
    """

    def startTest(self, test):
        unittest.TestResult.startTest(self, test)
        # TODO: Maybe show test.shortDescription somewhere?
        what = test.id()
        # python2.3 has the bad habit of just "runit" for doctests
        if what == 'runit':
            what = test.shortDescription()
        if self.showAll:
            self.stream.write('%-60.60s' % what)
        self.stream.flush()

    def addError(self, test, err):
        super(_MyResult, self).addError(test, err)
        self.stream.flush()

    def addFailure(self, test, err):
        super(_MyResult, self).addFailure(test, err)
        self.stream.flush()

    def addSuccess(self, test):
        if self.showAll:
            self.stream.writeln('OK')
        elif self.dots:
            self.stream.write('~')
        self.stream.flush()
        unittest.TestResult.addSuccess(self, test)

    def printErrorList(self, flavour, errors):
        for test, err in errors:
            self.stream.writeln(self.separator1)
            self.stream.writeln("%s: %s" % (flavour,self.getDescription(test)))
            self.stream.writeln(self.separator2)
            self.stream.writeln("%s" % err)
            if hasattr(test, '_get_log'):
                self.stream.writeln()
                self.stream.writeln('log from this test:')
                print >>self.stream, test._get_log()


class TextTestRunner(unittest.TextTestRunner):

    def _makeResult(self):
        result = _MyResult(self.stream, self.descriptions, self.verbosity)
        return EarlyStoppingTestResultAdapter(result)


class filteringVisitor(TestUtil.TestVisitor):
    """I accruse all the testCases I visit that pass a regexp filter on id
    into my suite
    """

    def __init__(self, filter):
        import re
        TestUtil.TestVisitor.__init__(self)
        self._suite=None
        self.filter=re.compile(filter)

    def suite(self):
        """answer the suite we are building"""
        if self._suite is None:
            self._suite=TestUtil.TestSuite()
        return self._suite

    def visitCase(self, aCase):
        if self.filter.match(aCase.id()):
            self.suite().addTest(aCase)


def run_suite(suite, name='test', verbose=False, pattern=".*"):
    import shutil
    from bzrlib.selftest import TestCaseInTempDir
    TestCaseInTempDir._TEST_NAME = name
    if verbose:
        verbosity = 2
    else:
        verbosity = 1
    runner = TextTestRunner(stream=sys.stdout,
                            descriptions=0,
                            verbosity=verbosity)
    if not pattern or pattern == ".*":
        result = runner.run(suite)
    else:
        visitor = filteringVisitor(pattern)
        suite.visit(visitor)
        result = runner.run(visitor.suite())
    # This is still a little bogus, 
    # but only a little. Folk not using our testrunner will
    # have to delete their temp directories themselves.
    if result.wasSuccessful():
        if TestCaseInTempDir.TEST_ROOT is not None:
            shutil.rmtree(TestCaseInTempDir.TEST_ROOT) 
    else:
        print "Failed tests working directories are in '%s'\n" % TestCaseInTempDir.TEST_ROOT
    return result.wasSuccessful()
