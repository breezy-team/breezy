# Copyright (C) 2005, 2006 Canonical Ltd
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


from bzrlib import (
    bzrdir,
    debug,
    errors,
    memorytree,
    osutils,
    progress,
    urlutils,
    )
import bzrlib.branch
import bzrlib.commands
import bzrlib.bundle.serializer
import bzrlib.export
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
import bzrlib.plugin
from bzrlib.revision import common_ancestor
import bzrlib.store
from bzrlib import symbol_versioning
import bzrlib.trace
from bzrlib.transport import get_transport
import bzrlib.transport
from bzrlib.transport.local import LocalURLServer
from bzrlib.transport.memory import MemoryServer
from bzrlib.transport.readonly import ReadonlyServer
from bzrlib.trace import mutter, note
from bzrlib.tests import TestUtil
from bzrlib.tests.TestUtil import (
                          TestSuite,
                          TestLoader,
                          )
from bzrlib.tests.treeshape import build_tree_contents
from bzrlib.workingtree import WorkingTree, WorkingTreeFormat2

default_transport = LocalURLServer

MODULES_TO_TEST = []
MODULES_TO_DOCTEST = [
                      bzrlib.bundle.serializer,
                      bzrlib.errors,
                      bzrlib.export,
                      bzrlib.inventory,
                      bzrlib.iterablefile,
                      bzrlib.lockdir,
                      bzrlib.merge3,
                      bzrlib.option,
                      bzrlib.store,
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


class ExtendedTestResult(unittest._TextTestResult):
    """Accepts, reports and accumulates the results of running tests.

    Compared to this unittest version this class adds support for profiling,
    benchmarking, stopping as soon as a test fails,  and skipping tests.
    There are further-specialized subclasses for different types of display.
    """

    stop_early = False
    
    def __init__(self, stream, descriptions, verbosity,
                 bench_history=None,
                 num_tests=None,
                 ):
        """Construct new TestResult.

        :param bench_history: Optionally, a writable file object to accumulate
            benchmark results.
        """
        unittest._TextTestResult.__init__(self, stream, descriptions, verbosity)
        if bench_history is not None:
            from bzrlib.version import _get_bzr_source_tree
            src_tree = _get_bzr_source_tree()
            if src_tree:
                try:
                    revision_id = src_tree.get_parent_ids()[0]
                except IndexError:
                    # XXX: if this is a brand new tree, do the same as if there
                    # is no branch.
                    revision_id = ''
            else:
                # XXX: If there's no branch, what should we do?
                revision_id = ''
            bench_history.write("--date %s %s\n" % (time.time(), revision_id))
        self._bench_history = bench_history
        self.ui = bzrlib.ui.ui_factory
        self.num_tests = num_tests
        self.error_count = 0
        self.failure_count = 0
        self.skip_count = 0
        self.count = 0
        self._overall_start_time = time.time()
    
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

    def _shortened_test_description(self, test):
        what = test.id()
        what = re.sub(r'^bzrlib\.(tests|benchmark)\.', '', what)
        return what

    def startTest(self, test):
        unittest.TestResult.startTest(self, test)
        self.report_test_start(test)
        self._recordTestStartTime()

    def _recordTestStartTime(self):
        """Record that a test has started."""
        self._start_time = time.time()

    def addError(self, test, err):
        if isinstance(err[1], TestSkipped):
            return self.addSkipped(test, err)    
        unittest.TestResult.addError(self, test, err)
        # We can only do this if we have one of our TestCases, not if
        # we have a doctest.
        setKeepLogfile = getattr(test, 'setKeepLogfile', None)
        if setKeepLogfile is not None:
            setKeepLogfile()
        self.extractBenchmarkTime(test)
        self.report_error(test, err)
        if self.stop_early:
            self.stop()

    def addFailure(self, test, err):
        unittest.TestResult.addFailure(self, test, err)
        # We can only do this if we have one of our TestCases, not if
        # we have a doctest.
        setKeepLogfile = getattr(test, 'setKeepLogfile', None)
        if setKeepLogfile is not None:
            setKeepLogfile()
        self.extractBenchmarkTime(test)
        self.report_failure(test, err)
        if self.stop_early:
            self.stop()

    def addSuccess(self, test):
        self.extractBenchmarkTime(test)
        if self._bench_history is not None:
            if self._benchmarkTime is not None:
                self._bench_history.write("%s %s\n" % (
                    self._formatTime(self._benchmarkTime),
                    test.id()))
        self.report_success(test)
        unittest.TestResult.addSuccess(self, test)

    def addSkipped(self, test, skip_excinfo):
        self.extractBenchmarkTime(test)
        self.report_skip(test, skip_excinfo)
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

    def finished(self):
        pass

    def report_cleaning_up(self):
        pass

    def report_success(self, test):
        pass


class TextTestResult(ExtendedTestResult):
    """Displays progress and results of tests in text form"""

    def __init__(self, *args, **kw):
        ExtendedTestResult.__init__(self, *args, **kw)
        self.pb = self.ui.nested_progress_bar()
        self.pb.show_pct = False
        self.pb.show_spinner = False
        self.pb.show_eta = False, 
        self.pb.show_count = False
        self.pb.show_bar = False

    def report_starting(self):
        self.pb.update('[test 0/%d] starting...' % (self.num_tests))

    def _progress_prefix_text(self):
        a = '[%d' % self.count
        if self.num_tests is not None:
            a +='/%d' % self.num_tests
        a += ' in %ds' % (time.time() - self._overall_start_time)
        if self.error_count:
            a += ', %d errors' % self.error_count
        if self.failure_count:
            a += ', %d failed' % self.failure_count
        if self.skip_count:
            a += ', %d skipped' % self.skip_count
        a += ']'
        return a

    def report_test_start(self, test):
        self.count += 1
        self.pb.update(
                self._progress_prefix_text()
                + ' ' 
                + self._shortened_test_description(test))

    def report_error(self, test, err):
        self.error_count += 1
        self.pb.note('ERROR: %s\n    %s\n' % (
            self._shortened_test_description(test),
            err[1],
            ))

    def report_failure(self, test, err):
        self.failure_count += 1
        self.pb.note('FAIL: %s\n    %s\n' % (
            self._shortened_test_description(test),
            err[1],
            ))

    def report_skip(self, test, skip_excinfo):
        self.skip_count += 1
        if False:
            # at the moment these are mostly not things we can fix
            # and so they just produce stipple; use the verbose reporter
            # to see them.
            if False:
                # show test and reason for skip
                self.pb.note('SKIP: %s\n    %s\n' % (
                    self._shortened_test_description(test),
                    skip_excinfo[1]))
            else:
                # since the class name was left behind in the still-visible
                # progress bar...
                self.pb.note('SKIP: %s' % (skip_excinfo[1]))

    def report_cleaning_up(self):
        self.pb.update('cleaning up...')

    def finished(self):
        self.pb.finished()


class VerboseTestResult(ExtendedTestResult):
    """Produce long output, with one line per test run plus times"""

    def _ellipsize_to_right(self, a_string, final_width):
        """Truncate and pad a string, keeping the right hand side"""
        if len(a_string) > final_width:
            result = '...' + a_string[3-final_width:]
        else:
            result = a_string
        return result.ljust(final_width)

    def report_starting(self):
        self.stream.write('running %d tests...\n' % self.num_tests)

    def report_test_start(self, test):
        self.count += 1
        name = self._shortened_test_description(test)
        self.stream.write(self._ellipsize_to_right(name, 60))
        self.stream.flush()

    def report_error(self, test, err):
        self.error_count += 1
        self.stream.writeln('ERROR %s\n    %s' 
                % (self._testTimeString(), err[1]))

    def report_failure(self, test, err):
        self.failure_count += 1
        self.stream.writeln('FAIL %s\n    %s'
                % (self._testTimeString(), err[1]))

    def report_success(self, test):
        self.stream.writeln('   OK %s' % self._testTimeString())
        for bench_called, stats in getattr(test, '_benchcalls', []):
            self.stream.writeln('LSProf output for %s(%s, %s)' % bench_called)
            stats.pprint(file=self.stream)
        self.stream.flush()

    def report_skip(self, test, skip_excinfo):
        print >>self.stream, ' SKIP %s' % self._testTimeString()
        print >>self.stream, '     %s' % skip_excinfo[1]


class TextTestRunner(object):
    stop_on_failure = False

    def __init__(self,
                 stream=sys.stderr,
                 descriptions=0,
                 verbosity=1,
                 keep_output=False,
                 bench_history=None):
        self.stream = unittest._WritelnDecorator(stream)
        self.descriptions = descriptions
        self.verbosity = verbosity
        self.keep_output = keep_output
        self._bench_history = bench_history

    def run(self, test):
        "Run the given test case or test suite."
        startTime = time.time()
        if self.verbosity == 1:
            result_class = TextTestResult
        elif self.verbosity >= 2:
            result_class = VerboseTestResult
        result = result_class(self.stream,
                              self.descriptions,
                              self.verbosity,
                              bench_history=self._bench_history,
                              num_tests=test.countTestCases(),
                              )
        result.stop_early = self.stop_on_failure
        result.report_starting()
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
        result.report_cleaning_up()
        # This is still a little bogus, 
        # but only a little. Folk not using our testrunner will
        # have to delete their temp directories themselves.
        test_root = TestCaseWithMemoryTransport.TEST_ROOT
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
            note("Failed tests working directories are in '%s'\n", test_root)
        TestCaseWithMemoryTransport.TEST_ROOT = None
        result.finished()
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
    _keep_log_file = False
    # record lsprof data when performing benchmark calls.
    _gather_lsprof_in_benchmarks = False

    def __init__(self, methodName='testMethod'):
        super(TestCase, self).__init__(methodName)
        self._cleanups = []

    def setUp(self):
        unittest.TestCase.setUp(self)
        self._cleanEnvironment()
        bzrlib.trace.disable_default_logging()
        self._silenceUI()
        self._startLogFile()
        self._benchcalls = []
        self._benchtime = None

    def _silenceUI(self):
        """Turn off UI for duration of test"""
        # by default the UI is off; tests can turn it on if they want it.
        saved = bzrlib.ui.ui_factory
        def _restore():
            bzrlib.ui.ui_factory = saved
        bzrlib.ui.ui_factory = bzrlib.ui.SilentUIFactory()
        self.addCleanup(_restore)

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

    def _capture_warnings(self, a_callable, *args, **kwargs):
        """A helper for callDeprecated and applyDeprecated.

        :param a_callable: A callable to call.
        :param args: The positional arguments for the callable
        :param kwargs: The keyword arguments for the callable
        :return: A tuple (warnings, result). result is the result of calling
            a_callable(*args, **kwargs).
        """
        local_warnings = []
        def capture_warnings(msg, cls=None, stacklevel=None):
            # we've hooked into a deprecation specific callpath,
            # only deprecations should getting sent via it.
            self.assertEqual(cls, DeprecationWarning)
            local_warnings.append(msg)
        original_warning_method = symbol_versioning.warn
        symbol_versioning.set_warning_method(capture_warnings)
        try:
            result = a_callable(*args, **kwargs)
        finally:
            symbol_versioning.set_warning_method(original_warning_method)
        return (local_warnings, result)

    def applyDeprecated(self, deprecation_format, a_callable, *args, **kwargs):
        """Call a deprecated callable without warning the user.

        :param deprecation_format: The deprecation format that the callable
            should have been deprecated with. This is the same type as the 
            parameter to deprecated_method/deprecated_function. If the 
            callable is not deprecated with this format, an assertion error
            will be raised.
        :param a_callable: A callable to call. This may be a bound method or
            a regular function. It will be called with *args and **kwargs.
        :param args: The positional arguments for the callable
        :param kwargs: The keyword arguments for the callable
        :return: The result of a_callable(*args, **kwargs)
        """
        call_warnings, result = self._capture_warnings(a_callable,
            *args, **kwargs)
        expected_first_warning = symbol_versioning.deprecation_string(
            a_callable, deprecation_format)
        if len(call_warnings) == 0:
            self.fail("No assertion generated by call to %s" %
                a_callable)
        self.assertEqual(expected_first_warning, call_warnings[0])
        return result

    def callDeprecated(self, expected, callable, *args, **kwargs):
        """Assert that a callable is deprecated in a particular way.

        This is a very precise test for unusual requirements. The 
        applyDeprecated helper function is probably more suited for most tests
        as it allows you to simply specify the deprecation format being used
        and will ensure that that is issued for the function being called.

        :param expected: a list of the deprecation warnings expected, in order
        :param callable: The callable to call
        :param args: The positional arguments for the callable
        :param kwargs: The keyword arguments for the callable
        """
        call_warnings, result = self._capture_warnings(callable,
            *args, **kwargs)
        self.assertEqual(expected, call_warnings)
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

        Close the file and delete it, unless setKeepLogfile was called.
        """
        if self._log_file is None:
            return
        bzrlib.trace.disable_test_log(self._log_nonce)
        self._log_file.close()
        self._log_file = None
        if not self._keep_log_file:
            os.remove(self._log_file_name)
            self._log_file_name = None

    def setKeepLogfile(self):
        """Make the logfile not be deleted when _finishLogFile is called."""
        self._keep_log_file = True

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
            'BZR_HOME': None, # Don't inherit BZR_HOME to all the tests.
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

    def _get_log(self, keep_log_file=False):
        """Return as a string the log for this test. If the file is still
        on disk and keep_log_file=False, delete the log file and store the
        content in self._log_contents."""
        # flush the log file, to get all content
        import bzrlib.trace
        bzrlib.trace._trace_file.flush()
        if self._log_contents:
            return self._log_contents
        if self._log_file_name is not None:
            logfile = open(self._log_file_name)
            try:
                log_contents = logfile.read()
            finally:
                logfile.close()
            if not keep_log_file:
                self._log_contents = log_contents
                os.remove(self._log_file_name)
            return log_contents
        else:
            return "DELETED log file to reduce memory footprint"

    def capture(self, cmd, retcode=0):
        """Shortcut that splits cmd into words, runs, and returns stdout"""
        return self.run_bzr_captured(cmd.split(), retcode=retcode)[0]

    def run_bzr_captured(self, argv, retcode=0, encoding=None, stdin=None,
                         working_dir=None):
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
        :param working_dir: Change to this directory before running
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

        cwd = None
        if working_dir is not None:
            cwd = osutils.getcwd()
            os.chdir(working_dir)

        try:
            saved_debug_flags = frozenset(debug.debug_flags)
            debug.debug_flags.clear()
            try:
                result = self.apply_redirected(stdin, stdout, stderr,
                                               bzrlib.commands.run_bzr_catch_errors,
                                               argv)
            finally:
                debug.debug_flags.update(saved_debug_flags)
        finally:
            logger.removeHandler(handler)
            bzrlib.ui.ui_factory = old_ui_factory
            if cwd is not None:
                os.chdir(cwd)

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
        working_dir = kwargs.pop('working_dir', None)
        return self.run_bzr_captured(args, retcode=retcode, encoding=encoding,
                                     stdin=stdin, working_dir=working_dir)

    def run_bzr_decode(self, *args, **kwargs):
        if 'encoding' in kwargs:
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
        :param universal_newlines: Convert CRLF => LF
        :param allow_plugins: By default the subprocess is run with
            --no-plugins to ensure test reproducibility. Also, it is possible
            for system-wide plugins to create unexpected output on stderr,
            which can cause unnecessary test failures.
        """
        env_changes = kwargs.get('env_changes', {})
        working_dir = kwargs.get('working_dir', None)
        allow_plugins = kwargs.get('allow_plugins', False)
        process = self.start_bzr_subprocess(args, env_changes=env_changes,
                                            working_dir=working_dir,
                                            allow_plugins=allow_plugins)
        # We distinguish between retcode=None and retcode not passed.
        supplied_retcode = kwargs.get('retcode', 0)
        return self.finish_bzr_subprocess(process, retcode=supplied_retcode,
            universal_newlines=kwargs.get('universal_newlines', False),
            process_args=args)

    def start_bzr_subprocess(self, process_args, env_changes=None,
                             skip_if_plan_to_signal=False,
                             working_dir=None,
                             allow_plugins=False):
        """Start bzr in a subprocess for testing.

        This starts a new Python interpreter and runs bzr in there.
        This should only be used for tests that have a justifiable need for
        this isolation: e.g. they are testing startup time, or signal
        handling, or early startup code, etc.  Subprocess code can't be
        profiled or debugged so easily.

        :param process_args: a list of arguments to pass to the bzr executable,
            for example `['--version']`.
        :param env_changes: A dictionary which lists changes to environment
            variables. A value of None will unset the env variable.
            The values must be strings. The change will only occur in the
            child, so you don't need to fix the environment after running.
        :param skip_if_plan_to_signal: raise TestSkipped when true and os.kill
            is not available.
        :param allow_plugins: If False (default) pass --no-plugins to bzr.

        :returns: Popen object for the started process.
        """
        if skip_if_plan_to_signal:
            if not getattr(os, 'kill', None):
                raise TestSkipped("os.kill not available.")

        if env_changes is None:
            env_changes = {}
        old_env = {}

        def cleanup_environment():
            for env_var, value in env_changes.iteritems():
                old_env[env_var] = osutils.set_or_unset_env(env_var, value)

        def restore_environment():
            for env_var, value in old_env.iteritems():
                osutils.set_or_unset_env(env_var, value)

        bzr_path = self.get_bzr_path()

        cwd = None
        if working_dir is not None:
            cwd = osutils.getcwd()
            os.chdir(working_dir)

        try:
            # win32 subprocess doesn't support preexec_fn
            # so we will avoid using it on all platforms, just to
            # make sure the code path is used, and we don't break on win32
            cleanup_environment()
            command = [sys.executable, bzr_path]
            if not allow_plugins:
                command.append('--no-plugins')
            command.extend(process_args)
            process = self._popen(command, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        finally:
            restore_environment()
            if cwd is not None:
                os.chdir(cwd)

        return process

    def _popen(self, *args, **kwargs):
        """Place a call to Popen.

        Allows tests to override this method to intercept the calls made to
        Popen for introspection.
        """
        return Popen(*args, **kwargs)

    def get_bzr_path(self):
        """Return the path of the 'bzr' executable for this test suite."""
        bzr_path = os.path.dirname(os.path.dirname(bzrlib.__file__))+'/bzr'
        if not os.path.isfile(bzr_path):
            # We are probably installed. Assume sys.argv is the right file
            bzr_path = sys.argv[0]
        return bzr_path

    def finish_bzr_subprocess(self, process, retcode=0, send_signal=None,
                              universal_newlines=False, process_args=None):
        """Finish the execution of process.

        :param process: the Popen object returned from start_bzr_subprocess.
        :param retcode: The status code that is expected.  Defaults to 0.  If
            None is supplied, the status code is not checked.
        :param send_signal: an optional signal to send to the process.
        :param universal_newlines: Convert CRLF => LF
        :returns: (stdout, stderr)
        """
        if send_signal is not None:
            os.kill(process.pid, send_signal)
        out, err = process.communicate()

        if universal_newlines:
            out = out.replace('\r\n', '\n')
            err = err.replace('\r\n', '\n')

        if retcode is not None and retcode != process.returncode:
            if process_args is None:
                process_args = "(unknown args)"
            mutter('Output of bzr %s:\n%s', process_args, out)
            mutter('Error for bzr %s:\n%s', process_args, err)
            self.fail('Command bzr %s failed with retcode %s != %s'
                      % (process_args, retcode, process.returncode))
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

    @symbol_versioning.deprecated_method(symbol_versioning.zero_eleven)
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


class TestCaseWithMemoryTransport(TestCase):
    """Common test class for tests that do not need disk resources.

    Tests that need disk resources should derive from TestCaseWithTransport.

    TestCaseWithMemoryTransport sets the TEST_ROOT variable for all bzr tests.

    For TestCaseWithMemoryTransport the test_home_dir is set to the name of
    a directory which does not exist. This serves to help ensure test isolation
    is preserved. test_dir is set to the TEST_ROOT, as is cwd, because they
    must exist. However, TestCaseWithMemoryTransport does not offer local
    file defaults for the transport in tests, nor does it obey the command line
    override, so tests that accidentally write to the common directory should
    be rare.
    """

    TEST_ROOT = None
    _TEST_NAME = 'test'


    def __init__(self, methodName='runTest'):
        # allow test parameterisation after test construction and before test
        # execution. Variables that the parameteriser sets need to be 
        # ones that are not set by setUp, or setUp will trash them.
        super(TestCaseWithMemoryTransport, self).__init__(methodName)
        self.transport_server = default_transport
        self.transport_readonly_server = None

    def failUnlessExists(self, path):
        """Fail unless path, which may be abs or relative, exists."""
        self.failUnless(osutils.lexists(path))

    def failIfExists(self, path):
        """Fail if path, which may be abs or relative, exists."""
        self.failIf(osutils.lexists(path))
        
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

    def get_server(self):
        """Get the read/write server instance.

        This is useful for some tests with specific servers that need
        diagnostics.

        For TestCaseWithMemoryTransport this is always a MemoryServer, and there
        is no means to override it.
        """
        if self.__server is None:
            self.__server = MemoryServer()
            self.__server.setUp()
            self.addCleanup(self.__server.tearDown)
        return self.__server

    def get_url(self, relpath=None):
        """Get a URL (or maybe a path) for the readwrite transport.

        This will either be backed by '.' or to an equivalent non-file based
        facility.
        relpath provides for clients to get a path relative to the base url.
        These should only be downwards relative, not upwards.
        """
        base = self.get_server().get_url()
        if relpath is not None and relpath != '.':
            if not base.endswith('/'):
                base = base + '/'
            # XXX: Really base should be a url; we did after all call
            # get_url()!  But sometimes it's just a path (from
            # LocalAbspathServer), and it'd be wrong to append urlescaped data
            # to a non-escaped local path.
            if base.startswith('./') or base.startswith('/'):
                base += relpath
            else:
                base += urlutils.escape(relpath)
        return base

    def _make_test_root(self):
        if TestCaseWithMemoryTransport.TEST_ROOT is not None:
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
            TestCaseWithMemoryTransport.TEST_ROOT = osutils.abspath(root)
            break
        # make a fake bzr directory there to prevent any tests propagating
        # up onto the source directory's real branch
        bzrdir.BzrDir.create_standalone_workingtree(
            TestCaseWithMemoryTransport.TEST_ROOT)

    def makeAndChdirToTestDir(self):
        """Create a temporary directories for this one test.
        
        This must set self.test_home_dir and self.test_dir and chdir to
        self.test_dir.
        
        For TestCaseWithMemoryTransport we chdir to the TEST_ROOT for this test.
        """
        os.chdir(TestCaseWithMemoryTransport.TEST_ROOT)
        self.test_dir = TestCaseWithMemoryTransport.TEST_ROOT
        self.test_home_dir = self.test_dir + "/MemoryTransportMissingHomeDir"
        
    def make_branch(self, relpath, format=None):
        """Create a branch on the transport at relpath."""
        repo = self.make_repository(relpath, format=format)
        return repo.bzrdir.create_branch()

    def make_bzrdir(self, relpath, format=None):
        try:
            # might be a relative or absolute path
            maybe_a_url = self.get_url(relpath)
            segments = maybe_a_url.rsplit('/', 1)
            t = get_transport(maybe_a_url)
            if len(segments) > 1 and segments[-1] not in ('', '.'):
                try:
                    t.mkdir('.')
                except errors.FileExists:
                    pass
            if format is None:
                format = bzrlib.bzrdir.BzrDirFormat.get_default_format()
            return format.initialize_on_transport(t)
        except errors.UninitializableFormat:
            raise TestSkipped("Format %s is not initializable." % format)

    def make_repository(self, relpath, shared=False, format=None):
        """Create a repository on our default transport at relpath."""
        made_control = self.make_bzrdir(relpath, format=format)
        return made_control.create_repository(shared=shared)

    def make_branch_and_memory_tree(self, relpath, format=None):
        """Create a branch on the default transport and a MemoryTree for it."""
        b = self.make_branch(relpath, format=format)
        return memorytree.MemoryTree.create_on_branch(b)

    def overrideEnvironmentForTesting(self):
        os.environ['HOME'] = self.test_home_dir
        os.environ['APPDATA'] = self.test_home_dir
        
    def setUp(self):
        super(TestCaseWithMemoryTransport, self).setUp()
        self._make_test_root()
        _currentdir = os.getcwdu()
        def _leaveDirectory():
            os.chdir(_currentdir)
        self.addCleanup(_leaveDirectory)
        self.makeAndChdirToTestDir()
        self.overrideEnvironmentForTesting()
        self.__readonly_server = None
        self.__server = None

     
class TestCaseInTempDir(TestCaseWithMemoryTransport):
    """Derived class that runs a test within a temporary directory.

    This is useful for tests that need to create a branch, etc.

    The directory is created in a slightly complex way: for each
    Python invocation, a new temporary top-level directory is created.
    All test cases create their own directory within that.  If the
    tests complete successfully, the directory is removed.

    InTempDir is an old alias for FunctionalTestCase.
    """

    OVERRIDE_PYTHON = 'python'

    def check_file_contents(self, filename, expect):
        self.log("check contents of file %s" % filename)
        contents = file(filename, 'r').read()
        if contents != expect:
            self.log("expected: %r" % expect)
            self.log("actually: %r" % contents)
            self.fail("contents of %s not as expected" % filename)

    def makeAndChdirToTestDir(self):
        """See TestCaseWithMemoryTransport.makeAndChdirToTestDir().
        
        For TestCaseInTempDir we create a temporary directory based on the test
        name and then create two subdirs - test and home under it.
        """
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
                os.mkdir(candidate_dir)
                self.test_home_dir = candidate_dir + '/home'
                os.mkdir(self.test_home_dir)
                self.test_dir = candidate_dir + '/work'
                os.mkdir(self.test_dir)
                os.chdir(self.test_dir)
                break

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
                #   put_non_atomic: 2.9-4.5s
                transport.put_bytes_non_atomic(urlutils.escape(name), content)

    def build_tree_contents(self, shape):
        build_tree_contents(shape)

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

    def get_server(self):
        """See TestCaseWithMemoryTransport.

        This is useful for some tests with specific servers that need
        diagnostics.
        """
        if self.__server is None:
            self.__server = self.transport_server()
            self.__server.setUp()
            self.addCleanup(self.__server.tearDown)
        return self.__server

    def make_branch_and_tree(self, relpath, format=None):
        """Create a branch on the transport and a tree locally.

        If the transport is not a LocalTransport, the Tree can't be created on
        the transport.  In that case the working tree is created in the local
        directory, and the returned tree's branch and repository will also be
        accessed locally.

        This will fail if the original default transport for this test
        case wasn't backed by the working directory, as the branch won't
        be on disk for us to open it.  

        :param format: The BzrDirFormat.
        :returns: the WorkingTree.
        """
        # TODO: always use the local disk path for the working tree,
        # this obviously requires a format that supports branch references
        # so check for that by checking bzrdir.BzrDirFormat.get_default_format()
        # RBC 20060208
        b = self.make_branch(relpath, format=format)
        try:
            return b.bzrdir.create_workingtree()
        except errors.NotLocalUrl:
            # We can only make working trees locally at the moment.  If the
            # transport can't support them, then reopen the branch on a local
            # transport, and create the working tree there.  
            #
            # Possibly we should instead keep
            # the non-disk-backed branch and create a local checkout?
            bd = bzrdir.BzrDir.open(relpath)
            return bd.create_workingtree()

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

    def setUp(self):
        super(TestCaseWithTransport, self).setUp()
        self.__server = None


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
    TestCase._gather_lsprof_in_benchmarks = lsprof_timed
    if verbose:
        verbosity = 2
    else:
        verbosity = 1
    runner = TextTestRunner(stream=sys.stdout,
                            descriptions=0,
                            verbosity=verbosity,
                            keep_output=keep_output,
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
                   'bzrlib.tests.test_ftp_transport',
                   'bzrlib.tests.test_gpg',
                   'bzrlib.tests.test_graph',
                   'bzrlib.tests.test_hashcache',
                   'bzrlib.tests.test_http',
                   'bzrlib.tests.test_http_response',
                   'bzrlib.tests.test_identitymap',
                   'bzrlib.tests.test_ignores',
                   'bzrlib.tests.test_inv',
                   'bzrlib.tests.test_knit',
                   'bzrlib.tests.test_lazy_import',
                   'bzrlib.tests.test_lazy_regex',
                   'bzrlib.tests.test_lockdir',
                   'bzrlib.tests.test_lockable_files',
                   'bzrlib.tests.test_log',
                   'bzrlib.tests.test_memorytree',
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
                   'bzrlib.tests.test_registry',
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
                   'bzrlib.tests.test_smart_add',
                   'bzrlib.tests.test_smart_transport',
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
                   'bzrlib.tests.test_treebuilder',
                   'bzrlib.tests.test_tsort',
                   'bzrlib.tests.test_tuned_gzip',
                   'bzrlib.tests.test_ui',
                   'bzrlib.tests.test_upgrade',
                   'bzrlib.tests.test_urlutils',
                   'bzrlib.tests.test_versionedfile',
                   'bzrlib.tests.test_version',
                   'bzrlib.tests.test_version_info',
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
        try:
            suite.addTest(doctest.DocTestSuite(m))
        except ValueError, e:
            print '**failed to get doctest for: %s\n%s' %(m,e)
            raise
    for name, plugin in bzrlib.plugin.all_plugins().items():
        if getattr(plugin, 'test_suite', None) is not None:
            suite.addTest(plugin.test_suite())
    return suite


def adapt_modules(mods_list, adapter, loader, suite):
    """Adapt the modules in mods_list using adapter and add to suite."""
    for test in iter_suite_tests(loader.loadTestsFromModuleNames(mods_list)):
        suite.addTests(adapter.adapt(test))
