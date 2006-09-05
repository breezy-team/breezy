# Copyright (C) 2005, 2006 by Canonical Ltd
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


# TODO: Perhaps there should be an API to find out if bzr running under the
# test suite -- some plugins might want to avoid making intrusive changes if
# this is the case.  However, we want behaviour under to test to diverge as
# little as possible, so this should be used rarely if it's added at all.
# (Suggestion from j-a-meinel, 2005-11-24)

# NOTE: Some classes in here use camelCaseNaming() rather than
# underscore_naming().  That's for consistency with unittest; it's not the
# general style of bzrlib.  Please continue that consistency when adding e.g.
# new assertFoo() methods.

import codecs
from cStringIO import StringIO
import difflib
import doctest
import errno
import logging
import os
import re
import shlex
import stat
from subprocess import Popen, PIPE
import sys
import tempfile
import unittest
import time


import bzrlib.branch
import bzrlib.bzrdir as bzrdir
import bzrlib.commands
import bzrlib.bundle.serializer
import bzrlib.errors as errors
import bzrlib.inventory
import bzrlib.iterablefile
import bzrlib.lockdir
try:
    import bzrlib.lsprof
except ImportError:
    # lsprof not available
    pass
from bzrlib.merge import merge_inner
import bzrlib.merge3
import bzrlib.osutils
import bzrlib.osutils as osutils
import bzrlib.plugin
import bzrlib.progress as progress
from bzrlib.revision import common_ancestor
from bzrlib.revisionspec import RevisionSpec
import bzrlib.store
from bzrlib import symbol_versioning
import bzrlib.trace
from bzrlib.transport import get_transport
import bzrlib.transport
from bzrlib.transport.local import LocalRelpathServer
from bzrlib.transport.readonly import ReadonlyServer
from bzrlib.trace import mutter
from bzrlib.tests import TestUtil
from bzrlib.tests.TestUtil import (
                          TestSuite,
                          TestLoader,
                          )
from bzrlib.tests.treeshape import build_tree_contents
import bzrlib.urlutils as urlutils
from bzrlib.workingtree import WorkingTree, WorkingTreeFormat2

default_transport = LocalRelpathServer

MODULES_TO_TEST = []
MODULES_TO_DOCTEST = [
                      bzrlib.branch,
                      bzrlib.bundle.serializer,
                      bzrlib.commands,
                      bzrlib.errors,
                      bzrlib.inventory,
                      bzrlib.iterablefile,
                      bzrlib.lockdir,
                      bzrlib.merge3,
                      bzrlib.option,
                      bzrlib.osutils,
                      bzrlib.store
                      ]


def packages_to_test():
    """Return a list of packages to test.

    The packages are not globally imported so that import failures are
    triggered when running selftest, not when importing the command.
    """
    import bzrlib.doc
    import bzrlib.tests.blackbox
    import bzrlib.tests.branch_implementations
    import bzrlib.tests.bzrdir_implementations
    import bzrlib.tests.interrepository_implementations
    import bzrlib.tests.interversionedfile_implementations
    import bzrlib.tests.intertree_implementations
    import bzrlib.tests.repository_implementations
    import bzrlib.tests.revisionstore_implementations
    import bzrlib.tests.tree_implementations
    import bzrlib.tests.workingtree_implementations
    return [
            bzrlib.doc,
            bzrlib.tests.blackbox,
            bzrlib.tests.branch_implementations,
            bzrlib.tests.bzrdir_implementations,
            bzrlib.tests.interrepository_implementations,
            bzrlib.tests.interversionedfile_implementations,
            bzrlib.tests.intertree_implementations,
            bzrlib.tests.repository_implementations,
            bzrlib.tests.revisionstore_implementations,
            bzrlib.tests.tree_implementations,
            bzrlib.tests.workingtree_implementations,
            ]


