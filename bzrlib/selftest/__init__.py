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


from cStringIO import StringIO
import difflib
import errno
import logging
import os
import re
import shutil
import sys
import tempfile
import unittest
import time

import bzrlib.commands
import bzrlib.trace
import bzrlib.fetch
import bzrlib.osutils as osutils
from bzrlib.selftest import TestUtil
from bzrlib.selftest.TestUtil import TestLoader, TestSuite
from bzrlib.selftest.treeshape import build_tree_contents

MODULES_TO_TEST = []
MODULES_TO_DOCTEST = []

from logging import debug, warning, error


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

    def _elapsedTime(self):
        return "(Took %.3fs)" % (time.time() - self._start_time)

    def startTest(self, test):
        unittest.TestResult.startTest(self, test)
        # TODO: Maybe show test.shortDescription somewhere?
        what = test.shortDescription() or test.id()        
        if self.showAll:
            self.stream.write('%-70.70s' % what)
        self.stream.flush()
        self._start_time = time.time()

    def addError(self, test, err):
        unittest.TestResult.addError(self, test, err)
        if self.showAll:
            self.stream.writeln("ERROR %s" % self._elapsedTime())
        elif self.dots:
            self.stream.write('E')
        self.stream.flush()

    def addFailure(self, test, err):
        unittest.TestResult.addFailure(self, test, err)
        if self.showAll:
            self.stream.writeln("FAIL %s" % self._elapsedTime())
        elif self.dots:
            self.stream.write('F')
        self.stream.flush()

    def addSuccess(self, test):
        if self.showAll:
            self.stream.writeln('OK %s' % self._elapsedTime())
        elif self.dots:
            self.stream.write('~')
        self.stream.flush()
        unittest.TestResult.addSuccess(self, test)

    def printErrorList(self, flavour, errors):
        for test, err in errors:
            self.stream.writeln(self.separator1)
            self.stream.writeln("%s: %s" % (flavour,self.getDescription(test)))
            if hasattr(test, '_get_log'):
                self.stream.writeln()
                self.stream.writeln('log from this test:')
                print >>self.stream, test._get_log()
            self.stream.writeln(self.separator2)
            self.stream.writeln("%s" % err)


class TextTestRunner(unittest.TextTestRunner):
    stop_on_failure = False

    def _makeResult(self):
        result = _MyResult(self.stream, self.descriptions, self.verbosity)
        if self.stop_on_failure:
            result = EarlyStoppingTestResultAdapter(result)
        return result


def iter_suite_tests(suite):
    """Return all tests in a suite, recursing through nested suites"""
    for item in suite._tests:
        if isinstance(item, unittest.TestCase):
            yield item
        elif isinstance(item, unittest.TestSuite):
            for r in iter_suite_tests(item):
                yield r
        else:
            raise Exception('unknown object %r inside test suite %r'
                            % (item, suite))


class TestSkipped(Exception):
    """Indicates that a test was intentionally skipped, rather than failing."""
    # XXX: Not used yet


class CommandFailed(Exception):
    pass

