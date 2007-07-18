# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

import atexit
import codecs
from cStringIO import StringIO
import difflib
import doctest
import errno
import logging
import os
from pprint import pformat
import random
import re
import shlex
import stat
from subprocess import Popen, PIPE
import sys
import tempfile
import unittest
import time
import warnings


from bzrlib import (
    bzrdir,
    debug,
    errors,
    memorytree,
    osutils,
    progress,
    ui,
    urlutils,
    workingtree,
    )
import bzrlib.branch
import bzrlib.commands
import bzrlib.timestamp
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
from bzrlib.symbol_versioning import (
    deprecated_method,
    zero_eighteen,
    )
import bzrlib.trace
from bzrlib.transport import get_transport
import bzrlib.transport
from bzrlib.transport.local import LocalURLServer
from bzrlib.transport.memory import MemoryServer
from bzrlib.transport.readonly import ReadonlyServer
from bzrlib.trace import mutter, note
from bzrlib.tests import TestUtil
from bzrlib.tests.HttpServer import HttpServer
from bzrlib.tests.TestUtil import (
                          TestSuite,
                          TestLoader,
                          )
from bzrlib.tests.treeshape import build_tree_contents
from bzrlib.workingtree import WorkingTree, WorkingTreeFormat2

# Mark this python module as being part of the implementation
# of unittest: this gives us better tracebacks where the last
# shown frame is the test code, not our assertXYZ.
__unittest = 1

default_transport = LocalURLServer