class _MyResult(unittest._TextTestResult):
    """Custom TestResult.

    Shows output in a different format, including displaying runtime for tests.
    """
    stop_early = False
    
    def __init__(self, stream, descriptions, verbosity, pb=None,
                 bench_history=None):
        """Construct new TestResult.

        :param bench_history: Optionally, a writable file object to accumulate
            benchmark results.
        """
        unittest._TextTestResult.__init__(self, stream, descriptions, verbosity)
        self.pb = pb
        if bench_history is not None:
            from bzrlib.version import _get_bzr_source_tree
            src_tree = _get_bzr_source_tree()
            if src_tree:
                revision_id = src_tree.last_revision()
            else:
                # XXX: If there's no branch, what should we do?
                revision_id = ''
            bench_history.write("--date %s %s\n" % (time.time(), revision_id))
        self._bench_history = bench_history
    
    def extractBenchmarkTime(self, testCase):
        """Add a benchmark time for the current test case."""
        self._benchmarkTime = getattr(testCase, "_benchtime", None)
    
    def _elapsedTestTimeString(self):
        """Return a time string for the overall time the current test has taken."""
        return self._formatTime(time.time() - self._start_time)

    def _testTimeString(self):
        if self._benchmarkTime is not None:
            return "%s/%s" % (
                self._formatTime(self._benchmarkTime),
                self._elapsedTestTimeString())
        else:
            return "      %s" % self._elapsedTestTimeString()

    def _formatTime(self, seconds):
        """Format seconds as milliseconds with leading spaces."""
        return "%5dms" % (1000 * seconds)

    def _ellipsise_unimportant_words(self, a_string, final_width,
                                   keep_start=False):
        """Add ellipses (sp?) for overly long strings.
        
        :param keep_start: If true preserve the start of a_string rather
                           than the end of it.
        """
        if keep_start:
            if len(a_string) > final_width:
                result = a_string[:final_width-3] + '...'
            else:
                result = a_string
        else:
            if len(a_string) > final_width:
                result = '...' + a_string[3-final_width:]
            else:
                result = a_string
        return result.ljust(final_width)

    def startTest(self, test):
        unittest.TestResult.startTest(self, test)
        # In a short description, the important words are in
        # the beginning, but in an id, the important words are
        # at the end
        SHOW_DESCRIPTIONS = False

        if not self.showAll and self.dots and self.pb is not None:
            final_width = 13
        else:
            final_width = osutils.terminal_width()
            final_width = final_width - 15 - 8
        what = None
        if SHOW_DESCRIPTIONS:
            what = test.shortDescription()
            if what:
                what = self._ellipsise_unimportant_words(what, final_width, keep_start=True)
        if what is None:
            what = test.id()
            if what.startswith('bzrlib.tests.'):
                what = what[13:]
            what = self._ellipsise_unimportant_words(what, final_width)
        if self.showAll:
            self.stream.write(what)
        elif self.dots and self.pb is not None:
            self.pb.update(what, self.testsRun - 1, None)
        self.stream.flush()
        self._recordTestStartTime()

    def _recordTestStartTime(self):
        """Record that a test has started."""
        self._start_time = time.time()

    def addError(self, test, err):
        if isinstance(err[1], TestSkipped):
            return self.addSkipped(test, err)    
        unittest.TestResult.addError(self, test, err)
        self.extractBenchmarkTime(test)
        if self.showAll:
            self.stream.writeln("ERROR %s" % self._testTimeString())
        elif self.dots and self.pb is None:
            self.stream.write('E')
        elif self.dots:
            self.pb.update(self._ellipsise_unimportant_words('ERROR', 13), self.testsRun, None)
            self.pb.note(self._ellipsise_unimportant_words(
                            test.id() + ': ERROR',
                            osutils.terminal_width()))
        self.stream.flush()
        if self.stop_early:
            self.stop()

    def addFailure(self, test, err):
        unittest.TestResult.addFailure(self, test, err)
        self.extractBenchmarkTime(test)
        if self.showAll:
            self.stream.writeln(" FAIL %s" % self._testTimeString())
        elif self.dots and self.pb is None:
            self.stream.write('F')
        elif self.dots:
            self.pb.update(self._ellipsise_unimportant_words('FAIL', 13), self.testsRun, None)
            self.pb.note(self._ellipsise_unimportant_words(
                            test.id() + ': FAIL',
                            osutils.terminal_width()))
        self.stream.flush()
        if self.stop_early:
            self.stop()

    def addSuccess(self, test):
        self.extractBenchmarkTime(test)
        if self._bench_history is not None:
            if self._benchmarkTime is not None:
                self._bench_history.write("%s %s\n" % (
                    self._formatTime(self._benchmarkTime),
                    test.id()))
        if self.showAll:
            self.stream.writeln('   OK %s' % self._testTimeString())
            for bench_called, stats in getattr(test, '_benchcalls', []):
                self.stream.writeln('LSProf output for %s(%s, %s)' % bench_called)
                stats.pprint(file=self.stream)
        elif self.dots and self.pb is None:
            self.stream.write('~')
        elif self.dots:
            self.pb.update(self._ellipsise_unimportant_words('OK', 13), self.testsRun, None)
        self.stream.flush()
        unittest.TestResult.addSuccess(self, test)

    def addSkipped(self, test, skip_excinfo):
        self.extractBenchmarkTime(test)
        if self.showAll:
            print >>self.stream, ' SKIP %s' % self._testTimeString()
            print >>self.stream, '     %s' % skip_excinfo[1]
        elif self.dots and self.pb is None:
            self.stream.write('S')
        elif self.dots:
            self.pb.update(self._ellipsise_unimportant_words('SKIP', 13), self.testsRun, None)
        self.stream.flush()
        # seems best to treat this as success from point-of-view of unittest
        # -- it actually does nothing so it barely matters :)
        try:
            test.tearDown()
        except KeyboardInterrupt:
            raise
        except:
            self.addError(test, test.__exc_info())
        else:
            unittest.TestResult.addSuccess(self, test)

    def printErrorList(self, flavour, errors):
        for test, err in errors:
            self.stream.writeln(self.separator1)
            self.stream.writeln("%s: %s" % (flavour, self.getDescription(test)))
            if getattr(test, '_get_log', None) is not None:
                print >>self.stream
                print >>self.stream, \
                        ('vvvv[log from %s]' % test.id()).ljust(78,'-')
                print >>self.stream, test._get_log()
                print >>self.stream, \
                        ('^^^^[log from %s]' % test.id()).ljust(78,'-')
            self.stream.writeln(self.separator2)
            self.stream.writeln("%s" % err)