class TestCase(unittest.TestCase):
    """Base class for bzr unit tests.
    
    Tests that need access to disk resources should subclass 
    TestCaseInTempDir not TestCase.

    Error and debug log messages are redirected from their usual
    location into a temporary file, the contents of which can be
    retrieved by _get_log().  We use a real OS file, not an in-memory object,
    so that it can also capture file IO.  When the test completes this file
    is read into memory and removed from disk.
       
    There are also convenience functions to invoke bzr's command-line
    routine, and to build and check bzr trees.
   
    In addition to the usual method of overriding tearDown(), this class also
    allows subclasses to register functions into the _cleanups list, which is
    run in order as the object is torn down.  It's less likely this will be
    accidentally overlooked.
    """

    BZRPATH = 'bzr'
    _log_file_name = None
    _log_contents = ''

    def setUp(self):
        unittest.TestCase.setUp(self)
        self._cleanups = []
        self._cleanEnvironment()
        bzrlib.trace.disable_default_logging()
        self._startLogFile()

    def _ndiff_strings(self, a, b):
        """Return ndiff between two strings containing lines.
        
        A trailing newline is added if missing to make the strings
        print properly."""
        if b and b[-1] != '\n':
            b += '\n'
        if a and a[-1] != '\n':
            a += '\n'
        difflines = difflib.ndiff(a.splitlines(True),
                                  b.splitlines(True),
                                  linejunk=lambda x: False,
                                  charjunk=lambda x: False)
        return ''.join(difflines)

    def assertEqualDiff(self, a, b):
        """Assert two texts are equal, if not raise an exception.
        
        This is intended for use with multi-line strings where it can 
        be hard to find the differences by eye.
        """
        # TODO: perhaps override assertEquals to call this for strings?
        if a == b:
            return
        raise AssertionError("texts not equal:\n" + 
                             self._ndiff_strings(a, b))      

    def assertContainsRe(self, haystack, needle_re):
        """Assert that a contains something matching a regular expression."""
        if not re.search(needle_re, haystack):
            raise AssertionError('pattern "%s" not found in "%s"'
                    % (needle_re, haystack))

    def _startLogFile(self):
        """Send bzr and test log messages to a temporary file.

        The file is removed as the test is torn down.
        """
        fileno, name = tempfile.mkstemp(suffix='.log', prefix='testbzr')
        self._log_file = os.fdopen(fileno, 'w+')
        hdlr = logging.StreamHandler(self._log_file)
        hdlr.setLevel(logging.DEBUG)
        hdlr.setFormatter(logging.Formatter('%(levelname)8s  %(message)s'))
        logging.getLogger('').addHandler(hdlr)
        logging.getLogger('').setLevel(logging.DEBUG)
        self._log_hdlr = hdlr
        debug('opened log file %s', name)
        self._log_file_name = name
        self.addCleanup(self._finishLogFile)

    def _finishLogFile(self):
        """Finished with the log file.

        Read contents into memory, close, and delete.
        """
        self._log_file.seek(0)
        self._log_contents = self._log_file.read()
        os.remove(self._log_file_name)
        self._log_file = self._log_file_name = None

    def addCleanup(self, callable):
        """Arrange to run a callable when this case is torn down.

        Callables are run in the reverse of the order they are registered, 
        ie last-in first-out.
        """
        if callable in self._cleanups:
            raise ValueError("cleanup function %r already registered on %s" 
                    % (callable, self))
        self._cleanups.append(callable)

    def _cleanEnvironment(self):
        self.oldenv = os.environ.get('HOME', None)
        os.environ['HOME'] = os.getcwd()
        self.bzr_email = os.environ.get('BZREMAIL')
        if self.bzr_email is not None:
            del os.environ['BZREMAIL']
        self.email = os.environ.get('EMAIL')
        if self.email is not None:
            del os.environ['EMAIL']
        self.addCleanup(self._restoreEnvironment)

    def _restoreEnvironment(self):
        os.environ['HOME'] = self.oldenv
        if os.environ.get('BZREMAIL') is not None:
            del os.environ['BZREMAIL']
        if self.bzr_email is not None:
            os.environ['BZREMAIL'] = self.bzr_email
        if os.environ.get('EMAIL') is not None:
            del os.environ['EMAIL']
        if self.email is not None:
            os.environ['EMAIL'] = self.email

    def tearDown(self):
        logging.getLogger('').removeHandler(self._log_hdlr)
        bzrlib.trace.enable_default_logging()
        logging.debug('%s teardown', self.id())
        self._runCleanups()
        unittest.TestCase.tearDown(self)

    def _runCleanups(self):
        """Run registered cleanup functions. 

        This should only be called from TestCase.tearDown.
        """
        for callable in reversed(self._cleanups):
            callable()

    def log(self, *args):
        logging.debug(*args)

    def _get_log(self):
        """Return as a string the log for this test"""
        if self._log_file_name:
            return open(self._log_file_name).read()
        else:
            return self._log_contents

    def capture(self, cmd):
        """Shortcut that splits cmd into words, runs, and returns stdout"""
        return self.run_bzr_captured(cmd.split())[0]

    def run_bzr_captured(self, argv, retcode=0):
        """Invoke bzr and return (stdout, stderr).

        Useful for code that wants to check the contents of the
        output, the way error messages are presented, etc.

        This should be the main method for tests that want to exercise the
        overall behavior of the bzr application (rather than a unit test
        or a functional test of the library.)

        Much of the old code runs bzr by forking a new copy of Python, but
        that is slower, harder to debug, and generally not necessary.

        This runs bzr through the interface that catches and reports
        errors, and with logging set to something approximating the
        default, so that error reporting can be checked.

        argv -- arguments to invoke bzr
        retcode -- expected return code, or None for don't-care.
        """
        stdout = StringIO()
        stderr = StringIO()
        self.log('run bzr: %s', ' '.join(argv))
        handler = logging.StreamHandler(stderr)
        handler.setFormatter(bzrlib.trace.QuietFormatter())
        handler.setLevel(logging.INFO)
        logger = logging.getLogger('')
        logger.addHandler(handler)
        try:
            result = self.apply_redirected(None, stdout, stderr,
                                           bzrlib.commands.run_bzr_catch_errors,
                                           argv)
        finally:
            logger.removeHandler(handler)
        out = stdout.getvalue()
        err = stderr.getvalue()
        if out:
            self.log('output:\n%s', out)
        if err:
            self.log('errors:\n%s', err)
        if retcode is not None:
            self.assertEquals(result, retcode)
        return out, err

    def run_bzr(self, *args, **kwargs):
        """Invoke bzr, as if it were run from the command line.

        This should be the main method for tests that want to exercise the
        overall behavior of the bzr application (rather than a unit test
        or a functional test of the library.)

        This sends the stdout/stderr results into the test's log,
        where it may be useful for debugging.  See also run_captured.
        """
        retcode = kwargs.pop('retcode', 0)
        return self.run_bzr_captured(args, retcode)

    def check_inventory_shape(self, inv, shape):
        """Compare an inventory to a list of expected names.

        Fail if they are not precisely equal.
        """
        extras = []
        shape = list(shape)             # copy
        for path, ie in inv.entries():
            name = path.replace('\\', '/')
            if ie.kind == 'dir':
                name = name + '/'
            if name in shape:
                shape.remove(name)
            else:
                extras.append(name)
        if shape:
            self.fail("expected paths not found in inventory: %r" % shape)
        if extras:
            self.fail("unexpected paths found in inventory: %r" % extras)

    def apply_redirected(self, stdin=None, stdout=None, stderr=None,
                         a_callable=None, *args, **kwargs):
        """Call callable with redirected std io pipes.

        Returns the return code."""
        if not callable(a_callable):
            raise ValueError("a_callable must be callable.")
        if stdin is None:
            stdin = StringIO("")
        if stdout is None:
            if hasattr(self, "_log_file"):
                stdout = self._log_file
            else:
                stdout = StringIO()
        if stderr is None:
            if hasattr(self, "_log_file"):
                stderr = self._log_file
            else:
                stderr = StringIO()
        real_stdin = sys.stdin
        real_stdout = sys.stdout
        real_stderr = sys.stderr
        try:
            sys.stdout = stdout
            sys.stderr = stderr
            sys.stdin = stdin
            return a_callable(*args, **kwargs)
        finally:
            sys.stdout = real_stdout
            sys.stderr = real_stderr
            sys.stdin = real_stdin