MODULES_TO_TEST = []
MODULES_TO_DOCTEST = [
                      bzrlib.timestamp,
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
    import bzrlib.tests.per_lock
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
            bzrlib.tests.per_lock,
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
        self.ui = ui.ui_factory
        self.num_tests = num_tests
        self.error_count = 0
        self.failure_count = 0
        self.known_failure_count = 0
        self.skip_count = 0
        self.unsupported = {}
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
            return "           %s" % self._elapsedTestTimeString()

    def _formatTime(self, seconds):
        """Format seconds as milliseconds with leading spaces."""
        # some benchmarks can take thousands of seconds to run, so we need 8
        # places
        return "%8dms" % (1000 * seconds)

    def _shortened_test_description(self, test):
        what = test.id()
        what = re.sub(r'^bzrlib\.(tests|benchmarks)\.', '', what)
        return what

    def startTest(self, test):
        unittest.TestResult.startTest(self, test)
        self.report_test_start(test)
        test.number = self.count
        self._recordTestStartTime()

    def _recordTestStartTime(self):
        """Record that a test has started."""
        self._start_time = time.time()

    def _cleanupLogFile(self, test):
        # We can only do this if we have one of our TestCases, not if
        # we have a doctest.
        setKeepLogfile = getattr(test, 'setKeepLogfile', None)
        if setKeepLogfile is not None:
            setKeepLogfile()

    def addError(self, test, err):
        self.extractBenchmarkTime(test)
        self._cleanupLogFile(test)
        if isinstance(err[1], TestSkipped):
            return self.addSkipped(test, err)
        elif isinstance(err[1], UnavailableFeature):
            return self.addNotSupported(test, err[1].args[0])
        unittest.TestResult.addError(self, test, err)
        self.error_count += 1
        self.report_error(test, err)
        if self.stop_early:
            self.stop()

    def addFailure(self, test, err):
        self._cleanupLogFile(test)
        self.extractBenchmarkTime(test)
        if isinstance(err[1], KnownFailure):
            return self.addKnownFailure(test, err)
        unittest.TestResult.addFailure(self, test, err)
        self.failure_count += 1
        self.report_failure(test, err)
        if self.stop_early:
            self.stop()

    def addKnownFailure(self, test, err):
        self.known_failure_count += 1
        self.report_known_failure(test, err)

    def addNotSupported(self, test, feature):
        self.unsupported.setdefault(str(feature), 0)
        self.unsupported[str(feature)] += 1
        self.report_unsupported(test, feature)

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
            self.stream.write("%s: " % flavour)
            self.stream.writeln(self.getDescription(test))
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

    def __init__(self, stream, descriptions, verbosity,
                 bench_history=None,
                 num_tests=None,
                 pb=None,
                 ):
        ExtendedTestResult.__init__(self, stream, descriptions, verbosity,
            bench_history, num_tests)
        if pb is None:
            self.pb = self.ui.nested_progress_bar()
            self._supplied_pb = False
        else:
            self.pb = pb
            self._supplied_pb = True
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
        if self.known_failure_count:
            a += ', %d known failures' % self.known_failure_count
        if self.skip_count:
            a += ', %d skipped' % self.skip_count
        if self.unsupported:
            a += ', %d missing features' % len(self.unsupported)
        a += ']'
        return a

    def report_test_start(self, test):
        self.count += 1
        self.pb.update(
                self._progress_prefix_text()
                + ' ' 
                + self._shortened_test_description(test))

    def _test_description(self, test):
        return self._shortened_test_description(test)

    def report_error(self, test, err):
        self.pb.note('ERROR: %s\n    %s\n', 
            self._test_description(test),
            err[1],
            )

    def report_failure(self, test, err):
        self.pb.note('FAIL: %s\n    %s\n', 
            self._test_description(test),
            err[1],
            )

    def report_known_failure(self, test, err):
        self.pb.note('XFAIL: %s\n%s\n',
            self._test_description(test), err[1])

    def report_skip(self, test, skip_excinfo):
        self.skip_count += 1
        if False:
            # at the moment these are mostly not things we can fix
            # and so they just produce stipple; use the verbose reporter
            # to see them.
            if False:
                # show test and reason for skip
                self.pb.note('SKIP: %s\n    %s\n', 
                    self._shortened_test_description(test),
                    skip_excinfo[1])
            else:
                # since the class name was left behind in the still-visible
                # progress bar...
                self.pb.note('SKIP: %s', skip_excinfo[1])

    def report_unsupported(self, test, feature):
        """test cannot be run because feature is missing."""
                  
    def report_cleaning_up(self):
        self.pb.update('cleaning up...')

    def finished(self):
        if not self._supplied_pb:
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
        # width needs space for 6 char status, plus 1 for slash, plus 2 10-char
        # numbers, plus a trailing blank
        # when NUMBERED_DIRS: plus 5 chars on test number, plus 1 char on space
        self.stream.write(self._ellipsize_to_right(name,
                          osutils.terminal_width()-30))
        self.stream.flush()

    def _error_summary(self, err):
        indent = ' ' * 4
        return '%s%s' % (indent, err[1])

    def report_error(self, test, err):
        self.stream.writeln('ERROR %s\n%s'
                % (self._testTimeString(),
                   self._error_summary(err)))

    def report_failure(self, test, err):
        self.stream.writeln(' FAIL %s\n%s'
                % (self._testTimeString(),
                   self._error_summary(err)))

    def report_known_failure(self, test, err):
        self.stream.writeln('XFAIL %s\n%s'
                % (self._testTimeString(),
                   self._error_summary(err)))

    def report_success(self, test):
        self.stream.writeln('   OK %s' % self._testTimeString())
        for bench_called, stats in getattr(test, '_benchcalls', []):
            self.stream.writeln('LSProf output for %s(%s, %s)' % bench_called)
            stats.pprint(file=self.stream)
        # flush the stream so that we get smooth output. This verbose mode is
        # used to show the output in PQM.
        self.stream.flush()

    def report_skip(self, test, skip_excinfo):
        self.skip_count += 1
        self.stream.writeln(' SKIP %s\n%s'
                % (self._testTimeString(),
                   self._error_summary(skip_excinfo)))

    def report_unsupported(self, test, feature):
        """test cannot be run because feature is missing."""
        self.stream.writeln("NODEP %s\n    The feature '%s' is not available."
                %(self._testTimeString(), feature))
                  


class TextTestRunner(object):
    stop_on_failure = False

    def __init__(self,
                 stream=sys.stderr,
                 descriptions=0,
                 verbosity=1,
                 bench_history=None,
                 list_only=False
                 ):
        self.stream = unittest._WritelnDecorator(stream)
        self.descriptions = descriptions
        self.verbosity = verbosity
        self._bench_history = bench_history
        self.list_only = list_only

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
        if self.list_only:
            if self.verbosity >= 2:
                self.stream.writeln("Listing tests only ...\n")
            run = 0
            for t in iter_suite_tests(test):
                self.stream.writeln("%s" % (t.id()))
                run += 1
            actionTaken = "Listed"
        else: 
            test.run(result)
            run = result.testsRun
            actionTaken = "Ran"
        stopTime = time.time()
        timeTaken = stopTime - startTime
        result.printErrors()
        self.stream.writeln(result.separator2)
        self.stream.writeln("%s %d test%s in %.3fs" % (actionTaken,
                            run, run != 1 and "s" or "", timeTaken))
        self.stream.writeln()
        if not result.wasSuccessful():
            self.stream.write("FAILED (")
            failed, errored = map(len, (result.failures, result.errors))
            if failed:
                self.stream.write("failures=%d" % failed)
            if errored:
                if failed: self.stream.write(", ")
                self.stream.write("errors=%d" % errored)
            if result.known_failure_count:
                if failed or errored: self.stream.write(", ")
                self.stream.write("known_failure_count=%d" %
                    result.known_failure_count)
            self.stream.writeln(")")
        else:
            if result.known_failure_count:
                self.stream.writeln("OK (known_failures=%d)" %
                    result.known_failure_count)
            else:
                self.stream.writeln("OK")
        if result.skip_count > 0:
            skipped = result.skip_count
            self.stream.writeln('%d test%s skipped' %
                                (skipped, skipped != 1 and "s" or ""))
        if result.unsupported:
            for feature, count in sorted(result.unsupported.items()):
                self.stream.writeln("Missing feature '%s' skipped %d tests." %
                    (feature, count))
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


class KnownFailure(AssertionError):
    """Indicates that a test failed in a precisely expected manner.

    Such failures dont block the whole test suite from passing because they are
    indicators of partially completed code or of future work. We have an
    explicit error for them so that we can ensure that they are always visible:
    KnownFailures are always shown in the output of bzr selftest.
    """


class UnavailableFeature(Exception):
    """A feature required for this test was not available.

    The feature should be used to construct the exception.
    """


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


class TestUIFactory(ui.CLIUIFactory):
    """A UI Factory for testing.

    Hide the progress bar but emit note()s.
    Redirect stdin.
    Allows get_password to be tested without real tty attached.
    """

    def __init__(self,
                 stdout=None,
                 stderr=None,
                 stdin=None):
        super(TestUIFactory, self).__init__()
        if stdin is not None:
            # We use a StringIOWrapper to be able to test various
            # encodings, but the user is still responsible to
            # encode the string and to set the encoding attribute
            # of StringIOWrapper.
            self.stdin = StringIOWrapper(stdin)
        if stdout is None:
            self.stdout = sys.stdout
        else:
            self.stdout = stdout
        if stderr is None:
            self.stderr = sys.stderr
        else:
            self.stderr = stderr

    def clear(self):
        """See progress.ProgressBar.clear()."""

    def clear_term(self):
        """See progress.ProgressBar.clear_term()."""

    def clear_term(self):
        """See progress.ProgressBar.clear_term()."""

    def finished(self):
        """See progress.ProgressBar.finished()."""

    def note(self, fmt_string, *args, **kwargs):
        """See progress.ProgressBar.note()."""
        self.stdout.write((fmt_string + "\n") % args)

    def progress_bar(self):
        return self

    def nested_progress_bar(self):
        return self

    def update(self, message, count=None, total=None):
        """See progress.ProgressBar.update()."""

    def get_non_echoed_password(self, prompt):
        """Get password from stdin without trying to handle the echo mode"""
        if prompt:
            self.stdout.write(prompt.encode(self.stdout.encoding, 'replace'))
        password = self.stdin.readline()
        if not password:
            raise EOFError
        if password[-1] == '\n':
            password = password[:-1]
        return password


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
        self._clear_hooks()
        self._clear_debug_flags()

    def _clear_debug_flags(self):
        """Prevent externally set debug flags affecting tests.
        
        Tests that want to use debug flags can just set them in the
        debug_flags set during setup/teardown.
        """
        self._preserved_debug_flags = set(debug.debug_flags)
        debug.debug_flags.clear()
        self.addCleanup(self._restore_debug_flags)

    def _clear_hooks(self):
        # prevent hooks affecting tests
        import bzrlib.branch
        import bzrlib.smart.server
        self._preserved_hooks = {
            bzrlib.branch.Branch: bzrlib.branch.Branch.hooks,
            bzrlib.smart.server.SmartTCPServer: bzrlib.smart.server.SmartTCPServer.hooks,
            }
        self.addCleanup(self._restoreHooks)
        # reset all hooks to an empty instance of the appropriate type
        bzrlib.branch.Branch.hooks = bzrlib.branch.BranchHooks()
        bzrlib.smart.server.SmartTCPServer.hooks = bzrlib.smart.server.SmartServerHooks()

    def _silenceUI(self):
        """Turn off UI for duration of test"""
        # by default the UI is off; tests can turn it on if they want it.
        saved = ui.ui_factory
        def _restore():
            ui.ui_factory = saved
        ui.ui_factory = ui.SilentUIFactory()
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

    def assertEqual(self, a, b, message=''):
        try:
            if a == b:
                return
        except UnicodeError, e:
            # If we can't compare without getting a UnicodeError, then
            # obviously they are different
            mutter('UnicodeError: %s', e)
        if message:
            message += '\n'
        raise AssertionError("%snot equal:\na = %s\nb = %s\n"
            % (message,
               pformat(a), pformat(b)))

    assertEquals = assertEqual

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
            if '\n' in haystack or len(haystack) > 60:
                # a long string, format it in a more readable way
                raise AssertionError(
                        'pattern "%s" not found in\n"""\\\n%s"""\n'
                        % (needle_re, haystack))
            else:
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

    def assertListRaises(self, excClass, func, *args, **kwargs):
        """Fail unless excClass is raised when the iterator from func is used.
        
        Many functions can return generators this makes sure
        to wrap them in a list() call to make sure the whole generator
        is run, and that the proper exception is raised.
        """
        try:
            list(func(*args, **kwargs))
        except excClass:
            return
        else:
            if getattr(excClass,'__name__', None) is not None:
                excName = excClass.__name__
            else:
                excName = str(excClass)
            raise self.failureException, "%s not raised" % excName

    def assertRaises(self, excClass, callableObj, *args, **kwargs):
        """Assert that a callable raises a particular exception.

        :param excClass: As for the except statement, this may be either an
            exception class, or a tuple of classes.
        :param callableObj: A callable, will be passed ``*args`` and
            ``**kwargs``.

        Returns the exception so that you can examine it.
        """
        try:
            callableObj(*args, **kwargs)
        except excClass, e:
            return e
        else:
            if getattr(excClass,'__name__', None) is not None:
                excName = excClass.__name__
            else:
                # probably a tuple
                excName = str(excClass)
            raise self.failureException, "%s not raised" % excName

    def assertIs(self, left, right, message=None):
        if not (left is right):
            if message is not None:
                raise AssertionError(message)
            else:
                raise AssertionError("%r is not %r." % (left, right))

    def assertIsNot(self, left, right, message=None):
        if (left is right):
            if message is not None:
                raise AssertionError(message)
            else:
                raise AssertionError("%r is %r." % (left, right))

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

    def expectFailure(self, reason, assertion, *args, **kwargs):
        """Invoke a test, expecting it to fail for the given reason.

        This is for assertions that ought to succeed, but currently fail.
        (The failure is *expected* but not *wanted*.)  Please be very precise
        about the failure you're expecting.  If a new bug is introduced,
        AssertionError should be raised, not KnownFailure.

        Frequently, expectFailure should be followed by an opposite assertion.
        See example below.

        Intended to be used with a callable that raises AssertionError as the
        'assertion' parameter.  args and kwargs are passed to the 'assertion'.

        Raises KnownFailure if the test fails.  Raises AssertionError if the
        test succeeds.

        example usage::

          self.expectFailure('Math is broken', self.assertNotEqual, 54,
                             dynamic_val)
          self.assertEqual(42, dynamic_val)

          This means that a dynamic_val of 54 will cause the test to raise
          a KnownFailure.  Once math is fixed and the expectFailure is removed,
          only a dynamic_val of 42 will allow the test to pass.  Anything other
          than 54 or 42 will cause an AssertionError.
        """
        try:
            assertion(*args, **kwargs)
        except AssertionError:
            raise KnownFailure(reason)
        else:
            self.fail('Unexpected success.  Should have failed: %s' % reason)

    def _capture_warnings(self, a_callable, *args, **kwargs):
        """A helper for callDeprecated and applyDeprecated.

        :param a_callable: A callable to call.
        :param args: The positional arguments for the callable
        :param kwargs: The keyword arguments for the callable
        :return: A tuple (warnings, result). result is the result of calling
            a_callable(``*args``, ``**kwargs``).
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

        Note that this only captures warnings raised by symbol_versioning.warn,
        not other callers that go direct to the warning module.

        :param deprecation_format: The deprecation format that the callable
            should have been deprecated with. This is the same type as the
            parameter to deprecated_method/deprecated_function. If the
            callable is not deprecated with this format, an assertion error
            will be raised.
        :param a_callable: A callable to call. This may be a bound method or
            a regular function. It will be called with ``*args`` and
            ``**kwargs``.
        :param args: The positional arguments for the callable
        :param kwargs: The keyword arguments for the callable
        :return: The result of a_callable(``*args``, ``**kwargs``)
        """
        call_warnings, result = self._capture_warnings(a_callable,
            *args, **kwargs)
        expected_first_warning = symbol_versioning.deprecation_string(
            a_callable, deprecation_format)
        if len(call_warnings) == 0:
            self.fail("No deprecation warning generated by call to %s" %
                a_callable)
        self.assertEqual(expected_first_warning, call_warnings[0])
        return result

    def callDeprecated(self, expected, callable, *args, **kwargs):
        """Assert that a callable is deprecated in a particular way.

        This is a very precise test for unusual requirements. The 
        applyDeprecated helper function is probably more suited for most tests
        as it allows you to simply specify the deprecation format being used
        and will ensure that that is issued for the function being called.

        Note that this only captures warnings raised by symbol_versioning.warn,
        not other callers that go direct to the warning module.

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
            'APPDATA': None,  # bzr now use Win32 API and don't rely on APPDATA
            'BZR_EMAIL': None,
            'BZREMAIL': None, # may still be present in the environment
            'EMAIL': None,
            'BZR_PROGRESS_BAR': None,
            # SSH Agent
            'SSH_AUTH_SOCK': None,
            # Proxies
            'http_proxy': None,
            'HTTP_PROXY': None,
            'https_proxy': None,
            'HTTPS_PROXY': None,
            'no_proxy': None,
            'NO_PROXY': None,
            'all_proxy': None,
            'ALL_PROXY': None,
            # Nobody cares about these ones AFAIK. So far at
            # least. If you do (care), please update this comment
            # -- vila 20061212
            'ftp_proxy': None,
            'FTP_PROXY': None,
            'BZR_REMOTE_PATH': None,
        }
        self.__old_env = {}
        self.addCleanup(self._restoreEnvironment)
        for name, value in new_env.iteritems():
            self._captureVar(name, value)

    def _captureVar(self, name, newvalue):
        """Set an environment variable, and reset it when finished."""
        self.__old_env[name] = osutils.set_or_unset_env(name, newvalue)

    def _restore_debug_flags(self):
        debug.debug_flags.clear()
        debug.debug_flags.update(self._preserved_debug_flags)

    def _restoreEnvironment(self):
        for name, value in self.__old_env.iteritems():
            osutils.set_or_unset_env(name, value)

    def _restoreHooks(self):
        for klass, hooks in self._preserved_hooks.items():
            setattr(klass, 'hooks', hooks)

    def knownFailure(self, reason):
        """This test has failed for some known reason."""
        raise KnownFailure(reason)

    def run(self, result=None):
        if result is None: result = self.defaultTestResult()
        for feature in getattr(self, '_test_needs_features', []):
            if not feature.available():
                result.startTest(self)
                if getattr(result, 'addNotSupported', None):
                    result.addNotSupported(self, feature)
                else:
                    result.addSuccess(self)
                result.stopTest(self)
                return
        return unittest.TestCase.run(self, result)

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

        # Actually pop the cleanups from the list so tearDown running
        # twice is safe (this happens for skipped tests).
        while self._cleanups:
            self._cleanups.pop()()

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
                try:
                    os.remove(self._log_file_name)
                except OSError, e:
                    if sys.platform == 'win32' and e.errno == errno.EACCES:
                        print >>sys.stderr, ('Unable to delete log file '
                                             ' %r' % self._log_file_name)
                    else:
                        raise
            return log_contents
        else:
            return "DELETED log file to reduce memory footprint"

    @deprecated_method(zero_eighteen)
    def capture(self, cmd, retcode=0):
        """Shortcut that splits cmd into words, runs, and returns stdout"""
        return self.run_bzr_captured(cmd.split(), retcode=retcode)[0]

    def requireFeature(self, feature):
        """This test requires a specific feature is available.

        :raises UnavailableFeature: When feature is not available.
        """
        if not feature.available():
            raise UnavailableFeature(feature)

    @deprecated_method(zero_eighteen)
    def run_bzr_captured(self, argv, retcode=0, encoding=None, stdin=None,
                         working_dir=None):
        """Invoke bzr and return (stdout, stderr).

        Don't call this method, just use run_bzr() which is equivalent.

        :param argv: Arguments to invoke bzr.  This may be either a 
            single string, in which case it is split by shlex into words, 
            or a list of arguments.
        :param retcode: Expected return code, or None for don't-care.
        :param encoding: Encoding for sys.stdout and sys.stderr
        :param stdin: A string to be used as stdin for the command.
        :param working_dir: Change to this directory before running
        """
        return self._run_bzr_autosplit(argv, retcode=retcode,
                encoding=encoding, stdin=stdin, working_dir=working_dir,
                )

    def _run_bzr_autosplit(self, args, retcode, encoding, stdin,
            working_dir):
        """Run bazaar command line, splitting up a string command line."""
        if isinstance(args, basestring):
            args = list(shlex.split(args))
        return self._run_bzr_core(args, retcode=retcode,
                encoding=encoding, stdin=stdin, working_dir=working_dir,
                )

    def _run_bzr_core(self, args, retcode, encoding, stdin,
            working_dir):
        if encoding is None:
            encoding = bzrlib.user_encoding
        stdout = StringIOWrapper()
        stderr = StringIOWrapper()
        stdout.encoding = encoding
        stderr.encoding = encoding

        self.log('run bzr: %r', args)
        # FIXME: don't call into logging here
        handler = logging.StreamHandler(stderr)
        handler.setLevel(logging.INFO)
        logger = logging.getLogger('')
        logger.addHandler(handler)
        old_ui_factory = ui.ui_factory
        ui.ui_factory = TestUIFactory(stdin=stdin, stdout=stdout, stderr=stderr)

        cwd = None
        if working_dir is not None:
            cwd = osutils.getcwd()
            os.chdir(working_dir)

        try:
            result = self.apply_redirected(ui.ui_factory.stdin,
                stdout, stderr,
                bzrlib.commands.run_bzr_catch_errors,
                args)
        finally:
            logger.removeHandler(handler)
            ui.ui_factory = old_ui_factory
            if cwd is not None:
                os.chdir(cwd)

        out = stdout.getvalue()
        err = stderr.getvalue()
        if out:
            self.log('output:\n%r', out)
        if err:
            self.log('errors:\n%r', err)
        if retcode is not None:
            self.assertEquals(retcode, result,
                              message='Unexpected return code')
        return out, err

    def run_bzr(self, *args, **kwargs):
        """Invoke bzr, as if it were run from the command line.

        The argument list should not include the bzr program name - the
        first argument is normally the bzr command.  Arguments may be
        passed in three ways:

        1- A list of strings, eg ["commit", "a"].  This is recommended
        when the command contains whitespace or metacharacters, or 
        is built up at run time.

        2- A single string, eg "add a".  This is the most convenient 
        for hardcoded commands.

        3- Several varargs parameters, eg run_bzr("add", "a").  
        This is not recommended for new code.

        This runs bzr through the interface that catches and reports
        errors, and with logging set to something approximating the
        default, so that error reporting can be checked.

        This should be the main method for tests that want to exercise the
        overall behavior of the bzr application (rather than a unit test
        or a functional test of the library.)

        This sends the stdout/stderr results into the test's log,
        where it may be useful for debugging.  See also run_captured.

        :keyword stdin: A string to be used as stdin for the command.
        :keyword retcode: The status code the command should return;
            default 0.
        :keyword working_dir: The directory to run the command in
        :keyword error_regexes: A list of expected error messages.  If
            specified they must be seen in the error output of the command.
        """
        retcode = kwargs.pop('retcode', 0)
        encoding = kwargs.pop('encoding', None)
        stdin = kwargs.pop('stdin', None)
        working_dir = kwargs.pop('working_dir', None)
        error_regexes = kwargs.pop('error_regexes', [])

        if len(args) == 1:
            if isinstance(args[0], (list, basestring)):
                args = args[0]
        else:
            symbol_versioning.warn(zero_eighteen % "passing varargs to run_bzr",
                                   DeprecationWarning, stacklevel=3)

        out, err = self._run_bzr_autosplit(args=args,
            retcode=retcode,
            encoding=encoding, stdin=stdin, working_dir=working_dir,
            )

        for regex in error_regexes:
            self.assertContainsRe(err, regex)
        return out, err

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

        :return: (out, err) The actual output of running the command (in case
            you want to do more inspection)

        Examples of use::

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
        kwargs['error_regexes'] = error_regexes
        out, err = self.run_bzr(*args, **kwargs)
        return out, err

    def run_bzr_subprocess(self, *args, **kwargs):
        """Run bzr in a subprocess for testing.

        This starts a new Python interpreter and runs bzr in there. 
        This should only be used for tests that have a justifiable need for
        this isolation: e.g. they are testing startup time, or signal
        handling, or early startup code, etc.  Subprocess code can't be 
        profiled or debugged so easily.

        :keyword retcode: The status code that is expected.  Defaults to 0.  If
            None is supplied, the status code is not checked.
        :keyword env_changes: A dictionary which lists changes to environment
            variables. A value of None will unset the env variable.
            The values must be strings. The change will only occur in the
            child, so you don't need to fix the environment after running.
        :keyword universal_newlines: Convert CRLF => LF
        :keyword allow_plugins: By default the subprocess is run with
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
            for example ``['--version']``.
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
            if ie.kind == 'directory':
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

    def reduceLockdirTimeout(self):
        """Reduce the default lock timeout for the duration of the test, so that
        if LockContention occurs during a test, it does so quickly.

        Tests that expect to provoke LockContention errors should call this.
        """
        orig_timeout = bzrlib.lockdir._DEFAULT_TIMEOUT_SECONDS
        def resetTimeout():
            bzrlib.lockdir._DEFAULT_TIMEOUT_SECONDS = orig_timeout
        self.addCleanup(resetTimeout)
        bzrlib.lockdir._DEFAULT_TIMEOUT_SECONDS = 0


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

    :cvar TEST_ROOT: Directory containing all temporary directories, plus
    a .bzr directory that stops us ascending higher into the filesystem.
    """

    TEST_ROOT = None
    _TEST_NAME = 'test'

    def __init__(self, methodName='runTest'):
        # allow test parameterisation after test construction and before test
        # execution. Variables that the parameteriser sets need to be 
        # ones that are not set by setUp, or setUp will trash them.
        super(TestCaseWithMemoryTransport, self).__init__(methodName)
        self.vfs_transport_factory = default_transport
        self.transport_server = None
        self.transport_readonly_server = None
        self.__vfs_server = None

    def get_transport(self, relpath=None):
        """Return a writeable transport.

        This transport is for the test scratch space relative to
        "self._test_root""
        
        :param relpath: a path relative to the base url.
        """
        t = get_transport(self.get_url(relpath))
        self.assertFalse(t.is_readonly())
        return t

    def get_readonly_transport(self, relpath=None):
        """Return a readonly transport for the test scratch space
        
        This can be used to test that operations which should only need
        readonly access in fact do not try to write.

        :param relpath: a path relative to the base url.
        """
        t = get_transport(self.get_readonly_url(relpath))
        self.assertTrue(t.is_readonly())
        return t

    def create_transport_readonly_server(self):
        """Create a transport server from class defined at init.

        This is mostly a hook for daughter classes.
        """
        return self.transport_readonly_server()

    def get_readonly_server(self):
        """Get the server instance for the readonly transport

        This is useful for some tests with specific servers to do diagnostics.
        """
        if self.__readonly_server is None:
            if self.transport_readonly_server is None:
                # readonly decorator requested
                # bring up the server
                self.__readonly_server = ReadonlyServer()
                self.__readonly_server.setUp(self.get_vfs_only_server())
            else:
                self.__readonly_server = self.create_transport_readonly_server()
                self.__readonly_server.setUp(self.get_vfs_only_server())
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
        return self._adjust_url(base, relpath)

    def get_vfs_only_server(self):
        """Get the vfs only read/write server instance.

        This is useful for some tests with specific servers that need
        diagnostics.

        For TestCaseWithMemoryTransport this is always a MemoryServer, and there
        is no means to override it.
        """
        if self.__vfs_server is None:
            self.__vfs_server = MemoryServer()
            self.__vfs_server.setUp()
            self.addCleanup(self.__vfs_server.tearDown)
        return self.__vfs_server

    def get_server(self):
        """Get the read/write server instance.

        This is useful for some tests with specific servers that need
        diagnostics.

        This is built from the self.transport_server factory. If that is None,
        then the self.get_vfs_server is returned.
        """
        if self.__server is None:
            if self.transport_server is None or self.transport_server is self.vfs_transport_factory:
                return self.get_vfs_only_server()
            else:
                # bring up a decorated means of access to the vfs only server.
                self.__server = self.transport_server()
                try:
                    self.__server.setUp(self.get_vfs_only_server())
                except TypeError, e:
                    # This should never happen; the try:Except here is to assist
                    # developers having to update code rather than seeing an
                    # uninformative TypeError.
                    raise Exception, "Old server API in use: %s, %s" % (self.__server, e)
            self.addCleanup(self.__server.tearDown)
        return self.__server

    def _adjust_url(self, base, relpath):
        """Get a URL (or maybe a path) for the readwrite transport.

        This will either be backed by '.' or to an equivalent non-file based
        facility.
        relpath provides for clients to get a path relative to the base url.
        These should only be downwards relative, not upwards.
        """
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

    def get_url(self, relpath=None):
        """Get a URL (or maybe a path) for the readwrite transport.

        This will either be backed by '.' or to an equivalent non-file based
        facility.
        relpath provides for clients to get a path relative to the base url.
        These should only be downwards relative, not upwards.
        """
        base = self.get_server().get_url()
        return self._adjust_url(base, relpath)

    def get_vfs_only_url(self, relpath=None):
        """Get a URL (or maybe a path for the plain old vfs transport.

        This will never be a smart protocol.  It always has all the
        capabilities of the local filesystem, but it might actually be a
        MemoryTransport or some other similar virtual filesystem.

        This is the backing transport (if any) of the server returned by
        get_url and get_readonly_url.

        :param relpath: provides for clients to get a path relative to the base
            url.  These should only be downwards relative, not upwards.
        :return: A URL
        """
        base = self.get_vfs_only_server().get_url()
        return self._adjust_url(base, relpath)

    def _make_test_root(self):
        if TestCaseWithMemoryTransport.TEST_ROOT is not None:
            return
        root = tempfile.mkdtemp(prefix='testbzr-', suffix='.tmp')
        TestCaseWithMemoryTransport.TEST_ROOT = root
        
        # make a fake bzr directory there to prevent any tests propagating
        # up onto the source directory's real branch
        bzrdir.BzrDir.create_standalone_workingtree(root)

        # The same directory is used by all tests, and we're not specifically
        # told when all tests are finished.  This will do.
        atexit.register(_rmtree_temp_dir, root)

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
                t.ensure_base()
            if format is None:
                format = 'default'
            if isinstance(format, basestring):
                format = bzrdir.format_registry.make_bzrdir(format)
            return format.initialize_on_transport(t)
        except errors.UninitializableFormat:
            raise TestSkipped("Format %s is not initializable." % format)

    def make_repository(self, relpath, shared=False, format=None):
        """Create a repository on our default transport at relpath.
        
        Note that relpath must be a relative path, not a full url.
        """
        # FIXME: If you create a remoterepository this returns the underlying
        # real format, which is incorrect.  Actually we should make sure that 
        # RemoteBzrDir returns a RemoteRepository.
        # maybe  mbp 20070410
        made_control = self.make_bzrdir(relpath, format=format)
        return made_control.create_repository(shared=shared)

    def make_branch_and_memory_tree(self, relpath, format=None):
        """Create a branch on the default transport and a MemoryTree for it."""
        b = self.make_branch(relpath, format=format)
        return memorytree.MemoryTree.create_on_branch(b)

    def overrideEnvironmentForTesting(self):
        os.environ['HOME'] = self.test_home_dir
        os.environ['BZR_HOME'] = self.test_home_dir
        
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
        self.reduceLockdirTimeout()

     
class TestCaseInTempDir(TestCaseWithMemoryTransport):
    """Derived class that runs a test within a temporary directory.

    This is useful for tests that need to create a branch, etc.

    The directory is created in a slightly complex way: for each
    Python invocation, a new temporary top-level directory is created.
    All test cases create their own directory within that.  If the
    tests complete successfully, the directory is removed.

    :ivar test_base_dir: The path of the top-level directory for this 
    test, which contains a home directory and a work directory.

    :ivar test_home_dir: An initially empty directory under test_base_dir
    which is used as $HOME for this test.

    :ivar test_dir: A directory under test_base_dir used as the current
    directory when the test proper is run.
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
        # create a directory within the top level test directory
        candidate_dir = tempfile.mkdtemp(dir=self.TEST_ROOT)
        # now create test and home directories within this dir
        self.test_base_dir = candidate_dir
        self.test_home_dir = self.test_base_dir + '/home'
        os.mkdir(self.test_home_dir)
        self.test_dir = self.test_base_dir + '/work'
        os.mkdir(self.test_dir)
        os.chdir(self.test_dir)
        # put name of test inside
        f = file(self.test_base_dir + '/name', 'w')
        try:
            f.write(self.id())
        finally:
            f.close()
        self.addCleanup(self.deleteTestDir)

    def deleteTestDir(self):
        os.chdir(self.TEST_ROOT)
        _rmtree_temp_dir(self.test_base_dir)

    def build_tree(self, shape, line_endings='binary', transport=None):
        """Build a test tree according to a pattern.

        shape is a sequence of file specifications.  If the final
        character is '/', a directory is created.

        This assumes that all the elements in the tree being built are new.

        This doesn't add anything to a branch.

        :param line_endings: Either 'binary' or 'native'
            in binary mode, exact contents are written in native mode, the
            line endings match the default platform endings.
        :param transport: A transport to write to, for building trees on VFS's.
            If the transport is readonly or None, "." is opened automatically.
        :return: None
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
                    raise errors.BzrError(
                        'Invalid line ending request %r' % line_endings)
                content = "contents of %s%s" % (name.encode('utf-8'), end)
                transport.put_bytes_non_atomic(urlutils.escape(name), content)

    def build_tree_contents(self, shape):
        build_tree_contents(shape)

    def assertFileEqual(self, content, path):
        """Fail if path does not contain 'content'."""
        self.failUnlessExists(path)
        f = file(path, 'rb')
        try:
            s = f.read()
        finally:
            f.close()
        self.assertEqualDiff(content, s)

    def failUnlessExists(self, path):
        """Fail unless path or paths, which may be abs or relative, exist."""
        if not isinstance(path, basestring):
            for p in path:
                self.failUnlessExists(p)
        else:
            self.failUnless(osutils.lexists(path),path+" does not exist")

    def failIfExists(self, path):
        """Fail if path or paths, which may be abs or relative, exist."""
        if not isinstance(path, basestring):
            for p in path:
                self.failIfExists(p)
        else:
            self.failIf(osutils.lexists(path),path+" exists")

    def assertInWorkingTree(self,path,root_path='.',tree=None):
        """Assert whether path or paths are in the WorkingTree"""
        if tree is None:
            tree = workingtree.WorkingTree.open(root_path)
        if not isinstance(path, basestring):
            for p in path:
                self.assertInWorkingTree(p,tree=tree)
        else:
            self.assertIsNot(tree.path2id(path), None,
                path+' not in working tree.')

    def assertNotInWorkingTree(self,path,root_path='.',tree=None):
        """Assert whether path or paths are not in the WorkingTree"""
        if tree is None:
            tree = workingtree.WorkingTree.open(root_path)
        if not isinstance(path, basestring):
            for p in path:
                self.assertNotInWorkingTree(p,tree=tree)
        else:
            self.assertIs(tree.path2id(path), None, path+' in working tree.')


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

    def get_vfs_only_server(self):
        """See TestCaseWithMemoryTransport.

        This is useful for some tests with specific servers that need
        diagnostics.
        """
        if self.__vfs_server is None:
            self.__vfs_server = self.vfs_transport_factory()
            self.__vfs_server.setUp()
            self.addCleanup(self.__vfs_server.tearDown)
        return self.__vfs_server

    def make_branch_and_tree(self, relpath, format=None):
        """Create a branch on the transport and a tree locally.

        If the transport is not a LocalTransport, the Tree can't be created on
        the transport.  In that case if the vfs_transport_factory is
        LocalURLServer the working tree is created in the local
        directory backing the transport, and the returned tree's branch and
        repository will also be accessed locally. Otherwise a lightweight
        checkout is created and returned.

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
            # transport can't support them, then we keep the non-disk-backed
            # branch and create a local checkout.
            if self.vfs_transport_factory is LocalURLServer:
                # the branch is colocated on disk, we cannot create a checkout.
                # hopefully callers will expect this.
                local_controldir= bzrdir.BzrDir.open(self.get_vfs_only_url(relpath))
                return local_controldir.create_workingtree()
            else:
                return b.create_checkout(relpath, lightweight=True)

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

    def assertTreesEqual(self, left, right):
        """Check that left and right have the same content and properties."""
        # we use a tree delta to check for equality of the content, and we
        # manually check for equality of other things such as the parents list.
        self.assertEqual(left.get_parent_ids(), right.get_parent_ids())
        differences = left.changes_from(right)
        self.assertFalse(differences.has_changed(),
            "Trees %r and %r are different: %r" % (left, right, differences))

    def setUp(self):
        super(TestCaseWithTransport, self).setUp()
        self.__vfs_server = None


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
        if not self.vfs_transport_factory == MemoryServer:
            self.transport_readonly_server = HttpServer


def filter_suite_by_re(suite, pattern, exclude_pattern=None,
                       random_order=False):
    """Create a test suite by filtering another one.
    
    :param suite:           the source suite
    :param pattern:         pattern that names must match
    :param exclude_pattern: pattern that names must not match, if any
    :param random_order:    if True, tests in the new suite will be put in
                            random order
    :returns: the newly created suite
    """ 
    return sort_suite_by_re(suite, pattern, exclude_pattern,
        random_order, False)


def sort_suite_by_re(suite, pattern, exclude_pattern=None,
                     random_order=False, append_rest=True):
    """Create a test suite by sorting another one.
    
    :param suite:           the source suite
    :param pattern:         pattern that names must match in order to go
                            first in the new suite
    :param exclude_pattern: pattern that names must not match, if any
    :param random_order:    if True, tests in the new suite will be put in
                            random order
    :param append_rest:     if False, pattern is a strict filter and not
                            just an ordering directive
    :returns: the newly created suite
    """ 
    first = []
    second = []
    filter_re = re.compile(pattern)
    if exclude_pattern is not None:
        exclude_re = re.compile(exclude_pattern)
    for test in iter_suite_tests(suite):
        test_id = test.id()
        if exclude_pattern is None or not exclude_re.search(test_id):
            if filter_re.search(test_id):
                first.append(test)
            elif append_rest:
                second.append(test)
    if random_order:
        random.shuffle(first)
        random.shuffle(second)
    return TestUtil.TestSuite(first + second)


def run_suite(suite, name='test', verbose=False, pattern=".*",
              stop_on_failure=False,
              transport=None, lsprof_timed=None, bench_history=None,
              matching_tests_first=None,
              list_only=False,
              random_seed=None,
              exclude_pattern=None,
              ):
    TestCase._gather_lsprof_in_benchmarks = lsprof_timed
    if verbose:
        verbosity = 2
    else:
        verbosity = 1
    runner = TextTestRunner(stream=sys.stdout,
                            descriptions=0,
                            verbosity=verbosity,
                            bench_history=bench_history,
                            list_only=list_only,
                            )
    runner.stop_on_failure=stop_on_failure
    # Initialise the random number generator and display the seed used.
    # We convert the seed to a long to make it reuseable across invocations.
    random_order = False
    if random_seed is not None:
        random_order = True
        if random_seed == "now":
            random_seed = long(time.time())
        else:
            # Convert the seed to a long if we can
            try:
                random_seed = long(random_seed)
            except:
                pass
        runner.stream.writeln("Randomizing test order using seed %s\n" %
            (random_seed))
        random.seed(random_seed)
    # Customise the list of tests if requested
    if pattern != '.*' or exclude_pattern is not None or random_order:
        if matching_tests_first:
            suite = sort_suite_by_re(suite, pattern, exclude_pattern,
                random_order)
        else:
            suite = filter_suite_by_re(suite, pattern, exclude_pattern,
                random_order)
    result = runner.run(suite)
    return result.wasSuccessful()


def selftest(verbose=False, pattern=".*", stop_on_failure=True,
             transport=None,
             test_suite_factory=None,
             lsprof_timed=None,
             bench_history=None,
             matching_tests_first=None,
             list_only=False,
             random_seed=None,
             exclude_pattern=None):
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
                     stop_on_failure=stop_on_failure,
                     transport=transport,
                     lsprof_timed=lsprof_timed,
                     bench_history=bench_history,
                     matching_tests_first=matching_tests_first,
                     list_only=list_only,
                     random_seed=random_seed,
                     exclude_pattern=exclude_pattern)
    finally:
        default_transport = old_transport


def test_suite():
    """Build and return TestSuite for the whole of bzrlib.
    
    This function can be replaced if you need to change the default test
    suite on a global basis, but it is not encouraged.
    """
    testmod_names = [
                   'bzrlib.util.tests.test_bencode',
                   'bzrlib.tests.test_ancestry',
                   'bzrlib.tests.test_annotate',
                   'bzrlib.tests.test_api',
                   'bzrlib.tests.test_atomicfile',
                   'bzrlib.tests.test_bad_files',
                   'bzrlib.tests.test_branch',
                   'bzrlib.tests.test_branchbuilder',
                   'bzrlib.tests.test_bugtracker',
                   'bzrlib.tests.test_bundle',
                   'bzrlib.tests.test_bzrdir',
                   'bzrlib.tests.test_cache_utf8',
                   'bzrlib.tests.test_commands',
                   'bzrlib.tests.test_commit',
                   'bzrlib.tests.test_commit_merge',
                   'bzrlib.tests.test_config',
                   'bzrlib.tests.test_conflicts',
                   'bzrlib.tests.test_pack',
                   'bzrlib.tests.test_counted_lock',
                   'bzrlib.tests.test_decorators',
                   'bzrlib.tests.test_delta',
                   'bzrlib.tests.test_deprecated_graph',
                   'bzrlib.tests.test_diff',
                   'bzrlib.tests.test_dirstate',
                   'bzrlib.tests.test_errors',
                   'bzrlib.tests.test_escaped_store',
                   'bzrlib.tests.test_extract',
                   'bzrlib.tests.test_fetch',
                   'bzrlib.tests.test_ftp_transport',
                   'bzrlib.tests.test_generate_docs',
                   'bzrlib.tests.test_generate_ids',
                   'bzrlib.tests.test_globbing',
                   'bzrlib.tests.test_gpg',
                   'bzrlib.tests.test_graph',
                   'bzrlib.tests.test_hashcache',
                   'bzrlib.tests.test_help',
                   'bzrlib.tests.test_hooks',
                   'bzrlib.tests.test_http',
                   'bzrlib.tests.test_http_response',
                   'bzrlib.tests.test_https_ca_bundle',
                   'bzrlib.tests.test_identitymap',
                   'bzrlib.tests.test_ignores',
                   'bzrlib.tests.test_index',
                   'bzrlib.tests.test_info',
                   'bzrlib.tests.test_inv',
                   'bzrlib.tests.test_knit',
                   'bzrlib.tests.test_lazy_import',
                   'bzrlib.tests.test_lazy_regex',
                   'bzrlib.tests.test_lockdir',
                   'bzrlib.tests.test_lockable_files',
                   'bzrlib.tests.test_log',
                   'bzrlib.tests.test_lsprof',
                   'bzrlib.tests.test_memorytree',
                   'bzrlib.tests.test_merge',
                   'bzrlib.tests.test_merge3',
                   'bzrlib.tests.test_merge_core',
                   'bzrlib.tests.test_merge_directive',
                   'bzrlib.tests.test_missing',
                   'bzrlib.tests.test_msgeditor',
                   'bzrlib.tests.test_nonascii',
                   'bzrlib.tests.test_options',
                   'bzrlib.tests.test_osutils',
                   'bzrlib.tests.test_osutils_encodings',
                   'bzrlib.tests.test_patch',
                   'bzrlib.tests.test_patches',
                   'bzrlib.tests.test_permissions',
                   'bzrlib.tests.test_plugins',
                   'bzrlib.tests.test_progress',
                   'bzrlib.tests.test_reconcile',
                   'bzrlib.tests.test_registry',
                   'bzrlib.tests.test_remote',
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
                   'bzrlib.tests.test_smart',
                   'bzrlib.tests.test_smart_add',
                   'bzrlib.tests.test_smart_transport',
                   'bzrlib.tests.test_smtp_connection',
                   'bzrlib.tests.test_source',
                   'bzrlib.tests.test_ssh_transport',
                   'bzrlib.tests.test_status',
                   'bzrlib.tests.test_store',
                   'bzrlib.tests.test_strace',
                   'bzrlib.tests.test_subsume',
                   'bzrlib.tests.test_symbol_versioning',
                   'bzrlib.tests.test_tag',
                   'bzrlib.tests.test_testament',
                   'bzrlib.tests.test_textfile',
                   'bzrlib.tests.test_textmerge',
                   'bzrlib.tests.test_timestamp',
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
                   'bzrlib.tests.test_workingtree_4',
                   'bzrlib.tests.test_wsgi',
                   'bzrlib.tests.test_xml',
                   ]
    test_transport_implementations = [
        'bzrlib.tests.test_transport_implementations',
        'bzrlib.tests.test_read_bundle',
        ]
    suite = TestUtil.TestSuite()
    loader = TestUtil.TestLoader()
    suite.addTest(loader.loadTestsFromModuleNames(testmod_names))
    from bzrlib.tests.test_transport_implementations import TransportTestProviderAdapter
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
            default_encoding = sys.getdefaultencoding()
            try:
                plugin_suite = plugin.test_suite()
            except ImportError, e:
                bzrlib.trace.warning(
                    'Unable to test plugin "%s": %s', name, e)
            else:
                suite.addTest(plugin_suite)
            if default_encoding != sys.getdefaultencoding():
                bzrlib.trace.warning(
                    'Plugin "%s" tried to reset default encoding to: %s', name,
                    sys.getdefaultencoding())
                reload(sys)
                sys.setdefaultencoding(default_encoding)
    return suite


def adapt_modules(mods_list, adapter, loader, suite):
    """Adapt the modules in mods_list using adapter and add to suite."""
    for test in iter_suite_tests(loader.loadTestsFromModuleNames(mods_list)):
        suite.addTests(adapter.adapt(test))


def _rmtree_temp_dir(dirname):
    # If LANG=C we probably have created some bogus paths
    # which rmtree(unicode) will fail to delete
    # so make sure we are using rmtree(str) to delete everything
    # except on win32, where rmtree(str) will fail
    # since it doesn't have the property of byte-stream paths
    # (they are either ascii or mbcs)
    if sys.platform == 'win32':
        # make sure we are using the unicode win32 api
        dirname = unicode(dirname)
    else:
        dirname = dirname.encode(sys.getfilesystemencoding())
    try:
        osutils.rmtree(dirname)
    except OSError, e:
        if sys.platform == 'win32' and e.errno == errno.EACCES:
            print >>sys.stderr, ('Permission denied: '
                                 'unable to remove testing dir '
                                 '%s' % os.path.basename(dirname))
        else:
            raise


class Feature(object):
    """An operating system Feature."""

    def __init__(self):
        self._available = None

    def available(self):
        """Is the feature available?

        :return: True if the feature is available.
        """
        if self._available is None:
            self._available = self._probe()
        return self._available

    def _probe(self):
        """Implement this method in concrete features.

        :return: True if the feature is available.
        """
        raise NotImplementedError

    def __str__(self):
        if getattr(self, 'feature_name', None):
            return self.feature_name()
        return self.__class__.__name__


class TestScenarioApplier(object):
    """A tool to apply scenarios to tests."""

    def adapt(self, test):
        """Return a TestSuite containing a copy of test for each scenario."""
        result = unittest.TestSuite()
        for scenario in self.scenarios:
            result.addTest(self.adapt_test_to_scenario(test, scenario))
        return result

    def adapt_test_to_scenario(self, test, scenario):
        """Copy test and apply scenario to it.

        :param test: A test to adapt.
        :param scenario: A tuple describing the scenarion.
            The first element of the tuple is the new test id.
            The second element is a dict containing attributes to set on the
            test.
        :return: The adapted test.
        """
        from copy import deepcopy
        new_test = deepcopy(test)
        for name, value in scenario[1].items():
            setattr(new_test, name, value)
        new_id = "%s(%s)" % (new_test.id(), scenario[0])
        new_test.id = lambda: new_id
        return new_test