class TextTestRunner(object):
    stop_on_failure = False

    def __init__(self,
                 stream=sys.stderr,
                 descriptions=0,
                 verbosity=1,
                 keep_output=False,
                 pb=None,
                 bench_history=None):
        self.stream = unittest._WritelnDecorator(stream)
        self.descriptions = descriptions
        self.verbosity = verbosity
        self.keep_output = keep_output
        self.pb = pb
        self._bench_history = bench_history

    def _makeResult(self):
        result = _MyResult(self.stream,
                           self.descriptions,
                           self.verbosity,
                           pb=self.pb,
                           bench_history=self._bench_history)
        result.stop_early = self.stop_on_failure
        return result

    def run(self, test):
        "Run the given test case or test suite."
        result = self._makeResult()
        startTime = time.time()
        if self.pb is not None:
            self.pb.update('Running tests', 0, test.countTestCases())
        test.run(result)
        stopTime = time.time()
        timeTaken = stopTime - startTime
        result.printErrors()
        self.stream.writeln(result.separator2)
        run = result.testsRun
        self.stream.writeln("Ran %d test%s in %.3fs" %
                            (run, run != 1 and "s" or "", timeTaken))
        self.stream.writeln()
        if not result.wasSuccessful():
            self.stream.write("FAILED (")
            failed, errored = map(len, (result.failures, result.errors))
            if failed:
                self.stream.write("failures=%d" % failed)
            if errored:
                if failed: self.stream.write(", ")
                self.stream.write("errors=%d" % errored)
            self.stream.writeln(")")
        else:
            self.stream.writeln("OK")
        if self.pb is not None:
            self.pb.update('Cleaning up', 0, 1)
        # This is still a little bogus, 
        # but only a little. Folk not using our testrunner will
        # have to delete their temp directories themselves.
        test_root = TestCaseInTempDir.TEST_ROOT
        if result.wasSuccessful() or not self.keep_output:
            if test_root is not None:
                # If LANG=C we probably have created some bogus paths
                # which rmtree(unicode) will fail to delete
                # so make sure we are using rmtree(str) to delete everything
                # except on win32, where rmtree(str) will fail
                # since it doesn't have the property of byte-stream paths
                # (they are either ascii or mbcs)
                if sys.platform == 'win32':
                    # make sure we are using the unicode win32 api
                    test_root = unicode(test_root)
                else:
                    test_root = test_root.encode(
                        sys.getfilesystemencoding())
                osutils.rmtree(test_root)
        else:
            if self.pb is not None:
                self.pb.note("Failed tests working directories are in '%s'\n",
                             test_root)
            else:
                self.stream.writeln(
                    "Failed tests working directories are in '%s'\n" %
                    test_root)
        TestCaseInTempDir.TEST_ROOT = None
        if self.pb is not None:
            self.pb.clear()
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


class CommandFailed(Exception):
    pass