BzrTestBase = TestCase

     
class TestCaseInTempDir(TestCase):
    """Derived class that runs a test within a temporary directory.

    This is useful for tests that need to create a branch, etc.

    The directory is created in a slightly complex way: for each
    Python invocation, a new temporary top-level directory is created.
    All test cases create their own directory within that.  If the
    tests complete successfully, the directory is removed.

    InTempDir is an old alias for FunctionalTestCase.
    """

    TEST_ROOT = None
    _TEST_NAME = 'test'
    OVERRIDE_PYTHON = 'python'

    def check_file_contents(self, filename, expect):
        self.log("check contents of file %s" % filename)
        contents = file(filename, 'r').read()
        if contents != expect:
            self.log("expected: %r" % expect)
            self.log("actually: %r" % contents)
            self.fail("contents of %s not as expected" % filename)

    def _make_test_root(self):
        if TestCaseInTempDir.TEST_ROOT is not None:
            return
        i = 0
        while True:
            root = 'test%04d.tmp' % i
            try:
                os.mkdir(root)
            except OSError, e:
                if e.errno == errno.EEXIST:
                    i += 1
                    continue
                else:
                    raise
            # successfully created
            TestCaseInTempDir.TEST_ROOT = os.path.abspath(root)
            break
        # make a fake bzr directory there to prevent any tests propagating
        # up onto the source directory's real branch
        os.mkdir(os.path.join(TestCaseInTempDir.TEST_ROOT, '.bzr'))

    def setUp(self):
        super(TestCaseInTempDir, self).setUp()
        self._make_test_root()
        _currentdir = os.getcwdu()
        short_id = self.id().replace('bzrlib.selftest.', '') \
                   .replace('__main__.', '')
        self.test_dir = os.path.join(self.TEST_ROOT, short_id)
        os.mkdir(self.test_dir)
        os.chdir(self.test_dir)
        def _leaveDirectory():
            os.chdir(_currentdir)
        self.addCleanup(_leaveDirectory)
        
    def build_tree(self, shape):
        """Build a test tree according to a pattern.

        shape is a sequence of file specifications.  If the final
        character is '/', a directory is created.

        This doesn't add anything to a branch.
        """
        # XXX: It's OK to just create them using forward slashes on windows?
        for name in shape:
            assert isinstance(name, basestring)
            if name[-1] == '/':
                os.mkdir(name[:-1])
            else:
                f = file(name, 'wt')
                print >>f, "contents of", name
                f.close()

    def build_tree_contents(self, shape):
        bzrlib.selftest.build_tree_contents(shape)

    def failUnlessExists(self, path):
        """Fail unless path, which may be abs or relative, exists."""
        self.failUnless(osutils.lexists(path))
        
    def assertFileEqual(self, content, path):
        """Fail if path does not contain 'content'."""
        self.failUnless(osutils.lexists(path))
        self.assertEqualDiff(content, open(path, 'r').read())
        