class StringIOWrapper(object):
    """A wrapper around cStringIO which just adds an encoding attribute.
    
    Internally we can check sys.stdout to see what the output encoding
    should be. However, cStringIO has no encoding attribute that we can
    set. So we wrap it instead.
    """
    encoding='ascii'
    _cstring = None

    def __init__(self, s=None):
        if s is not None:
            self.__dict__['_cstring'] = StringIO(s)
        else:
            self.__dict__['_cstring'] = StringIO()

    def __getattr__(self, name, getattr=getattr):
        return getattr(self.__dict__['_cstring'], name)

    def __setattr__(self, name, val):
        if name == 'encoding':
            self.__dict__['encoding'] = val
        else:
            return setattr(self._cstring, name, val)


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

    _log_file_name = None
    _log_contents = ''
    # record lsprof data when performing benchmark calls.
    _gather_lsprof_in_benchmarks = False

    def __init__(self, methodName='testMethod'):
        super(TestCase, self).__init__(methodName)
        self._cleanups = []

    def setUp(self):
        unittest.TestCase.setUp(self)
        self._cleanEnvironment()
        bzrlib.trace.disable_default_logging()
        self._startLogFile()
        self._benchcalls = []
        self._benchtime = None

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

    def assertEqualDiff(self, a, b, message=None):
        """Assert two texts are equal, if not raise an exception.
        
        This is intended for use with multi-line strings where it can 
        be hard to find the differences by eye.
        """
        # TODO: perhaps override assertEquals to call this for strings?
        if a == b:
            return
        if message is None:
            message = "texts not equal:\n"
        raise AssertionError(message + 
                             self._ndiff_strings(a, b))      
        
    def assertEqualMode(self, mode, mode_test):
        self.assertEqual(mode, mode_test,
                         'mode mismatch %o != %o' % (mode, mode_test))

    def assertStartsWith(self, s, prefix):
        if not s.startswith(prefix):
            raise AssertionError('string %r does not start with %r' % (s, prefix))

    def assertEndsWith(self, s, suffix):
        """Asserts that s ends with suffix."""
        if not s.endswith(suffix):
            raise AssertionError('string %r does not end with %r' % (s, suffix))

    def assertContainsRe(self, haystack, needle_re):
        """Assert that a contains something matching a regular expression."""
        if not re.search(needle_re, haystack):
            raise AssertionError('pattern "%s" not found in "%s"'
                    % (needle_re, haystack))

    def assertNotContainsRe(self, haystack, needle_re):
        """Assert that a does not match a regular expression"""
        if re.search(needle_re, haystack):
            raise AssertionError('pattern "%s" found in "%s"'
                    % (needle_re, haystack))

    def assertSubset(self, sublist, superlist):
        """Assert that every entry in sublist is present in superlist."""
        missing = []
        for entry in sublist:
            if entry not in superlist:
                missing.append(entry)
        if len(missing) > 0:
            raise AssertionError("value(s) %r not present in container %r" % 
                                 (missing, superlist))

    def assertIs(self, left, right):
        if not (left is right):
            raise AssertionError("%r is not %r." % (left, right))

    def assertTransportMode(self, transport, path, mode):
        """Fail if a path does not have mode mode.
        
        If modes are not supported on this transport, the assertion is ignored.
        """
        if not transport._can_roundtrip_unix_modebits():
            return
        path_stat = transport.stat(path)
        actual_mode = stat.S_IMODE(path_stat.st_mode)
        self.assertEqual(mode, actual_mode,
            'mode of %r incorrect (%o != %o)' % (path, mode, actual_mode))

    def assertIsInstance(self, obj, kls):
        """Fail if obj is not an instance of kls"""
        if not isinstance(obj, kls):
            self.fail("%r is an instance of %s rather than %s" % (
                obj, obj.__class__, kls))

    def callDeprecated(self, expected, callable, *args, **kwargs):
        """Assert that a callable is deprecated in a particular way.

        :param expected: a list of the deprecation warnings expected, in order
        :param callable: The callable to call
        :param args: The positional arguments for the callable
        :param kwargs: The keyword arguments for the callable
        """
        local_warnings = []
        def capture_warnings(msg, cls, stacklevel=None):
            self.assertEqual(cls, DeprecationWarning)
            local_warnings.append(msg)
        method = symbol_versioning.warn
        symbol_versioning.set_warning_method(capture_warnings)
        try:
            result = callable(*args, **kwargs)
        finally:
            symbol_versioning.set_warning_method(method)
        self.assertEqual(expected, local_warnings)
        return result

    def _startLogFile(self):
        """Send bzr and test log messages to a temporary file.

        The file is removed as the test is torn down.
        """
        fileno, name = tempfile.mkstemp(suffix='.log', prefix='testbzr')
        self._log_file = os.fdopen(fileno, 'w+')
        self._log_nonce = bzrlib.trace.enable_test_log(self._log_file)
        self._log_file_name = name
        self.addCleanup(self._finishLogFile)

    def _finishLogFile(self):
        """Finished with the log file.

        Read contents into memory, close, and delete.
        """
        if self._log_file is None:
            return
        bzrlib.trace.disable_test_log(self._log_nonce)
        self._log_file.seek(0)
        self._log_contents = self._log_file.read()
        self._log_file.close()
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
        new_env = {
            'HOME': os.getcwd(),
            'APPDATA': os.getcwd(),
            'BZR_EMAIL': None,
            'BZREMAIL': None, # may still be present in the environment
            'EMAIL': None,
            'BZR_PROGRESS_BAR': None,
        }
        self.__old_env = {}
        self.addCleanup(self._restoreEnvironment)
        for name, value in new_env.iteritems():
            self._captureVar(name, value)

    def _captureVar(self, name, newvalue):
        """Set an environment variable, and reset it when finished."""
        self.__old_env[name] = osutils.set_or_unset_env(name, newvalue)

    def _restoreEnvironment(self):
        for name, value in self.__old_env.iteritems():
            osutils.set_or_unset_env(name, value)

    def tearDown(self):
        self._runCleanups()
        unittest.TestCase.tearDown(self)

    def time(self, callable, *args, **kwargs):
        """Run callable and accrue the time it takes to the benchmark time.
        
        If lsprofiling is enabled (i.e. by --lsprof-time to bzr selftest) then
        this will cause lsprofile statistics to be gathered and stored in
        self._benchcalls.
        """
        if self._benchtime is None:
            self._benchtime = 0
        start = time.time()
        try:
            if not self._gather_lsprof_in_benchmarks:
                return callable(*args, **kwargs)
            else:
                # record this benchmark
                ret, stats = bzrlib.lsprof.profile(callable, *args, **kwargs)
                stats.sort()
                self._benchcalls.append(((callable, args, kwargs), stats))
                return ret
        finally:
            self._benchtime += time.time() - start

    def _runCleanups(self):
        """Run registered cleanup functions. 

        This should only be called from TestCase.tearDown.
        """
        # TODO: Perhaps this should keep running cleanups even if 
        # one of them fails?
        for cleanup_fn in reversed(self._cleanups):
            cleanup_fn()

    def log(self, *args):
        mutter(*args)

    def _get_log(self):
        """Return as a string the log for this test"""
        if self._log_file_name:
            return open(self._log_file_name).read()
        else:
            return self._log_contents
        # TODO: Delete the log after it's been read in

    def capture(self, cmd, retcode=0):
        """Shortcut that splits cmd into words, runs, and returns stdout"""
        return self.run_bzr_captured(cmd.split(), retcode=retcode)[0]

    def run_bzr_captured(self, argv, retcode=0, encoding=None, stdin=None):
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

        :param argv: arguments to invoke bzr
        :param retcode: expected return code, or None for don't-care.
        :param encoding: encoding for sys.stdout and sys.stderr
        :param stdin: A string to be used as stdin for the command.
        """
        if encoding is None:
            encoding = bzrlib.user_encoding
        if stdin is not None:
            stdin = StringIO(stdin)
        stdout = StringIOWrapper()
        stderr = StringIOWrapper()
        stdout.encoding = encoding
        stderr.encoding = encoding

        self.log('run bzr: %r', argv)
        # FIXME: don't call into logging here
        handler = logging.StreamHandler(stderr)
        handler.setLevel(logging.INFO)
        logger = logging.getLogger('')
        logger.addHandler(handler)
        old_ui_factory = bzrlib.ui.ui_factory
        bzrlib.ui.ui_factory = bzrlib.tests.blackbox.TestUIFactory(
            stdout=stdout,
            stderr=stderr)
        bzrlib.ui.ui_factory.stdin = stdin
        try:
            result = self.apply_redirected(stdin, stdout, stderr,
                                           bzrlib.commands.run_bzr_catch_errors,
                                           argv)
        finally:
            logger.removeHandler(handler)
            bzrlib.ui.ui_factory = old_ui_factory

        out = stdout.getvalue()
        err = stderr.getvalue()
        if out:
            self.log('output:\n%r', out)
        if err:
            self.log('errors:\n%r', err)
        if retcode is not None:
            self.assertEquals(retcode, result)
        return out, err

    def run_bzr(self, *args, **kwargs):
        """Invoke bzr, as if it were run from the command line.

        This should be the main method for tests that want to exercise the
        overall behavior of the bzr application (rather than a unit test
        or a functional test of the library.)

        This sends the stdout/stderr results into the test's log,
        where it may be useful for debugging.  See also run_captured.

        :param stdin: A string to be used as stdin for the command.
        """
        retcode = kwargs.pop('retcode', 0)
        encoding = kwargs.pop('encoding', None)
        stdin = kwargs.pop('stdin', None)
        return self.run_bzr_captured(args, retcode=retcode, encoding=encoding, stdin=stdin)

    def run_bzr_decode(self, *args, **kwargs):
        if kwargs.has_key('encoding'):
            encoding = kwargs['encoding']
        else:
            encoding = bzrlib.user_encoding
        return self.run_bzr(*args, **kwargs)[0].decode(encoding)

    def run_bzr_error(self, error_regexes, *args, **kwargs):
        """Run bzr, and check that stderr contains the supplied regexes
        
        :param error_regexes: Sequence of regular expressions which 
            must each be found in the error output. The relative ordering
            is not enforced.
        :param args: command-line arguments for bzr
        :param kwargs: Keyword arguments which are interpreted by run_bzr
            This function changes the default value of retcode to be 3,
            since in most cases this is run when you expect bzr to fail.
        :return: (out, err) The actual output of running the command (in case you
                 want to do more inspection)

        Examples of use:
            # Make sure that commit is failing because there is nothing to do
            self.run_bzr_error(['no changes to commit'],
                               'commit', '-m', 'my commit comment')
            # Make sure --strict is handling an unknown file, rather than
            # giving us the 'nothing to do' error
            self.build_tree(['unknown'])
            self.run_bzr_error(['Commit refused because there are unknown files'],
                               'commit', '--strict', '-m', 'my commit comment')
        """
        kwargs.setdefault('retcode', 3)
        out, err = self.run_bzr(*args, **kwargs)
        for regex in error_regexes:
            self.assertContainsRe(err, regex)
        return out, err

    def run_bzr_subprocess(self, *args, **kwargs):
        """Run bzr in a subprocess for testing.

        This starts a new Python interpreter and runs bzr in there. 
        This should only be used for tests that have a justifiable need for
        this isolation: e.g. they are testing startup time, or signal
        handling, or early startup code, etc.  Subprocess code can't be 
        profiled or debugged so easily.

        :param retcode: The status code that is expected.  Defaults to 0.  If
            None is supplied, the status code is not checked.
        :param env_changes: A dictionary which lists changes to environment
            variables. A value of None will unset the env variable.
            The values must be strings. The change will only occur in the
            child, so you don't need to fix the environment after running.
        """
        env_changes = kwargs.get('env_changes', {})
        def cleanup_environment():
            for env_var, value in env_changes.iteritems():
                old_val = osutils.set_or_unset_env(env_var, value)

        bzr_path = os.path.dirname(os.path.dirname(bzrlib.__file__))+'/bzr'
        args = list(args)
        process = Popen([sys.executable, bzr_path]+args,
                         stdout=PIPE, stderr=PIPE,
                         preexec_fn=cleanup_environment)
        out = process.stdout.read()
        err = process.stderr.read()
        retcode = process.wait()
        supplied_retcode = kwargs.get('retcode', 0)
        if supplied_retcode is not None:
            assert supplied_retcode == retcode
        return [out, err]

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
            if getattr(self, "_log_file", None) is not None:
                stdout = self._log_file
            else:
                stdout = StringIO()
        if stderr is None:
            if getattr(self, "_log_file", None is not None):
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

    def merge(self, branch_from, wt_to):
        """A helper for tests to do a ui-less merge.

        This should move to the main library when someone has time to integrate
        it in.
        """
        # minimal ui-less merge.
        wt_to.branch.fetch(branch_from)
        base_rev = common_ancestor(branch_from.last_revision(),
                                   wt_to.branch.last_revision(),
                                   wt_to.branch.repository)
        merge_inner(wt_to.branch, branch_from.basis_tree(),
                    wt_to.branch.repository.revision_tree(base_rev),
                    this_tree=wt_to)
        wt_to.add_parent_tree_id(branch_from.last_revision())


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
            root = u'test%04d.tmp' % i
            try:
                os.mkdir(root)
            except OSError, e:
                if e.errno == errno.EEXIST:
                    i += 1
                    continue
                else:
                    raise
            # successfully created
            TestCaseInTempDir.TEST_ROOT = osutils.abspath(root)
            break
        # make a fake bzr directory there to prevent any tests propagating
        # up onto the source directory's real branch
        bzrdir.BzrDir.create_standalone_workingtree(TestCaseInTempDir.TEST_ROOT)

    def setUp(self):
        super(TestCaseInTempDir, self).setUp()
        self._make_test_root()
        _currentdir = os.getcwdu()
        # shorten the name, to avoid test failures due to path length
        short_id = self.id().replace('bzrlib.tests.', '') \
                   .replace('__main__.', '')[-100:]
        # it's possible the same test class is run several times for
        # parameterized tests, so make sure the names don't collide.  
        i = 0
        while True:
            if i > 0:
                candidate_dir = '%s/%s.%d' % (self.TEST_ROOT, short_id, i)
            else:
                candidate_dir = '%s/%s' % (self.TEST_ROOT, short_id)
            if os.path.exists(candidate_dir):
                i = i + 1
                continue
            else:
                self.test_dir = candidate_dir
                os.mkdir(self.test_dir)
                os.chdir(self.test_dir)
                break
        os.environ['HOME'] = self.test_dir
        os.environ['APPDATA'] = self.test_dir
        def _leaveDirectory():
            os.chdir(_currentdir)
        self.addCleanup(_leaveDirectory)
        
    def build_tree(self, shape, line_endings='native', transport=None):
        """Build a test tree according to a pattern.

        shape is a sequence of file specifications.  If the final
        character is '/', a directory is created.

        This assumes that all the elements in the tree being built are new.

        This doesn't add anything to a branch.
        :param line_endings: Either 'binary' or 'native'
                             in binary mode, exact contents are written
                             in native mode, the line endings match the
                             default platform endings.

        :param transport: A transport to write to, for building trees on 
                          VFS's. If the transport is readonly or None,
                          "." is opened automatically.
        """
        # It's OK to just create them using forward slashes on windows.
        if transport is None or transport.is_readonly():
            transport = get_transport(".")
        for name in shape:
            self.assert_(isinstance(name, basestring))
            if name[-1] == '/':
                transport.mkdir(urlutils.escape(name[:-1]))
            else:
                if line_endings == 'binary':
                    end = '\n'
                elif line_endings == 'native':
                    end = os.linesep
                else:
                    raise errors.BzrError('Invalid line ending request %r' % (line_endings,))
                content = "contents of %s%s" % (name.encode('utf-8'), end)
                # Technically 'put()' is the right command. However, put
                # uses an AtomicFile, which requires an extra rename into place
                # As long as the files didn't exist in the past, append() will
                # do the same thing as put()
                # On jam's machine, make_kernel_like_tree is:
                #   put:    4.5-7.5s (averaging 6s)
                #   append: 2.9-4.5s
                transport.append(urlutils.escape(name), StringIO(content))

    def build_tree_contents(self, shape):
        build_tree_contents(shape)

    def failUnlessExists(self, path):
        """Fail unless path, which may be abs or relative, exists."""
        self.failUnless(osutils.lexists(path))

    def failIfExists(self, path):
        """Fail if path, which may be abs or relative, exists."""
        self.failIf(osutils.lexists(path))
        
    def assertFileEqual(self, content, path):
        """Fail if path does not contain 'content'."""
        self.failUnless(osutils.lexists(path))
        # TODO: jam 20060427 Shouldn't this be 'rb'?
        self.assertEqualDiff(content, open(path, 'r').read())


class TestCaseWithTransport(TestCaseInTempDir):
    """A test case that provides get_url and get_readonly_url facilities.

    These back onto two transport servers, one for readonly access and one for
    read write access.

    If no explicit class is provided for readonly access, a
    ReadonlyTransportDecorator is used instead which allows the use of non disk
    based read write transports.

    If an explicit class is provided for readonly access, that server and the 
    readwrite one must both define get_url() as resolving to os.getcwd().
    """

    def __init__(self, methodName='testMethod'):
        super(TestCaseWithTransport, self).__init__(methodName)
        self.__readonly_server = None
        self.__server = None
        self.transport_server = default_transport
        self.transport_readonly_server = None

    def get_readonly_url(self, relpath=None):
        """Get a URL for the readonly transport.

        This will either be backed by '.' or a decorator to the transport 
        used by self.get_url()
        relpath provides for clients to get a path relative to the base url.
        These should only be downwards relative, not upwards.
        """
        base = self.get_readonly_server().get_url()
        if relpath is not None:
            if not base.endswith('/'):
                base = base + '/'
            base = base + relpath
        return base

    def get_readonly_server(self):
        """Get the server instance for the readonly transport

        This is useful for some tests with specific servers to do diagnostics.
        """
        if self.__readonly_server is None:
            if self.transport_readonly_server is None:
                # readonly decorator requested
                # bring up the server
                self.get_url()
                self.__readonly_server = ReadonlyServer()
                self.__readonly_server.setUp(self.__server)
            else:
                self.__readonly_server = self.transport_readonly_server()
                self.__readonly_server.setUp()
            self.addCleanup(self.__readonly_server.tearDown)
        return self.__readonly_server

    def get_server(self):
        """Get the read/write server instance.

        This is useful for some tests with specific servers that need
        diagnostics.
        """
        if self.__server is None:
            self.__server = self.transport_server()
            self.__server.setUp()
            self.addCleanup(self.__server.tearDown)
        return self.__server

    def get_url(self, relpath=None):
        """Get a URL for the readwrite transport.

        This will either be backed by '.' or to an equivalent non-file based
        facility.
        relpath provides for clients to get a path relative to the base url.
        These should only be downwards relative, not upwards.
        """
        base = self.get_server().get_url()
        if relpath is not None and relpath != '.':
            if not base.endswith('/'):
                base = base + '/'
            base = base + urlutils.escape(relpath)
        return base

    def get_transport(self):
        """Return a writeable transport for the test scratch space"""
        t = get_transport(self.get_url())
        self.assertFalse(t.is_readonly())
        return t

    def get_readonly_transport(self):
        """Return a readonly transport for the test scratch space
        
        This can be used to test that operations which should only need
        readonly access in fact do not try to write.
        """
        t = get_transport(self.get_readonly_url())
        self.assertTrue(t.is_readonly())
        return t

    def make_branch(self, relpath, format=None):
        """Create a branch on the transport at relpath."""
        repo = self.make_repository(relpath, format=format)
        return repo.bzrdir.create_branch()

    def make_bzrdir(self, relpath, format=None):
        try:
            url = self.get_url(relpath)
            mutter('relpath %r => url %r', relpath, url)
            segments = url.split('/')
            if segments and segments[-1] not in ('', '.'):
                parent = '/'.join(segments[:-1])
                t = get_transport(parent)
                try:
                    t.mkdir(segments[-1])
                except errors.FileExists:
                    pass
            if format is None:
                format=bzrlib.bzrdir.BzrDirFormat.get_default_format()
            # FIXME: make this use a single transport someday. RBC 20060418
            return format.initialize_on_transport(get_transport(relpath))
        except errors.UninitializableFormat:
            raise TestSkipped("Format %s is not initializable." % format)

    def make_repository(self, relpath, shared=False, format=None):
        """Create a repository on our default transport at relpath."""
        made_control = self.make_bzrdir(relpath, format=format)
        return made_control.create_repository(shared=shared)

    def make_branch_and_tree(self, relpath, format=None):
        """Create a branch on the transport and a tree locally.

        Returns the tree.
        """
        # TODO: always use the local disk path for the working tree,
        # this obviously requires a format that supports branch references
        # so check for that by checking bzrdir.BzrDirFormat.get_default_format()
        # RBC 20060208
        b = self.make_branch(relpath, format=format)
        try:
            return b.bzrdir.create_workingtree()
        except errors.NotLocalUrl:
            # new formats - catch No tree error and create
            # a branch reference and a checkout.
            # old formats at that point - raise TestSkipped.
            # TODO: rbc 20060208
            return WorkingTreeFormat2().initialize(bzrdir.BzrDir.open(relpath))

    def assertIsDirectory(self, relpath, transport):
        """Assert that relpath within transport is a directory.

        This may not be possible on all transports; in that case it propagates
        a TransportNotPossible.
        """
        try:
            mode = transport.stat(relpath).st_mode
        except errors.NoSuchFile:
            self.fail("path %s is not a directory; no such file"
                      % (relpath))
        if not stat.S_ISDIR(mode):
            self.fail("path %s is not a directory; has mode %#o"
                      % (relpath, mode))


class ChrootedTestCase(TestCaseWithTransport):
    """A support class that provides readonly urls outside the local namespace.

    This is done by checking if self.transport_server is a MemoryServer. if it
    is then we are chrooted already, if it is not then an HttpServer is used
    for readonly urls.

    TODO RBC 20060127: make this an option to TestCaseWithTransport so it can
                       be used without needed to redo it when a different 
                       subclass is in use ?
    """

    def setUp(self):
        super(ChrootedTestCase, self).setUp()
        if not self.transport_server == bzrlib.transport.memory.MemoryServer:
            self.transport_readonly_server = bzrlib.transport.http.HttpServer


def filter_suite_by_re(suite, pattern):
    result = TestUtil.TestSuite()
    filter_re = re.compile(pattern)
    for test in iter_suite_tests(suite):
        if filter_re.search(test.id()):
            result.addTest(test)
    return result


def run_suite(suite, name='test', verbose=False, pattern=".*",
              stop_on_failure=False, keep_output=False,
              transport=None, lsprof_timed=None, bench_history=None):
    TestCaseInTempDir._TEST_NAME = name
    TestCase._gather_lsprof_in_benchmarks = lsprof_timed
    if verbose:
        verbosity = 2
        pb = None
    else:
        verbosity = 1
        pb = progress.ProgressBar()
    runner = TextTestRunner(stream=sys.stdout,
                            descriptions=0,
                            verbosity=verbosity,
                            keep_output=keep_output,
                            pb=pb,
                            bench_history=bench_history)
    runner.stop_on_failure=stop_on_failure
    if pattern != '.*':
        suite = filter_suite_by_re(suite, pattern)
    result = runner.run(suite)
    return result.wasSuccessful()


def selftest(verbose=False, pattern=".*", stop_on_failure=True,
             keep_output=False,
             transport=None,
             test_suite_factory=None,
             lsprof_timed=None,
             bench_history=None):
    """Run the whole test suite under the enhanced runner"""
    # XXX: Very ugly way to do this...
    # Disable warning about old formats because we don't want it to disturb
    # any blackbox tests.
    from bzrlib import repository
    repository._deprecation_warning_done = True

    global default_transport
    if transport is None:
        transport = default_transport
    old_transport = default_transport
    default_transport = transport
    try:
        if test_suite_factory is None:
            suite = test_suite()
        else:
            suite = test_suite_factory()
        return run_suite(suite, 'testbzr', verbose=verbose, pattern=pattern,
                     stop_on_failure=stop_on_failure, keep_output=keep_output,
                     transport=transport,
                     lsprof_timed=lsprof_timed,
                     bench_history=bench_history)
    finally:
        default_transport = old_transport


def test_suite():
    """Build and return TestSuite for the whole of bzrlib.
    
    This function can be replaced if you need to change the default test
    suite on a global basis, but it is not encouraged.
    """
    testmod_names = [
                   'bzrlib.tests.test_ancestry',
                   'bzrlib.tests.test_api',
                   'bzrlib.tests.test_atomicfile',
                   'bzrlib.tests.test_bad_files',
                   'bzrlib.tests.test_branch',
                   'bzrlib.tests.test_bundle',
                   'bzrlib.tests.test_bzrdir',
                   'bzrlib.tests.test_cache_utf8',
                   'bzrlib.tests.test_command',
                   'bzrlib.tests.test_commit',
                   'bzrlib.tests.test_commit_merge',
                   'bzrlib.tests.test_config',
                   'bzrlib.tests.test_conflicts',
                   'bzrlib.tests.test_decorators',
                   'bzrlib.tests.test_diff',
                   'bzrlib.tests.test_doc_generate',
                   'bzrlib.tests.test_errors',
                   'bzrlib.tests.test_escaped_store',
                   'bzrlib.tests.test_fetch',
                   'bzrlib.tests.test_gpg',
                   'bzrlib.tests.test_graph',
                   'bzrlib.tests.test_hashcache',
                   'bzrlib.tests.test_http',
                   'bzrlib.tests.test_http_response',
                   'bzrlib.tests.test_identitymap',
                   'bzrlib.tests.test_ignores',
                   'bzrlib.tests.test_inv',
                   'bzrlib.tests.test_knit',
                   'bzrlib.tests.test_lockdir',
                   'bzrlib.tests.test_lockable_files',
                   'bzrlib.tests.test_log',
                   'bzrlib.tests.test_merge',
                   'bzrlib.tests.test_merge3',
                   'bzrlib.tests.test_merge_core',
                   'bzrlib.tests.test_missing',
                   'bzrlib.tests.test_msgeditor',
                   'bzrlib.tests.test_nonascii',
                   'bzrlib.tests.test_options',
                   'bzrlib.tests.test_osutils',
                   'bzrlib.tests.test_patch',
                   'bzrlib.tests.test_patches',
                   'bzrlib.tests.test_permissions',
                   'bzrlib.tests.test_plugins',
                   'bzrlib.tests.test_progress',
                   'bzrlib.tests.test_reconcile',
                   'bzrlib.tests.test_repository',
                   'bzrlib.tests.test_revert',
                   'bzrlib.tests.test_revision',
                   'bzrlib.tests.test_revisionnamespaces',
                   'bzrlib.tests.test_revisiontree',
                   'bzrlib.tests.test_rio',
                   'bzrlib.tests.test_sampler',
                   'bzrlib.tests.test_selftest',
                   'bzrlib.tests.test_setup',
                   'bzrlib.tests.test_sftp_transport',
                   'bzrlib.tests.test_ftp_transport',
                   'bzrlib.tests.test_smart_add',
                   'bzrlib.tests.test_source',
                   'bzrlib.tests.test_status',
                   'bzrlib.tests.test_store',
                   'bzrlib.tests.test_symbol_versioning',
                   'bzrlib.tests.test_testament',
                   'bzrlib.tests.test_textfile',
                   'bzrlib.tests.test_textmerge',
                   'bzrlib.tests.test_trace',
                   'bzrlib.tests.test_transactions',
                   'bzrlib.tests.test_transform',
                   'bzrlib.tests.test_transport',
                   'bzrlib.tests.test_tree',
                   'bzrlib.tests.test_tsort',
                   'bzrlib.tests.test_tuned_gzip',
                   'bzrlib.tests.test_ui',
                   'bzrlib.tests.test_upgrade',
                   'bzrlib.tests.test_urlutils',
                   'bzrlib.tests.test_versionedfile',
                   'bzrlib.tests.test_version',
                   'bzrlib.tests.test_weave',
                   'bzrlib.tests.test_whitebox',
                   'bzrlib.tests.test_workingtree',
                   'bzrlib.tests.test_xml',
                   ]
    test_transport_implementations = [
        'bzrlib.tests.test_transport_implementations',
        'bzrlib.tests.test_read_bundle',
        ]
    suite = TestUtil.TestSuite()
    loader = TestUtil.TestLoader()
    suite.addTest(loader.loadTestsFromModuleNames(testmod_names))
    from bzrlib.transport import TransportTestProviderAdapter
    adapter = TransportTestProviderAdapter()
    adapt_modules(test_transport_implementations, adapter, loader, suite)
    for package in packages_to_test():
        suite.addTest(package.test_suite())
    for m in MODULES_TO_TEST:
        suite.addTest(loader.loadTestsFromModule(m))
    for m in MODULES_TO_DOCTEST:
        suite.addTest(doctest.DocTestSuite(m))
    for name, plugin in bzrlib.plugin.all_plugins().items():
        if getattr(plugin, 'test_suite', None) is not None:
            suite.addTest(plugin.test_suite())
    return suite


def adapt_modules(mods_list, adapter, loader, suite):
    """Adapt the modules in mods_list using adapter and add to suite."""
    for test in iter_suite_tests(loader.loadTestsFromModuleNames(mods_list)):
        suite.addTests(adapter.adapt(test))