class MetaTestLog(TestCase):
    def test_logging(self):
        """Test logs are captured when a test fails."""
        logging.info('an info message')
        warning('something looks dodgy...')
        logging.debug('hello, test is running')
        ## assert 0


def filter_suite_by_re(suite, pattern):
    result = TestUtil.TestSuite()
    filter_re = re.compile(pattern)
    for test in iter_suite_tests(suite):
        if filter_re.search(test.id()):
            result.addTest(test)
    return result


def run_suite(suite, name='test', verbose=False, pattern=".*",
              stop_on_failure=False):
    TestCaseInTempDir._TEST_NAME = name
    if verbose:
        verbosity = 2
    else:
        verbosity = 1
    runner = TextTestRunner(stream=sys.stdout,
                            descriptions=0,
                            verbosity=verbosity)
    runner.stop_on_failure=stop_on_failure
    if pattern != '.*':
        suite = filter_suite_by_re(suite, pattern)
    result = runner.run(suite)
    # This is still a little bogus, 
    # but only a little. Folk not using our testrunner will
    # have to delete their temp directories themselves.
    if result.wasSuccessful():
        if TestCaseInTempDir.TEST_ROOT is not None:
            shutil.rmtree(TestCaseInTempDir.TEST_ROOT) 
    else:
        print "Failed tests working directories are in '%s'\n" % TestCaseInTempDir.TEST_ROOT
    return result.wasSuccessful()


def selftest(verbose=False, pattern=".*", stop_on_failure=True):
    """Run the whole test suite under the enhanced runner"""
    return run_suite(test_suite(), 'testbzr', verbose=verbose, pattern=pattern,
                     stop_on_failure=stop_on_failure)


def test_suite():
    """Build and return TestSuite for the whole program."""
    import bzrlib.store, bzrlib.inventory, bzrlib.branch
    import bzrlib.osutils, bzrlib.merge3, bzrlib.plugin
    from doctest import DocTestSuite

    global MODULES_TO_TEST, MODULES_TO_DOCTEST

    testmod_names = \
                  ['bzrlib.selftest.MetaTestLog',
                   'bzrlib.selftest.testgpg',
                   'bzrlib.selftest.testidentitymap',
                   'bzrlib.selftest.testinv',
                   'bzrlib.selftest.test_ancestry',
                   'bzrlib.selftest.test_commit',
                   'bzrlib.selftest.test_command',
                   'bzrlib.selftest.test_commit_merge',
                   'bzrlib.selftest.testconfig',
                   'bzrlib.selftest.versioning',
                   'bzrlib.selftest.testmerge3',
                   'bzrlib.selftest.testmerge',
                   'bzrlib.selftest.testhashcache',
                   'bzrlib.selftest.teststatus',
                   'bzrlib.selftest.testlog',
                   'bzrlib.selftest.testrevisionnamespaces',
                   'bzrlib.selftest.testbranch',
                   'bzrlib.selftest.testrevision',
                   'bzrlib.selftest.test_revision_info',
                   'bzrlib.selftest.test_merge_core',
                   'bzrlib.selftest.test_smart_add',
                   'bzrlib.selftest.test_bad_files',
                   'bzrlib.selftest.testdiff',
                   'bzrlib.selftest.test_parent',
                   'bzrlib.selftest.test_xml',
                   'bzrlib.selftest.test_weave',
                   'bzrlib.selftest.testfetch',
                   'bzrlib.selftest.whitebox',
                   'bzrlib.selftest.teststore',
                   'bzrlib.selftest.blackbox',
                   'bzrlib.selftest.testsampler',
                   'bzrlib.selftest.testtransactions',
                   'bzrlib.selftest.testtransport',
                   'bzrlib.selftest.testgraph',
                   'bzrlib.selftest.testworkingtree',
                   'bzrlib.selftest.test_upgrade',
                   'bzrlib.selftest.test_conflicts',
                   'bzrlib.selftest.testtestament',
                   'bzrlib.selftest.testannotate',
                   'bzrlib.selftest.testrevprops',
                   'bzrlib.selftest.testoptions',
                   'bzrlib.selftest.testhttp',
                   'bzrlib.selftest.testnonascii',
                   'bzrlib.selftest.testreweave',
                   'bzrlib.selftest.testtsort',
                   ]

    for m in (bzrlib.store, bzrlib.inventory, bzrlib.branch,
              bzrlib.osutils, bzrlib.commands, bzrlib.merge3,
              bzrlib.errors,
              ):
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

