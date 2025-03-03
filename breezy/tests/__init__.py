# Copyright (C) 2005-2013, 2015, 2016 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Testing framework extensions."""

# NOTE: Some classes in here use camelCaseNaming() rather than
# underscore_naming().  That's for consistency with unittest; it's not the
# general style of breezy.  Please continue that consistency when adding e.g.
# new assertFoo() methods.

import atexit
import codecs
import contextlib
import copy
import difflib
import doctest
import errno
import functools
import itertools
import logging
import math
import os
import platform
import pprint
import random
import re
import shlex
import site
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest
import warnings
from io import BytesIO, StringIO, TextIOWrapper
from typing import Callable
from unittest import SkipTest as TestSkipped

import testtools
from testtools import content

import breezy
from breezy.bzr import chk_map

from .. import (
    branchbuilder,
    config,
    controldir,
    debug,
    errors,
    hooks,
    i18n,
    lockdir,
    osutils,
    pyutils,
    registry,
    symbol_versioning,
    trace,
    ui,
    urlutils,
    workingtree,
)
from .. import commands as _mod_commands
from .. import lock as _mod_lock
from .. import plugin as _mod_plugin
from .. import transport as _mod_transport

try:
    import breezy.lsprof
except ModuleNotFoundError:
    # lsprof not available
    pass
from ..bzr.smart import client, request
from ..tests import TestUtil, fixtures, test_server, treeshape, ui_testing
from ..transport import memory, pathfilter

# Mark this python module as being part of the implementation
# of unittest: this gives us better tracebacks where the last
# shown frame is the test code, not our assertXYZ.
__unittest = 1

default_transport = test_server.LocalURLServer


_unitialized_attr = object()
"""A sentinel needed to act as a default value in a method signature."""


# Subunit result codes, defined here to prevent a hard dependency on subunit.
SUBUNIT_SEEK_SET = 0
SUBUNIT_SEEK_CUR = 1

# These are intentionally brought into this namespace. That way plugins, etc
# can just "from breezy.tests import TestCase, TestLoader, etc"
TestSuite = TestUtil.TestSuite
TestLoader = TestUtil.TestLoader

# Tests should run in a clean and clearly defined environment. The goal is to
# keep them isolated from the running environment as mush as possible. The test
# framework ensures the variables defined below are set (or deleted if the
# value is None) before a test is run and reset to their original value after
# the test is run. Generally if some code depends on an environment variable,
# the tests should start without this variable in the environment. There are a
# few exceptions but you shouldn't violate this rule lightly.
isolated_environ = {
    "BRZ_HOME": None,
    "HOME": None,
    "GNUPGHOME": None,
    "XDG_CONFIG_HOME": None,
    # brz now uses the Win32 API and doesn't rely on APPDATA, but the
    # tests do check our impls match APPDATA
    "BRZ_EDITOR": None,  # test_msgeditor manipulates this variable
    "VISUAL": None,
    "EDITOR": None,
    "BRZ_EMAIL": None,
    "BZREMAIL": None,  # may still be present in the environment
    "EMAIL": "jrandom@example.com",  # set EMAIL as brz does not guess
    "BRZ_PROGRESS_BAR": None,
    # Trap leaks to $XDG_CACHE_HOME/breezy/brz.log. This occurs when tests use
    # TestCase as a base class instead of TestCaseInTempDir. Tests inheriting
    # from TestCase should not use disk resources, BRZ_LOG is one.
    "BRZ_LOG": "/you-should-use-TestCaseInTempDir-if-you-need-a-log-file",
    "BRZ_PLUGIN_PATH": "-site",
    "BRZ_DISABLE_PLUGINS": None,
    "BRZ_PLUGINS_AT": None,
    "BRZ_CONCURRENCY": None,
    # Make sure that any text ui tests are consistent regardless of
    # the environment the test case is run in; you may want tests that
    # test other combinations.  'dumb' is a reasonable guess for tests
    # going to a pipe or a BytesIO.
    "TERM": "dumb",
    "LINES": "25",
    "COLUMNS": "80",
    "BRZ_COLUMNS": "80",
    # Disable SSH Agent
    "SSH_AUTH_SOCK": None,
    # Proxies
    "http_proxy": None,
    "HTTP_PROXY": None,
    "https_proxy": None,
    "HTTPS_PROXY": None,
    "no_proxy": None,
    "NO_PROXY": None,
    "all_proxy": None,
    "ALL_PROXY": None,
    "BZR_REMOTE_PATH": None,
    "BRZ_SSH": None,
    # Generally speaking, we don't want apport reporting on crashes in
    # the test envirnoment unless we're specifically testing apport,
    # so that it doesn't leak into the real system environment.  We
    # use an env var so it propagates to subprocesses.
    "APPORT_DISABLE": "1",
}


def override_os_environ(test, env=None):
    """Modify os.environ keeping a copy.

    :param test: A test instance

    :param env: A dict containing variable definitions to be installed
    """
    if env is None:
        env = isolated_environ
    test._original_os_environ = dict(**os.environ)
    for var in env:
        osutils.set_or_unset_env(var, env[var])
        if var not in test._original_os_environ:
            # The var is new, add it with a value of None, so
            # restore_os_environ will delete it
            test._original_os_environ[var] = None


def restore_os_environ(test):
    """Restore os.environ to its original state.

    :param test: A test instance previously passed to override_os_environ.
    """
    for var, value in test._original_os_environ.items():
        # Restore the original value (or delete it if the value has been set to
        # None in override_os_environ).
        osutils.set_or_unset_env(var, value)


def _clear__type_equality_funcs(test):
    """Cleanup bound methods stored on TestCase instances.

    Clear the dict breaking a few (mostly) harmless cycles in the affected
    unittests released with Python 2.6 and initial Python 2.7 versions.

    For a few revisions between Python 2.7.1 and Python 2.7.2 that annoyingly
    shipped in Oneiric, an object with no clear method was used, hence the
    extra complications, see bug 809048 for details.
    """
    type_equality_funcs = getattr(test, "_type_equality_funcs", None)
    if type_equality_funcs is not None:
        tef_clear = getattr(type_equality_funcs, "clear", None)
        if tef_clear is None:
            tef_instance_dict = getattr(type_equality_funcs, "__dict__", None)
            if tef_instance_dict is not None:
                tef_clear = tef_instance_dict.clear
        if tef_clear is not None:
            tef_clear()


class ExtendedTestResult(testtools.TextTestResult):
    """Accepts, reports and accumulates the results of running tests.

    Compared to the unittest version this class adds support for
    profiling, benchmarking, stopping as soon as a test fails,  and
    skipping tests.  There are further-specialized subclasses for
    different types of display.

    When a test finishes, in whatever way, it calls one of the addSuccess,
    addFailure or addError methods.  These in turn may redirect to a more
    specific case for the special test results supported by our extended
    tests.

    Note that just one of these objects is fed the results from many tests.
    """

    stop_early = False

    def __init__(
        self,
        stream,
        descriptions,
        verbosity,
        bench_history=None,
        strict=False,
    ):
        """Construct new TestResult.

        :param bench_history: Optionally, a writable file object to accumulate
            benchmark results.
        """
        testtools.TextTestResult.__init__(self, stream)
        if bench_history is not None:
            from breezy.version import _get_bzr_source_tree

            src_tree = _get_bzr_source_tree()
            if src_tree:
                try:
                    revision_id = src_tree.get_parent_ids()[0]
                except IndexError:
                    # XXX: if this is a brand new tree, do the same as if there
                    # is no branch.
                    revision_id = b""
            else:
                # XXX: If there's no branch, what should we do?
                revision_id = b""
            bench_history.write("--date {} {}\n".format(time.time(), revision_id))
        self._bench_history = bench_history
        self.ui = ui.ui_factory
        self.num_tests = 0
        self.error_count = 0
        self.failure_count = 0
        self.known_failure_count = 0
        self.skip_count = 0
        self.not_applicable_count = 0
        self.unsupported = {}
        self.count = 0
        self._overall_start_time = time.time()
        self._strict = strict
        self._first_thread_leaker_id = None
        self._tests_leaking_threads_count = 0
        self._traceback_from_test = None

    def stopTestRun(self):
        run = self.testsRun
        actionTaken = "Ran"
        stopTime = time.time()
        timeTaken = stopTime - self.startTime
        # GZ 2010-07-19: Seems testtools has no printErrors method, and though
        #                the parent class method is similar have to duplicate
        self._show_list("ERROR", self.errors)
        self._show_list("FAIL", self.failures)
        self.stream.write(self.sep2)
        self.stream.write(
            "%s %d test%s in %.3fs\n\n"
            % (actionTaken, run, (run != 1 and "s") or "", timeTaken)
        )
        if not self.wasSuccessful():
            self.stream.write("FAILED (")
            failed, errored = map(len, (self.failures, self.errors))
            if failed:
                self.stream.write("failures=%d" % failed)
            if errored:
                if failed:
                    self.stream.write(", ")
                self.stream.write("errors=%d" % errored)
            if self.known_failure_count:
                if failed or errored:
                    self.stream.write(", ")
                self.stream.write("known_failure_count=%d" % self.known_failure_count)
            self.stream.write(")\n")
        else:
            if self.known_failure_count:
                self.stream.write("OK (known_failures=%d)\n" % self.known_failure_count)
            else:
                self.stream.write("OK\n")
        if self.skip_count > 0:
            skipped = self.skip_count
            self.stream.write(
                "%d test%s skipped\n" % (skipped, (skipped != 1 and "s") or "")
            )
        if self.unsupported:
            for feature, count in sorted(self.unsupported.items()):
                self.stream.write(
                    "Missing feature '%s' skipped %d tests.\n" % (feature, count)
                )
        if self._strict:
            self.wasStrictlySuccessful()
        else:
            self.wasSuccessful()
        if self._first_thread_leaker_id:
            self.stream.write(
                "%s is leaking threads among %d leaking tests.\n"
                % (self._first_thread_leaker_id, self._tests_leaking_threads_count)
            )
            # We don't report the main thread as an active one.
            self.stream.write(
                "%d non-main threads were left active in the end.\n"
                % (len(self._active_threads) - 1)
            )

    def getDescription(self, test):
        return test.id()

    def _extractBenchmarkTime(self, testCase, details=None):
        """Add a benchmark time for the current test case."""
        if details and "benchtime" in details:
            return float("".join(details["benchtime"].iter_bytes()))
        return getattr(testCase, "_benchtime", None)

    def _delta_to_float(self, a_timedelta, precision):
        # This calls ceiling to ensure that the most pessimistic view of time
        # taken is shown (rather than leaving it to the Python %f operator
        # to decide whether to round/floor/ceiling. This was added when we
        # had pyp3 test failures that suggest a floor was happening.
        shift = 10**precision
        return (
            math.ceil(
                (
                    a_timedelta.days * 86400.0
                    + a_timedelta.seconds
                    + a_timedelta.microseconds / 1000000.0
                )
                * shift
            )
            / shift
        )

    def _elapsedTestTimeString(self):
        """Return time string for overall time the current test has taken."""
        return self._formatTime(
            self._delta_to_float(self._now() - self._start_datetime, 3)
        )

    def _testTimeString(self, test_case):
        benchmark_time = self._extractBenchmarkTime(test_case)
        if benchmark_time is not None:
            return self._formatTime(benchmark_time) + "*"
        else:
            return self._elapsedTestTimeString()

    def _formatTime(self, seconds):
        """Format seconds as milliseconds with leading spaces."""
        # some benchmarks can take thousands of seconds to run, so we need 8
        # places
        return "%8dms" % (1000 * seconds)

    def _shortened_test_description(self, test):
        what = test.id()
        what = re.sub(r"^breezy\.tests\.", "", what)
        return what

    # GZ 2010-10-04: Cloned tests may end up harmlessly calling this method
    #                multiple times in a row, because the handler is added for
    #                each test but the container list is shared between cases.
    #                See lp:498869 lp:625574 and lp:637725 for background.
    def _record_traceback_from_test(self, exc_info):
        """Store the traceback from passed exc_info tuple till."""
        self._traceback_from_test = exc_info[2]

    def startTest(self, test):
        super().startTest(test)
        if self.count == 0:
            self.startTests()
        self.count += 1
        self.report_test_start(test)
        test.number = self.count
        self._recordTestStartTime()
        # Make testtools cases give us the real traceback on failure
        addOnException = getattr(test, "addOnException", None)
        if addOnException is not None:
            addOnException(self._record_traceback_from_test)
        # Only check for thread leaks on breezy derived test cases
        if isinstance(test, TestCase):
            test.addCleanup(self._check_leaked_threads, test)

    def stopTest(self, test):
        super().stopTest(test)
        # Manually break cycles, means touching various private things but hey
        getDetails = getattr(test, "getDetails", None)
        if getDetails is not None:
            getDetails().clear()
        _clear__type_equality_funcs(test)
        self._traceback_from_test = None

    def startTests(self):
        self.report_tests_starting()
        self._active_threads = threading.enumerate()

    def _check_leaked_threads(self, test):
        """See if any threads have leaked since last call.

        A sample of live threads is stored in the _active_threads attribute,
        when this method runs it compares the current live threads and any not
        in the previous sample are treated as having leaked.
        """
        now_active_threads = set(threading.enumerate())
        threads_leaked = now_active_threads.difference(self._active_threads)
        if threads_leaked:
            self._report_thread_leak(test, threads_leaked, now_active_threads)
            self._tests_leaking_threads_count += 1
            if self._first_thread_leaker_id is None:
                self._first_thread_leaker_id = test.id()
            self._active_threads = now_active_threads

    def _recordTestStartTime(self):
        """Record that a test has started."""
        self._start_datetime = self._now()

    def addError(self, test, err):
        """Tell result that test finished with an error.

        Called from the TestCase run() method when the test
        fails with an unexpected error.
        """
        self._post_mortem(self._traceback_from_test or err[2])
        super().addError(test, err)
        self.error_count += 1
        self.report_error(test, err)
        if self.stop_early:
            self.stop()

    def addFailure(self, test, err):
        """Tell result that test failed.

        Called from the TestCase run() method when the test
        fails because e.g. an assert() method failed.
        """
        self._post_mortem(self._traceback_from_test or err[2])
        super().addFailure(test, err)
        self.failure_count += 1
        self.report_failure(test, err)
        if self.stop_early:
            self.stop()

    def addSuccess(self, test, details=None):
        """Tell result that test completed successfully.

        Called from the TestCase run()
        """
        if self._bench_history is not None:
            benchmark_time = self._extractBenchmarkTime(test, details)
            if benchmark_time is not None:
                self._bench_history.write(
                    "{} {}\n".format(self._formatTime(benchmark_time), test.id())
                )
        self.report_success(test)
        super().addSuccess(test)
        test._log_contents = ""

    def addExpectedFailure(self, test, err):
        self.known_failure_count += 1
        self.report_known_failure(test, err)

    def addUnexpectedSuccess(self, test, details=None):
        """Tell result the test unexpectedly passed, counting as a failure.

        When the minimum version of testtools required becomes 0.9.8 this
        can be updated to use the new handling there.
        """
        super().addFailure(test, details=details)
        self.failure_count += 1
        self.report_unexpected_success(test, "".join(details["reason"].iter_text()))
        if self.stop_early:
            self.stop()

    def addNotSupported(self, test, feature):
        """The test will not be run because of a missing feature."""
        # this can be called in two different ways: it may be that the
        # test started running, and then raised (through requireFeature)
        # UnavailableFeature.  Alternatively this method can be called
        # while probing for features before running the test code proper; in
        # that case we will see startTest and stopTest, but the test will
        # never actually run.
        self.unsupported.setdefault(str(feature), 0)
        self.unsupported[str(feature)] += 1
        self.report_unsupported(test, feature)

    def addSkip(self, test, reason):
        """A test has not run for 'reason'."""
        self.skip_count += 1
        self.report_skip(test, reason)

    def addNotApplicable(self, test, reason):
        self.not_applicable_count += 1
        self.report_not_applicable(test, reason)

    def _count_stored_tests(self):
        """Count of tests instances kept alive due to not succeeding."""
        return self.error_count + self.failure_count + self.known_failure_count

    def _post_mortem(self, tb=None):
        """Start a PDB post mortem session."""
        if os.environ.get("BRZ_TEST_PDB", None):
            import pdb

            pdb.post_mortem(tb)

    def progress(self, offset, whence):
        """The test is adjusting the count of tests to run."""
        if whence == SUBUNIT_SEEK_SET:
            self.num_tests = offset
        elif whence == SUBUNIT_SEEK_CUR:
            self.num_tests += offset
        else:
            raise errors.BzrError("Unknown whence {!r}".format(whence))

    def report_tests_starting(self):
        """Display information before the test run begins."""
        bzr_path = osutils.realpath(sys.argv[0])
        self.stream.write("brz selftest: {}\n".format(bzr_path))
        self.stream.write("   {}\n".format(breezy.__path__[0]))
        self.stream.write(
            "   bzr-{} python-{} {}\n".format(
                breezy.version_string,
                breezy._format_version_tuple(sys.version_info),
                platform.platform(aliased=1),
            )
        )
        self.stream.write("\n")

    def report_test_start(self, test):
        """Display information on the test just about to be run."""

    def _report_thread_leak(self, test, leaked_threads, active_threads):
        """Display information on a test that leaked one or more threads."""
        # GZ 2010-09-09: A leak summary reported separately from the general
        #                thread debugging would be nice. Tests under subunit
        #                need something not using stream, perhaps adding a
        #                testtools details object would be fitting.
        if "threads" in selftest_debug_flags:
            self.stream.write(
                "%s is leaking, active is now %d\n" % (test.id(), len(active_threads))
            )

    def startTestRun(self):
        self.startTime = time.time()

    def report_success(self, test):
        pass

    def wasStrictlySuccessful(self):
        if self.unsupported or self.known_failure_count:
            return False
        return self.wasSuccessful()


class TextTestResult(ExtendedTestResult):
    """Displays progress and results of tests in text form."""

    def __init__(
        self,
        stream,
        descriptions,
        verbosity,
        bench_history=None,
        strict=None,
    ):
        ExtendedTestResult.__init__(
            self, stream, descriptions, verbosity, bench_history, strict
        )
        self.pb = self.ui.nested_progress_bar()
        self.pb.show_pct = False
        self.pb.show_spinner = False
        self.pb.show_eta = (False,)
        self.pb.show_count = False
        self.pb.show_bar = False
        self.pb.update_latency = 0
        self.pb.show_transport_activity = False

    def stopTestRun(self):
        # called when the tests that are going to run have run
        self.pb.clear()
        self.pb.finished()
        super().stopTestRun()

    def report_tests_starting(self):
        super().report_tests_starting()
        self.pb.update("[test 0/%d] Starting" % (self.num_tests))

    def _progress_prefix_text(self):
        # the longer this text, the less space we have to show the test
        # name...
        a = "[%d" % self.count  # total that have been run
        # tests skipped as known not to be relevant are not important enough
        # to show here
        # if self.skip_count:
        #     a += ', %d skip' % self.skip_count
        # if self.known_failure_count:
        #     a += '+%dX' % self.known_failure_count
        if self.num_tests:
            a += "/%d" % self.num_tests
        a += " in "
        runtime = time.time() - self._overall_start_time
        if runtime >= 60:
            a += "%dm%ds" % (runtime / 60, runtime % 60)
        else:
            a += "%ds" % runtime
        total_fail_count = self.error_count + self.failure_count
        if total_fail_count:
            a += ", %d failed" % total_fail_count
        # if self.unsupported:
        #     a += ', %d missing' % len(self.unsupported)
        a += "]"
        return a

    def report_test_start(self, test):
        self.pb.update(
            self._progress_prefix_text() + " " + self._shortened_test_description(test)
        )

    def _test_description(self, test):
        return self._shortened_test_description(test)

    def report_error(self, test, err):
        self.stream.write(
            "ERROR: {}\n    {}\n".format(
                self._test_description(test),
                err[1],
            )
        )

    def report_failure(self, test, err):
        self.stream.write(
            "FAIL: {}\n    {}\n".format(
                self._test_description(test),
                err[1],
            )
        )

    def report_known_failure(self, test, err):
        pass

    def report_unexpected_success(self, test, reason):
        self.stream.write(
            "FAIL: {}\n    {}: {}\n".format(
                self._test_description(test),
                "Unexpected success. Should have failed",
                reason,
            )
        )

    def report_skip(self, test, reason):
        pass

    def report_not_applicable(self, test, reason):
        pass

    def report_unsupported(self, test, feature):
        """Test cannot be run because feature is missing."""


class VerboseTestResult(ExtendedTestResult):
    """Produce long output, with one line per test run plus times."""

    def _ellipsize_to_right(self, a_string, final_width):
        """Truncate and pad a string, keeping the right hand side."""
        if len(a_string) > final_width:
            result = "..." + a_string[3 - final_width :]
        else:
            result = a_string
        return result.ljust(final_width)

    def report_tests_starting(self):
        self.stream.write("running %d tests...\n" % self.num_tests)
        super().report_tests_starting()

    def report_test_start(self, test):
        name = self._shortened_test_description(test)
        width = osutils.terminal_width()
        if width is not None:
            # width needs space for 6 char status, plus 1 for slash, plus an
            # 11-char time string, plus a trailing blank
            # when NUMBERED_DIRS: plus 5 chars on test number, plus 1 char on
            # space
            self.stream.write(self._ellipsize_to_right(name, width - 18))
        else:
            self.stream.write(name)
        self.stream.flush()

    def _error_summary(self, err):
        indent = " " * 4
        return "{}{}".format(indent, err[1])

    def report_error(self, test, err):
        self.stream.write(
            "ERROR {}\n{}\n".format(self._testTimeString(test), self._error_summary(err))
        )

    def report_failure(self, test, err):
        self.stream.write(
            " FAIL {}\n{}\n".format(self._testTimeString(test), self._error_summary(err))
        )

    def report_known_failure(self, test, err):
        self.stream.write(
            "XFAIL {}\n{}\n".format(self._testTimeString(test), self._error_summary(err))
        )

    def report_unexpected_success(self, test, reason):
        self.stream.write(
            " FAIL {}\n{}: {}\n".format(
                self._testTimeString(test),
                "Unexpected success. Should have failed",
                reason,
            )
        )

    def report_success(self, test):
        self.stream.write("   OK {}\n".format(self._testTimeString(test)))
        for bench_called, stats in getattr(test, "_benchcalls", []):
            self.stream.write("LSProf output for {}({}, {})\n".format(*bench_called))
            stats.pprint(file=self.stream)
        # flush the stream so that we get smooth output. This verbose mode is
        # used to show the output in PQM.
        self.stream.flush()

    def report_skip(self, test, reason):
        self.stream.write(" SKIP {}\n{}\n".format(self._testTimeString(test), reason))

    def report_not_applicable(self, test, reason):
        self.stream.write("  N/A {}\n    {}\n".format(self._testTimeString(test), reason))

    def report_unsupported(self, test, feature):
        """Test cannot be run because feature is missing."""
        self.stream.write(
            "NODEP {}\n    The feature '{}' is not available.\n".format(self._testTimeString(test), feature)
        )


class TextTestRunner:
    stop_on_failure = False

    def __init__(
        self,
        stream=sys.stderr,
        descriptions=0,
        verbosity=1,
        bench_history=None,
        strict=False,
        result_decorators=None,
    ):
        """Create a TextTestRunner.

        :param result_decorators: An optional list of decorators to apply
            to the result object being used by the runner. Decorators are
            applied left to right - the first element in the list is the
            innermost decorator.
        """
        # stream may know claim to know to write unicode strings, but in older
        # pythons this goes sufficiently wrong that it is a bad idea. (
        # specifically a built in file with encoding 'UTF-8' will still try
        # to encode using ascii.
        new_encoding = osutils.get_terminal_encoding()
        codec = codecs.lookup(new_encoding)
        encode = codec.encode
        # GZ 2010-09-08: Really we don't want to be writing arbitrary bytes,
        #                so should swap to the plain codecs.StreamWriter
        stream = osutils.UnicodeOrBytesToBytesWriter(encode, stream, "backslashreplace")
        stream.encoding = new_encoding
        self.stream = stream
        self.descriptions = descriptions
        self.verbosity = verbosity
        self._bench_history = bench_history
        self._strict = strict
        self._result_decorators = result_decorators or []

    def run(self, test):
        """Run the given test case or test suite."""
        if self.verbosity == 1:
            result_class = TextTestResult
        elif self.verbosity >= 2:
            result_class = VerboseTestResult
        original_result = result_class(
            self.stream,
            self.descriptions,
            self.verbosity,
            bench_history=self._bench_history,
            strict=self._strict,
        )
        # Signal to result objects that look at stop early policy to stop,
        original_result.stop_early = self.stop_on_failure
        result = original_result
        for decorator in self._result_decorators:
            result = decorator(result)
            result.stop_early = self.stop_on_failure
        result.startTestRun()
        try:
            test.run(result)
        finally:
            result.stopTestRun()
        # higher level code uses our extended protocol to determine
        # what exit code to give.
        return original_result


def iter_suite_tests(suite):
    """Return all tests in a suite, recursing through nested suites."""
    if isinstance(suite, unittest.TestCase):
        yield suite
    elif isinstance(suite, unittest.TestSuite):
        for item in suite:
            yield from iter_suite_tests(item)
    else:
        raise Exception("unknown type {!r} for object {!r}".format(type(suite), suite))


class TestNotApplicable(TestSkipped):
    """A test is not applicable to the situation where it was run.

    This is only normally raised by parameterized tests, if they find that
    the instance they're constructed upon does not support one aspect
    of its interface.
    """


# traceback._some_str fails to format exceptions that have the default
# __str__ which does an implicit ascii conversion. However, repr() on those
# objects works, for all that its not quite what the doctor may have ordered.
def _clever_some_str(value):
    try:
        return str(value)
    except BaseException:
        try:
            return repr(value).replace("\\n", "\n")
        except BaseException:
            return "<unprintable {} object>".format(type(value).__name__)


traceback._some_str = _clever_some_str  # type: ignore


# deprecated - use self.knownFailure(), or self.expectFailure.
KnownFailure = testtools.testcase._ExpectedFailure


class UnavailableFeature(Exception):
    """A feature required for this test was not available.

    This can be considered a specialised form of SkippedTest.

    The feature should be used to construct the exception.
    """


class StringIOWrapper(ui_testing.BytesIOWithEncoding):
    @symbol_versioning.deprecated_method(symbol_versioning.deprecated_in((3, 0)))
    def __init__(self, s=None):
        super().__init__(s)


TestUIFactory = ui_testing.TestUIFactory


def isolated_doctest_setUp(test):
    override_os_environ(test)
    osutils.set_or_unset_env("BRZ_HOME", "/nonexistent")
    test._orig_ui_factory = ui.ui_factory
    ui.ui_factory = ui.SilentUIFactory()


def isolated_doctest_tearDown(test):
    restore_os_environ(test)
    ui.ui_factory = test._orig_ui_factory


def IsolatedDocTestSuite(*args, **kwargs):
    """Overrides doctest.DocTestSuite to handle isolation.

    The method is really a factory and users are expected to use it as such.
    """
    kwargs["setUp"] = isolated_doctest_setUp
    kwargs["tearDown"] = isolated_doctest_tearDown
    return doctest.DocTestSuite(*args, **kwargs)


class TestCase(testtools.TestCase):
    """Base class for brz unit tests.

    Tests that need access to disk resources should subclass
    TestCaseInTempDir not TestCase.

    Error and debug log messages are redirected from their usual
    location into a temporary file, the contents of which can be
    retrieved by _get_log().  We use a real OS file, not an in-memory object,
    so that it can also capture file IO.  When the test completes this file
    is read into memory and removed from disk.

    There are also convenience functions to invoke bzr's command-line
    routine, and to build and check brz trees.

    In addition to the usual method of overriding tearDown(), this class also
    allows subclasses to register cleanup functions via addCleanup, which are
    run in order as the object is torn down.  It's less likely this will be
    accidentally overlooked.
    """

    _log_file = None
    # record lsprof data when performing benchmark calls.
    _gather_lsprof_in_benchmarks = False

    def __init__(self, methodName="testMethod"):
        super().__init__(methodName)
        self._directory_isolation = True
        self.exception_handlers.insert(
            0, (UnavailableFeature, self._do_unsupported_or_skip)
        )
        self.exception_handlers.insert(0, (TestNotApplicable, self._do_not_applicable))

    def setUp(self):
        super().setUp()

        # At this point we're still accessing the config files in $BRZ_HOME (as
        # set by the user running selftest).
        timeout = config.GlobalStack().get("selftest.timeout")
        if timeout:
            timeout_fixture = fixtures.TimeoutFixture(timeout, gentle=True)
            timeout_fixture.setUp()
            self.addCleanup(timeout_fixture.cleanUp)

        for feature in getattr(self, "_test_needs_features", []):
            self.requireFeature(feature)
        self._cleanEnvironment()

        self.overrideAttr(
            breezy.get_global_state(), "cmdline_overrides", config.CommandLineStore()
        )

        self._silenceUI()
        self._startLogFile()
        self._benchcalls = []
        self._benchtime = None
        self._clear_hooks()
        self._track_transports()
        self._track_locks()
        self._clear_debug_flags()
        # Isolate global verbosity level, to make sure it's reproducible
        # between tests.  We should get rid of this altogether: bug 656694. --
        # mbp 20101008
        self.overrideAttr(breezy.trace, "_verbosity_level", 0)
        self._log_files = set()
        # Each key in the ``_counters`` dict holds a value for a different
        # counter. When the test ends, addDetail() should be used to output the
        # counter values. This happens in install_counter_hook().
        self._counters = {}
        if "config_stats" in selftest_debug_flags:
            self._install_config_stats_hooks()
        # Do not use i18n for tests (unless the test reverses this)
        i18n.disable_i18n()

    def debug(self):
        # debug a frame up.
        import pdb

        # The sys preserved stdin/stdout should allow blackbox tests debugging
        pdb.Pdb(stdin=sys.__stdin__, stdout=sys.__stdout__).set_trace(
            sys._getframe().f_back
        )

    def discardDetail(self, name):
        """Extend the addDetail, getDetails api so we can remove a detail.

        eg. brz always adds the 'log' detail at startup, but we don't want to
        include it for skipped, xfail, etc tests.

        It is safe to call this for a detail that doesn't exist, in case this
        gets called multiple times.
        """
        # We cheat. details is stored in __details which means we shouldn't
        # touch it. but getDetails() returns the dict directly, so we can
        # mutate it.
        details = self.getDetails()
        if name in details:
            del details[name]

    def install_counter_hook(self, hooks, name, counter_name=None):
        """Install a counting hook.

        Any hook can be counted as long as it doesn't need to return a value.

        :param hooks: Where the hook should be installed.

        :param name: The hook name that will be counted.

        :param counter_name: The counter identifier in ``_counters``, defaults
            to ``name``.
        """
        _counters = self._counters  # Avoid closing over self
        if counter_name is None:
            counter_name = name
        if counter_name in _counters:
            raise AssertionError(
                "{} is already used as a counter name".format(counter_name)
            )
        _counters[counter_name] = 0
        self.addDetail(
            counter_name,
            content.Content(
                content.UTF8_TEXT, lambda: [b"%d" % (_counters[counter_name],)]
            ),
        )

        def increment_counter(*args, **kwargs):
            _counters[counter_name] += 1

        label = "count {} calls".format(counter_name)
        hooks.install_named_hook(name, increment_counter, label)
        self.addCleanup(hooks.uninstall_named_hook, name, label)

    def _install_config_stats_hooks(self):
        """Install config hooks to count hook calls."""
        for hook_name in ("get", "set", "remove", "load", "save"):
            self.install_counter_hook(
                config.ConfigHooks, hook_name, "config.{}".format(hook_name)
            )

        # The OldConfigHooks are private and need special handling to protect
        # against recursive tests (tests that run other tests), so we just do
        # manually what registering them into _builtin_known_hooks will provide
        # us.
        self.overrideAttr(config, "OldConfigHooks", config._OldConfigHooks())
        for hook_name in ("get", "set", "remove", "load", "save"):
            self.install_counter_hook(
                config.OldConfigHooks, hook_name, "old_config.{}".format(hook_name)
            )

    def _clear_debug_flags(self):
        """Prevent externally set debug flags affecting tests.

        Tests that want to use debug flags can just set them in the
        debug_flags set during setup/teardown.
        """
        # Start with a copy of the current debug flags we can safely modify.
        self.overrideAttr(debug, "debug_flags", set(debug.debug_flags))
        if "allow_debug" not in selftest_debug_flags:
            debug.debug_flags.clear()
        if "disable_lock_checks" not in selftest_debug_flags:
            debug.debug_flags.add("strict_locks")

    def _clear_hooks(self):
        # prevent hooks affecting tests
        known_hooks = hooks.known_hooks
        self._preserved_hooks = {}
        for key, (parent, name) in known_hooks.iter_parent_objects():
            current_hooks = getattr(parent, name)
            self._preserved_hooks[parent] = (name, current_hooks)
        self._preserved_lazy_hooks = hooks._lazy_hooks
        hooks._lazy_hooks = {}
        self.addCleanup(self._restoreHooks)
        for key, (parent, name) in known_hooks.iter_parent_objects():
            factory = known_hooks.get(key)
            setattr(parent, name, factory())
        # this hook should always be installed
        request._install_hook()

    def disable_directory_isolation(self):
        """Turn off directory isolation checks."""
        self._directory_isolation = False

    def enable_directory_isolation(self):
        """Enable directory isolation checks."""
        self._directory_isolation = True

    def _silenceUI(self):
        """Turn off UI for duration of test."""
        # by default the UI is off; tests can turn it on if they want it.
        self.overrideAttr(ui, "ui_factory", ui.SilentUIFactory())

    def _check_locks(self):
        """Check that all lock take/release actions have been paired."""
        # We always check for mismatched locks. If a mismatch is found, we
        # fail unless -Edisable_lock_checks is supplied to selftest, in which
        # case we just print a warning.
        # unhook:
        acquired_locks = [
            lock for action, lock in self._lock_actions if action == "acquired"
        ]
        released_locks = [
            lock for action, lock in self._lock_actions if action == "released"
        ]
        broken_locks = [
            lock for action, lock in self._lock_actions if action == "broken"
        ]
        # trivially, given the tests for lock acquistion and release, if we
        # have as many in each list, it should be ok. Some lock tests also
        # break some locks on purpose and should be taken into account by
        # considering that breaking a lock is just a dirty way of releasing it.
        if len(acquired_locks) != (len(released_locks) + len(broken_locks)):
            message = (
                "Different number of acquired and "
                "released or broken locks.\n"
                "acquired={}\n"
                "released={}\n"
                "broken={}\n".format(acquired_locks, released_locks, broken_locks)
            )
            if not self._lock_check_thorough:
                # Rather than fail, just warn
                print("Broken test {}: {}".format(self, message))
                return
            self.fail(message)

    def _track_locks(self):
        """Track lock activity during tests."""
        self._lock_actions = []
        if "disable_lock_checks" in selftest_debug_flags:
            self._lock_check_thorough = False
        else:
            self._lock_check_thorough = True

        self.addCleanup(self._check_locks)
        _mod_lock.Lock.hooks.install_named_hook(
            "lock_acquired", self._lock_acquired, None
        )
        _mod_lock.Lock.hooks.install_named_hook(
            "lock_released", self._lock_released, None
        )
        _mod_lock.Lock.hooks.install_named_hook("lock_broken", self._lock_broken, None)

    def _lock_acquired(self, result):
        self._lock_actions.append(("acquired", result))

    def _lock_released(self, result):
        self._lock_actions.append(("released", result))

    def _lock_broken(self, result):
        self._lock_actions.append(("broken", result))

    def permit_dir(self, name):
        """Permit a directory to be used by this test. See permit_url."""
        name_transport = _mod_transport.get_transport_from_path(name)
        self.permit_url(name)
        self.permit_url(name_transport.base)

    def permit_url(self, url):
        """Declare that url is an ok url to use in this test.

        Do this for memory transports, temporary test directory etc.

        Do not do this for the current working directory, /tmp, or any other
        preexisting non isolated url.
        """
        if not url.endswith("/"):
            url += "/"
        self._bzr_selftest_roots.append(url)

    def permit_source_tree_branch_repo(self):
        """Permit the source tree brz is running from to be opened.

        Some code such as breezy.version attempts to read from the brz branch
        that brz is executing from (if any). This method permits that directory
        to be used in the test suite.
        """
        path = self.get_source_path()
        self.record_directory_isolation()
        try:
            try:
                workingtree.WorkingTree.open(path)
            except (errors.NotBranchError, errors.NoWorkingTree):
                raise TestSkipped("Needs a working tree of brz sources")
        finally:
            self.enable_directory_isolation()

    def _preopen_isolate_transport(self, transport):
        """Check that all transport openings are done in the test work area."""
        while isinstance(transport, pathfilter.PathFilteringTransport):
            # Unwrap pathfiltered transports
            transport = transport.server.backing_transport.clone(transport._filter("."))
        url = transport.base
        # ReadonlySmartTCPServer_for_testing decorates the backing transport
        # urls it is given by prepending readonly+. This is appropriate as the
        # client shouldn't know that the server is readonly (or not readonly).
        # We could register all servers twice, with readonly+ prepending, but
        # that makes for a long list; this is about the same but easier to
        # read.
        if url.startswith("readonly+"):
            url = url[len("readonly+") :]
        self._preopen_isolate_url(url)

    def _preopen_isolate_url(self, url):
        if not self._directory_isolation:
            return
        if self._directory_isolation == "record":
            self._bzr_selftest_roots.append(url)
            return
        # This prevents all transports, including e.g. sftp ones backed on disk
        # from working unless they are explicitly granted permission. We then
        # depend on the code that sets up test transports to check that they
        # are appropriately isolated and enable their use by calling
        # self.permit_transport()
        if not osutils.is_inside_any(self._bzr_selftest_roots, url):
            raise errors.BzrError(
                "Attempt to escape test isolation: {!r} {!r}".format(url, self._bzr_selftest_roots)
            )

    def record_directory_isolation(self):
        """Gather accessed directories to permit later access.

        This is used for tests that access the branch brz is running from.
        """
        self._directory_isolation = "record"

    def start_server(self, transport_server, backing_server=None):
        """Start transport_server for this test.

        This starts the server, registers a cleanup for it and permits the
        server's urls to be used.
        """
        if backing_server is None:
            transport_server.start_server()
        else:
            transport_server.start_server(backing_server)
        self.addCleanup(transport_server.stop_server)
        # Obtain a real transport because if the server supplies a password, it
        # will be hidden from the base on the client side.
        t = _mod_transport.get_transport_from_url(transport_server.get_url())
        # Some transport servers effectively chroot the backing transport;
        # others like SFTPServer don't - users of the transport can walk up the
        # transport to read the entire backing transport. This wouldn't matter
        # except that the workdir tests are given - and that they expect the
        # server's url to point at - is one directory under the safety net. So
        # Branch operations into the transport will attempt to walk up one
        # directory. Chrooting all servers would avoid this but also mean that
        # we wouldn't be testing directly against non-root urls. Alternatively
        # getting the test framework to start the server with a backing server
        # at the actual safety net directory would work too, but this then
        # means that the self.get_url/self.get_transport methods would need
        # to transform all their results. On balance its cleaner to handle it
        # here, and permit a higher url when we have one of these transports.
        if t.base.endswith("/work/"):
            # we have safety net/test root/work
            t = t.clone("../..")
        elif isinstance(transport_server, test_server.SmartTCPServer_for_testing):
            # The smart server adds a path similar to work, which is traversed
            # up from by the client. But the server is chrooted - the actual
            # backing transport is not escaped from, and VFS requests to the
            # root will error (because they try to escape the chroot).
            t2 = t.clone("..")
            while t2.base != t.base:
                t = t2
                t2 = t.clone("..")
        self.permit_url(t.base)

    def _track_transports(self):
        """Install checks for transport usage."""
        # TestCase has no safe place it can write to.
        self._bzr_selftest_roots = []
        # Currently the easiest way to be sure that nothing is going on is to
        # hook into brz dir opening. This leaves a small window of error for
        # transport tests, but they are well known, and we can improve on this
        # step.
        controldir.ControlDir.hooks.install_named_hook(
            "pre_open",
            self._preopen_isolate_transport,
            "Check brz directories are safe.",
        )

    def _ndiff_strings(self, a, b):
        """Return ndiff between two strings containing lines.

        A trailing newline is added if missing to make the strings
        print properly.
        """
        if b and not b.endswith("\n"):
            b += "\n"
        if a and not a.endswith("\n"):
            a += "\n"
        difflines = difflib.ndiff(
            a.splitlines(True),
            b.splitlines(True),
            linejunk=lambda x: False,
            charjunk=lambda x: False,
        )
        return "".join(difflines)

    def assertEqual(self, a, b, message=""):
        try:
            if a == b:
                return
        except UnicodeError as e:
            # If we can't compare without getting a UnicodeError, then
            # obviously they are different
            trace.mutter("UnicodeError: %s", e)
        if message:
            message += "\n"
        raise AssertionError(
            "{}not equal:\na = {}\nb = {}\n".format(message, pprint.pformat(a), pprint.pformat(b))
        )

    # FIXME: This is deprecated in unittest2 but plugins may still use it so we
    # need a deprecation period for them -- vila 2016-02-01
    assertEquals = assertEqual

    def assertEqualDiff(self, a, b, message=None):
        """Assert two texts are equal, if not raise an exception.

        This is intended for use with multi-line strings where it can
        be hard to find the differences by eye.
        """
        # TODO: perhaps override assertEqual to call this for strings?
        if a == b:
            return
        if message is None:
            message = "texts not equal:\n"
        if a + ("\n" if isinstance(a, str) else b"\n") == b:
            message = "first string is missing a final newline.\n"
        if a == b + ("\n" if isinstance(b, str) else b"\n"):
            message = "second string is missing a final newline.\n"
        raise AssertionError(
            message
            + self._ndiff_strings(
                a if isinstance(a, str) else a.decode(),
                b if isinstance(b, str) else b.decode(),
            )
        )

    def assertEqualMode(self, mode, mode_test):
        self.assertEqual(
            mode, mode_test, "mode mismatch {:o} != {:o}".format(mode, mode_test)
        )

    def assertEqualStat(self, expected, actual):
        """Assert that expected and actual are the same stat result.

        :param expected: A stat result.
        :param actual: A stat result.
        :raises AssertionError: If the expected and actual stat values differ
            other than by atime.
        """
        self.assertEqual(expected.st_size, actual.st_size, "st_size did not match")
        self.assertEqual(expected.st_mtime, actual.st_mtime, "st_mtime did not match")
        self.assertEqual(expected.st_ctime, actual.st_ctime, "st_ctime did not match")
        if sys.platform == "win32":
            # On Win32 both 'dev' and 'ino' cannot be trusted. In python2.4 it
            # is 'dev' that varies, in python 2.5 (6?) it is st_ino that is
            # odd. We just force it to always be 0 to avoid any problems.
            self.assertEqual(0, expected.st_dev)
            self.assertEqual(0, actual.st_dev)
            self.assertEqual(0, expected.st_ino)
            self.assertEqual(0, actual.st_ino)
        else:
            self.assertEqual(expected.st_dev, actual.st_dev, "st_dev did not match")
            self.assertEqual(expected.st_ino, actual.st_ino, "st_ino did not match")
        self.assertEqual(expected.st_mode, actual.st_mode, "st_mode did not match")

    def assertLength(self, length, obj_with_len):
        """Assert that obj_with_len is of length length."""
        if len(obj_with_len) != length:
            self.fail(
                "Incorrect length: wanted %d, got %d for %r"
                % (length, len(obj_with_len), obj_with_len)
            )

    def assertLogsError(self, exception_class, func, *args, **kwargs):
        """Assert that `func(*args, **kwargs)` quietly logs a specific error."""
        captured = []
        orig_log_exception_quietly = trace.log_exception_quietly
        try:

            def capture():
                orig_log_exception_quietly()
                captured.append(sys.exc_info()[1])

            trace.log_exception_quietly = capture
            func(*args, **kwargs)
        finally:
            trace.log_exception_quietly = orig_log_exception_quietly
        self.assertLength(1, captured)
        err = captured[0]
        self.assertIsInstance(err, exception_class)
        return err

    def assertPositive(self, val):
        """Assert that val is greater than 0."""
        self.assertTrue(val > 0, "expected a positive value, but got {}".format(val))

    def assertNegative(self, val):
        """Assert that val is less than 0."""
        self.assertTrue(val < 0, "expected a negative value, but got {}".format(val))

    def assertStartsWith(self, s, prefix):
        if not s.startswith(prefix):
            raise AssertionError(
                "string {!r} does not start with {!r}".format(s, prefix)
            )

    def assertEndsWith(self, s, suffix):
        """Asserts that s ends with suffix."""
        if not s.endswith(suffix):
            raise AssertionError("string {!r} does not end with {!r}".format(s, suffix))

    def assertContainsRe(self, haystack, needle_re, flags=0):
        """Assert that a contains something matching a regular expression."""
        if not re.search(needle_re, haystack, flags):
            if ("\n" if isinstance(haystack, str) else b"\n") in haystack or len(
                haystack
            ) > 60:
                # a long string, format it in a more readable way
                raise AssertionError(
                    'pattern "{}" not found in\n"""\\\n{}"""\n'.format(needle_re, haystack)
                )
            else:
                raise AssertionError(
                    'pattern "{}" not found in "{}"'.format(needle_re, haystack)
                )

    def assertNotContainsRe(self, haystack, needle_re, flags=0):
        """Assert that a does not match a regular expression."""
        if re.search(needle_re, haystack, flags):
            raise AssertionError('pattern "{}" found in "{}"'.format(needle_re, haystack))

    def assertContainsString(self, haystack, needle):
        if haystack.find(needle) == -1:
            self.fail("string {!r} not found in '''{}'''".format(needle, haystack))

    def assertNotContainsString(self, haystack, needle):
        if haystack.find(needle) != -1:
            self.fail("string {!r} found in '''{}'''".format(needle, haystack))

    def assertSubset(self, sublist, superlist):
        """Assert that every entry in sublist is present in superlist."""
        missing = set(sublist) - set(superlist)
        if len(missing) > 0:
            raise AssertionError(
                "value(s) {!r} not present in container {!r}".format(missing, superlist)
            )

    def assertListRaises(self, exc_class, func, *args, **kwargs):
        """Fail unless exc_class is raised when the iterator from func is used.

        Many functions can return generators this makes sure
        to wrap them in a list() call to make sure the whole generator
        is run, and that the proper exception is raised.
        """
        try:
            list(func(*args, **kwargs))
        except exc_class as e:
            return e
        else:
            if getattr(exc_class, "__name__", None) is not None:
                excName = exc_class.__name__
            else:
                excName = str(exc_class)
            raise self.failureException("{} not raised".format(excName))

    def assertRaises(self, exc_class, callableObj, *args, **kwargs):
        """Assert that a callable raises a particular exception.

        :param exc_class: As for the except statement, this may be either an
            exception class, or a tuple of classes.
        :param callableObj: A callable, will be passed ``*args`` and
            ``**kwargs``.

        Returns the exception so that you can examine it.
        """
        try:
            callableObj(*args, **kwargs)
        except exc_class as e:
            return e
        else:
            if getattr(exc_class, "__name__", None) is not None:
                excName = exc_class.__name__
            else:
                # probably a tuple
                excName = str(exc_class)
            raise self.failureException("{} not raised".format(excName))

    def assertIs(self, left, right, message=None):
        if left is not right:
            if message is not None:
                raise AssertionError(message)
            else:
                raise AssertionError("{!r} is not {!r}.".format(left, right))

    def assertIsNot(self, left, right, message=None):
        if left is right:
            if message is not None:
                raise AssertionError(message)
            else:
                raise AssertionError("{!r} is {!r}.".format(left, right))

    def assertTransportMode(self, transport, path, mode):
        """Fail if a path does not have mode "mode".

        If modes are not supported on this transport, the assertion is ignored.
        """
        if not transport._can_roundtrip_unix_modebits():
            return
        path_stat = transport.stat(path)
        actual_mode = stat.S_IMODE(path_stat.st_mode)
        self.assertEqual(
            mode,
            actual_mode,
            "mode of {!r} incorrect ({} != {})".format(path, oct(mode), oct(actual_mode)),
        )

    def assertIsSameRealPath(self, path1, path2):
        """Fail if path1 and path2 points to different files."""
        self.assertEqual(
            osutils.realpath(path1),
            osutils.realpath(path2),
            "apparent paths:\na = {}\nb = {}\n,".format(path1, path2),
        )

    def assertIsInstance(self, obj, kls, msg=None):
        """Fail if obj is not an instance of kls.

        :param msg: Supplementary message to show if the assertion fails.
        """
        if not isinstance(obj, kls):
            m = "{!r} is an instance of {} rather than {}".format(
                obj, obj.__class__, kls
            )
            if msg:
                m += ": " + msg
            self.fail(m)

    def assertFileEqual(self, content, path):
        """Fail if path does not contain 'content'."""
        self.assertPathExists(path)

        mode = "r" + ("b" if isinstance(content, bytes) else "")
        with open(path, mode) as f:
            s = f.read()
        self.assertEqualDiff(content, s)

    def assertDocstring(self, expected_docstring, obj):
        """Fail if obj does not have expected_docstring."""
        if __doc__ is None:
            # With -OO the docstring should be None instead
            self.assertIs(obj.__doc__, None)
        else:
            self.assertEqual(expected_docstring, obj.__doc__)

    def assertPathExists(self, path):
        """Fail unless path or paths, which may be abs or relative, exist."""
        # TODO(jelmer): Clean this up for pad.lv/1696545
        if not isinstance(path, (bytes, str)):
            for p in path:
                self.assertPathExists(p)
        else:
            self.assertTrue(osutils.lexists(path), path + " does not exist")

    def assertPathDoesNotExist(self, path):
        """Fail if path or paths, which may be abs or relative, exist."""
        if not isinstance(path, (str, str)):
            for p in path:
                self.assertPathDoesNotExist(p)
        else:
            self.assertFalse(osutils.lexists(path), path + " exists")

    def _capture_deprecation_warnings(self, a_callable, *args, **kwargs):
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

        To test that a deprecated method raises an error, do something like
        this (remember that both assertRaises and applyDeprecated delays *args
        and **kwargs passing)::

            self.assertRaises(errors.ReservedId,
                self.applyDeprecated,
                deprecated_in((1, 5, 0)),
                br.append_revision,
                'current:')

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
        call_warnings, result = self._capture_deprecation_warnings(
            a_callable, *args, **kwargs
        )
        expected_first_warning = symbol_versioning.deprecation_string(
            a_callable, deprecation_format
        )
        if len(call_warnings) == 0:
            self.fail("No deprecation warning generated by call to {}".format(a_callable))
        self.assertEqual(expected_first_warning, call_warnings[0])
        return result

    def callCatchWarnings(self, fn, *args, **kw):
        """Call a callable that raises python warnings.

        The caller's responsible for examining the returned warnings.

        If the callable raises an exception, the exception is not
        caught and propagates up to the caller.  In that case, the list
        of warnings is not available.

        :returns: ([warning_object, ...], fn_result)
        """
        # XXX: This is not perfect, because it completely overrides the
        # warnings filters, and some code may depend on suppressing particular
        # warnings.  It's the easiest way to insulate ourselves from -Werror,
        # though.  -- Andrew, 20071062
        wlist = []

        def _catcher(message, category, filename, lineno, file=None, line=None):
            # despite the name, 'message' is normally(?) a Warning subclass
            # instance
            wlist.append(message)

        saved_showwarning = warnings.showwarning
        saved_filters = warnings.filters
        try:
            warnings.showwarning = _catcher
            warnings.filters = []
            result = fn(*args, **kw)
        finally:
            warnings.showwarning = saved_showwarning
            warnings.filters = saved_filters
        return wlist, result

    def callDeprecated(self, expected, callable, *args, **kwargs):
        """Assert that a callable is deprecated in a particular way.

        This is a very precise test for unusual requirements. The
        applyDeprecated helper function is probably more suited for most tests
        as it allows you to simply specify the deprecation format being used
        and will ensure that that is issued for the function being called.

        Note that this only captures warnings raised by symbol_versioning.warn,
        not other callers that go direct to the warning module.  To catch
        general warnings, use callCatchWarnings.

        :param expected: a list of the deprecation warnings expected, in order
        :param callable: The callable to call
        :param args: The positional arguments for the callable
        :param kwargs: The keyword arguments for the callable
        """
        call_warnings, result = self._capture_deprecation_warnings(
            callable, *args, **kwargs
        )
        self.assertEqual(expected, call_warnings)
        return result

    def _startLogFile(self):
        """Setup a in-memory target for bzr and testcase log messages."""
        pseudo_log_file = BytesIO()

        def _get_log_contents_for_weird_testtools_api():
            return [
                pseudo_log_file.getvalue().decode("utf-8", "replace").encode("utf-8")
            ]

        self.addDetail(
            "log",
            content.Content(
                content.ContentType("text", "plain", {"charset": "utf8"}),
                _get_log_contents_for_weird_testtools_api,
            ),
        )
        self._log_file = pseudo_log_file
        self._log_memento = trace.push_log_file(self._log_file)
        self.addCleanup(self._finishLogFile)

    @contextlib.contextmanager
    def text_log_file(self, **kwargs):
        stream = TextIOWrapper(self._log_file, encoding="utf-8", **kwargs)
        yield stream
        stream.detach()

    def _finishLogFile(self):
        """Flush and dereference the in-memory log for this testcase."""
        if trace._trace_file:
            # flush the log file, to get all content
            trace._trace_file.flush()
        trace.pop_log_file(self._log_memento)
        # The logging module now tracks references for cleanup so discard ours
        del self._log_memento

    def thisFailsStrictLockCheck(self):
        """It is known that this test would fail with -Dstrict_locks.

        By default, all tests are run with strict lock checking unless
        -Edisable_lock_checks is supplied. However there are some tests which
        we know fail strict locks at this point that have not been fixed.
        They should call this function to disable the strict checking.

        This should be used sparingly, it is much better to fix the locking
        issues rather than papering over the problem by calling this function.
        """
        debug.debug_flags.discard("strict_locks")

    def overrideAttr(self, obj, attr_name, new=_unitialized_attr):
        """Overrides an object attribute restoring it after the test.

        :note: This should be used with discretion; you should think about
        whether it's better to make the code testable without monkey-patching.

        :param obj: The object that will be mutated.

        :param attr_name: The attribute name we want to preserve/override in
            the object.

        :param new: The optional value we want to set the attribute to.

        :returns: The actual attr value.
        """
        # The actual value is captured by the call below
        value = getattr(obj, attr_name, _unitialized_attr)
        if value is _unitialized_attr:
            # When the test completes, the attribute should not exist, but if
            # we aren't setting a value, we don't need to do anything.
            if new is not _unitialized_attr:
                self.addCleanup(delattr, obj, attr_name)
        else:
            self.addCleanup(setattr, obj, attr_name, value)
        if new is not _unitialized_attr:
            setattr(obj, attr_name, new)
        return value

    def overrideEnv(self, name, new):
        """Set an environment variable, and reset it after the test.

        :param name: The environment variable name.

        :param new: The value to set the variable to. If None, the
            variable is deleted from the environment.

        :returns: The actual variable value.
        """
        value = osutils.set_or_unset_env(name, new)
        self.addCleanup(osutils.set_or_unset_env, name, value)
        return value

    def recordCalls(self, obj, attr_name):
        """Monkeypatch in a wrapper that will record calls.

        The monkeypatch is automatically removed when the test concludes.

        :param obj: The namespace holding the reference to be replaced;
            typically a module, class, or object.
        :param attr_name: A string for the name of the attribute to patch.
        :returns: A list that will be extended with one item every time the
            function is called, with a tuple of (args, kwargs).
        """
        calls = []

        def decorator(*args, **kwargs):
            calls.append((args, kwargs))
            return orig(*args, **kwargs)

        orig = self.overrideAttr(obj, attr_name, decorator)
        return calls

    def _cleanEnvironment(self):
        for name, value in isolated_environ.items():
            self.overrideEnv(name, value)

    def _restoreHooks(self):
        for klass, (name, hooks) in self._preserved_hooks.items():
            setattr(klass, name, hooks)
        self._preserved_hooks.clear()
        breezy.hooks._lazy_hooks = self._preserved_lazy_hooks
        self._preserved_lazy_hooks.clear()

    def knownFailure(self, reason):
        """Declare that this test fails for a known reason.

        Tests that are known to fail should generally be using expectedFailure
        with an appropriate reverse assertion if a change could cause the test
        to start passing. Conversely if the test has no immediate prospect of
        succeeding then using skip is more suitable.

        When this method is called while an exception is being handled, that
        traceback will be used, otherwise a new exception will be thrown to
        provide one but won't be reported.
        """
        self._add_reason(reason)
        try:
            exc_info = sys.exc_info()
            if exc_info != (None, None, None):
                self._report_traceback(exc_info)
            else:
                try:
                    raise self.failureException(reason)
                except self.failureException:
                    exc_info = sys.exc_info()
            # GZ 02-08-2011: Maybe cleanup this err.exc_info attribute too?
            raise testtools.testcase._ExpectedFailure(exc_info)
        finally:
            del exc_info

    def _suppress_log(self):
        """Remove the log info from details."""
        self.discardDetail("log")

    def _do_skip(self, result, reason):
        self._suppress_log()
        addSkip = getattr(result, "addSkip", None)
        if not callable(addSkip):
            result.addSuccess(result)
        else:
            addSkip(self, str(reason))

    @staticmethod
    def _do_known_failure(self, result, e):
        self._suppress_log()
        err = sys.exc_info()
        addExpectedFailure = getattr(result, "addExpectedFailure", None)
        if addExpectedFailure is not None:
            addExpectedFailure(self, err)
        else:
            result.addSuccess(self)

    @staticmethod
    def _do_not_applicable(self, result, e):
        if not e.args:
            reason = "No reason given"
        else:
            reason = e.args[0]
        self._suppress_log()
        addNotApplicable = getattr(result, "addNotApplicable", None)
        if addNotApplicable is not None:
            result.addNotApplicable(self, reason)
        else:
            self._do_skip(result, reason)

    @staticmethod
    def _report_skip(self, result, err):
        """Override the default _report_skip.

        We want to strip the 'log' detail. If we waint until _do_skip, it has
        already been formatted into the 'reason' string, and we can't pull it
        out again.
        """
        self._suppress_log()
        super()._report_skip(self, result, err)

    @staticmethod
    def _report_expected_failure(self, result, err):
        """Strip the log.

        See _report_skip for motivation.
        """
        self._suppress_log()
        super()._report_expected_failure(self, result, err)

    @staticmethod
    def _do_unsupported_or_skip(self, result, e):
        reason = e.args[0]
        self._suppress_log()
        addNotSupported = getattr(result, "addNotSupported", None)
        if addNotSupported is not None:
            result.addNotSupported(self, reason)
        else:
            self._do_skip(result, reason)

    def time(self, callable, *args, **kwargs):
        """Run callable and accrue the time it takes to the benchmark time.

        If lsprofiling is enabled (i.e. by --lsprof-time to brz selftest) then
        this will cause lsprofile statistics to be gathered and stored in
        self._benchcalls.
        """
        if self._benchtime is None:
            self.addDetail(
                "benchtime",
                content.Content(
                    content.UTF8_TEXT, lambda: [str(self._benchtime).encode("utf-8")]
                ),
            )
            self._benchtime = 0
        start = time.time()
        try:
            if not self._gather_lsprof_in_benchmarks:
                return callable(*args, **kwargs)
            else:
                # record this benchmark
                ret, stats = breezy.lsprof.profile(callable, *args, **kwargs)
                stats.sort()
                self._benchcalls.append(((callable, args, kwargs), stats))
                return ret
        finally:
            self._benchtime += time.time() - start

    def log(self, *args):
        trace.mutter(*args)

    def get_log(self):
        """Get a unicode string containing the log from breezy.trace.

        Undecodable characters are replaced.
        """
        return "".join(self.getDetails()["log"].iter_text())

    def requireFeature(self, feature):
        """This test requires a specific feature is available.

        :raises UnavailableFeature: When feature is not available.
        """
        if not feature.available():
            raise UnavailableFeature(feature)

    def _run_bzr_core(self, args, encoding, stdin, stdout, stderr, working_dir):
        # Clear chk_map page cache, because the contents are likely to mask
        # locking errors.
        chk_map.clear_cache()

        self.log("run brz: %r", args)

        self._last_cmd_stdout = stdout
        self._last_cmd_stderr = stderr

        old_ui_factory = ui.ui_factory
        ui.ui_factory = ui_testing.TestUIFactory(
            stdin=stdin, stdout=self._last_cmd_stdout, stderr=self._last_cmd_stderr
        )

        cwd = None
        if working_dir is not None:
            cwd = osutils.getcwd()
            os.chdir(working_dir)

        try:
            with ui.ui_factory:
                result = self.apply_redirected(
                    ui.ui_factory.stdin,
                    stdout,
                    stderr,
                    _mod_commands.run_bzr_catch_user_errors,
                    args,
                )
        finally:
            ui.ui_factory = old_ui_factory
            if cwd is not None:
                os.chdir(cwd)

        return result

    def run_bzr_raw(
        self,
        args,
        retcode=0,
        stdin=None,
        encoding=None,
        working_dir=None,
        error_regexes=None,
    ):
        """Invoke brz, as if it were run from the command line.

        The argument list should not include the brz program name - the
        first argument is normally the brz command.  Arguments may be
        passed in three ways:

        1- A list of strings, eg ["commit", "a"].  This is recommended
        when the command contains whitespace or metacharacters, or
        is built up at run time.

        2- A single string, eg "add a".  This is the most convenient
        for hardcoded commands.

        This runs brz through the interface that catches and reports
        errors, and with logging set to something approximating the
        default, so that error reporting can be checked.

        This should be the main method for tests that want to exercise the
        overall behavior of the brz application (rather than a unit test
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
        if error_regexes is None:
            error_regexes = []
        if isinstance(args, str):
            args = shlex.split(args)

        if encoding is None:
            encoding = osutils.get_user_encoding()

        stdout = BytesIO()
        stderr = BytesIO()
        wrapped_stdout = TextIOWrapper(stdout, encoding)
        wrapped_stderr = TextIOWrapper(stderr, encoding)
        handler = logging.StreamHandler(wrapped_stderr)
        handler.setLevel(logging.INFO)

        logger = logging.getLogger("")
        logger.addHandler(handler)
        try:
            result = self._run_bzr_core(
                args,
                encoding=encoding,
                stdin=stdin,
                stdout=wrapped_stdout,
                stderr=wrapped_stderr,
                working_dir=working_dir,
            )
        finally:
            logger.removeHandler(handler)

        wrapped_stdout.flush()
        wrapped_stderr.flush()

        out = stdout.getvalue()
        err = stderr.getvalue()
        if out:
            self.log("output:\n%r", out)
        if err:
            self.log("errors:\n%r", err)
        if retcode is not None:
            self.assertEqual(retcode, result, message="Unexpected return code")
        self.assertIsInstance(error_regexes, (list, tuple))
        for regex in error_regexes:
            self.assertContainsRe(err, regex)
        return out, err

    def run_bzr(
        self,
        args,
        retcode=0,
        stdin=None,
        encoding=None,
        working_dir=None,
        error_regexes=None,
    ):
        """Invoke brz, as if it were run from the command line.

        The argument list should not include the brz program name - the
        first argument is normally the brz command.  Arguments may be
        passed in three ways:

        1- A list of strings, eg ["commit", "a"].  This is recommended
        when the command contains whitespace or metacharacters, or
        is built up at run time.

        2- A single string, eg "add a".  This is the most convenient
        for hardcoded commands.

        This runs brz through the interface that catches and reports
        errors, and with logging set to something approximating the
        default, so that error reporting can be checked.

        This should be the main method for tests that want to exercise the
        overall behavior of the brz application (rather than a unit test
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
        if error_regexes is None:
            error_regexes = []
        if isinstance(args, str):
            args = shlex.split(args)

        if encoding is None:
            encoding = osutils.get_user_encoding()

        stdout = ui_testing.StringIOWithEncoding()
        stderr = ui_testing.StringIOWithEncoding()
        stdout.encoding = stderr.encoding = encoding
        handler = logging.StreamHandler(stream=stderr)
        handler.setLevel(logging.INFO)

        logger = logging.getLogger("")
        logger.addHandler(handler)

        try:
            result = self._run_bzr_core(
                args,
                encoding=encoding,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                working_dir=working_dir,
            )
        finally:
            logger.removeHandler(handler)

        out = stdout.getvalue()
        err = stderr.getvalue()
        if out:
            self.log("output:\n%r", out)
        if err:
            self.log("errors:\n%r", err)
        if retcode is not None:
            self.assertEqual(retcode, result, message="Unexpected return code")
        self.assertIsInstance(error_regexes, (list, tuple))
        for regex in error_regexes:
            self.assertContainsRe(err, regex)
        return out, err

    def run_bzr_error(self, error_regexes, *args, **kwargs):
        """Run brz, and check that stderr contains the supplied regexes.

        :param error_regexes: Sequence of regular expressions which
            must each be found in the error output. The relative ordering
            is not enforced.
        :param args: command-line arguments for brz
        :param kwargs: Keyword arguments which are interpreted by run_brz
            This function changes the default value of retcode to be 3,
            since in most cases this is run when you expect brz to fail.

        :return: (out, err) The actual output of running the command (in case
            you want to do more inspection)

        Examples of use::

            # Make sure that commit is failing because there is nothing to do
            self.run_bzr_error(['no changes to commit'],
                               ['commit', '-m', 'my commit comment'])
            # Make sure --strict is handling an unknown file, rather than
            # giving us the 'nothing to do' error
            self.build_tree(['unknown'])
            self.run_bzr_error(
                ['Commit refused because there are unknown files'],
                ['commit', --strict', '-m', 'my commit comment'])
        """
        kwargs.setdefault("retcode", 3)
        kwargs["error_regexes"] = error_regexes
        out, err = self.run_bzr(*args, **kwargs)
        return out, err

    def run_brz_subprocess(self, *args, **kwargs):
        """Run brz in a subprocess for testing.

        This starts a new Python interpreter and runs brz in there.
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
        env_changes = kwargs.get("env_changes")
        working_dir = kwargs.get("working_dir")
        allow_plugins = kwargs.get("allow_plugins", False)
        if len(args) == 1:
            if isinstance(args[0], list):
                args = args[0]
            elif isinstance(args[0], str):
                args = list(shlex.split(args[0]))
        else:
            raise ValueError("passing varargs to run_brz_subprocess")
        process = self.start_brz_subprocess(
            args,
            env_changes=env_changes,
            working_dir=working_dir,
            allow_plugins=allow_plugins,
        )
        # We distinguish between retcode=None and retcode not passed.
        supplied_retcode = kwargs.get("retcode", 0)
        return self.finish_brz_subprocess(
            process,
            retcode=supplied_retcode,
            universal_newlines=kwargs.get("universal_newlines", False),
            process_args=args,
        )

    def start_brz_subprocess(
        self,
        process_args,
        env_changes=None,
        skip_if_plan_to_signal=False,
        working_dir=None,
        allow_plugins=False,
        stderr=subprocess.PIPE,
    ):
        """Start brz in a subprocess for testing.

        This starts a new Python interpreter and runs brz in there.
        This should only be used for tests that have a justifiable need for
        this isolation: e.g. they are testing startup time, or signal
        handling, or early startup code, etc.  Subprocess code can't be
        profiled or debugged so easily.

        :param process_args: a list of arguments to pass to the brz executable,
            for example ``['--version']``.
        :param env_changes: A dictionary which lists changes to environment
            variables. A value of None will unset the env variable.
            The values must be strings. The change will only occur in the
            child, so you don't need to fix the environment after running.
        :param skip_if_plan_to_signal: raise TestSkipped when true and system
            doesn't support signalling subprocesses.
        :param allow_plugins: If False (default) pass --no-plugins to brz.
        :param stderr: file to use for the subprocess's stderr.  Valid values
            are those valid for the stderr argument of `subprocess.Popen`.
            Default value is ``subprocess.PIPE``.

        :returns: Popen object for the started process.
        """
        if skip_if_plan_to_signal:
            if os.name != "posix":
                raise TestSkipped("Sending signals not supported")

        if env_changes is None:
            env_changes = {}
        # Because $HOME is set to a tempdir for the context of a test, modules
        # installed in the user dir will not be found unless $PYTHONUSERBASE
        # gets set to the computed directory of this parent process.
        if site.USER_BASE is not None:
            env_changes["PYTHONUSERBASE"] = site.USER_BASE

        if "PYTHONPATH" not in env_changes:
            env_changes["PYTHONPATH"] = ":".join(sys.path)

        old_env = {}

        def cleanup_environment():
            for env_var, value in env_changes.items():
                old_env[env_var] = osutils.set_or_unset_env(env_var, value)

        def restore_environment():
            for env_var, value in old_env.items():
                osutils.set_or_unset_env(env_var, value)

        cwd = None
        if working_dir is not None:
            cwd = osutils.getcwd()
            os.chdir(working_dir)

        try:
            # win32 subprocess doesn't support preexec_fn
            # so we will avoid using it on all platforms, just to
            # make sure the code path is used, and we don't break on win32
            cleanup_environment()
            # Include the subprocess's log file in the test details, in case
            # the test fails due to an error in the subprocess.
            self._add_subprocess_log(trace._get_brz_log_filename())
            command = self.get_brz_command()
            if not allow_plugins:
                command.append("--no-plugins")
            command.extend(process_args)
            process = self._popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                bufsize=0,
            )
        finally:
            restore_environment()
            if cwd is not None:
                os.chdir(cwd)

        return process

    def _add_subprocess_log(self, log_file_path):
        if len(self._log_files) == 0:
            # Register an addCleanup func.  We do this on the first call to
            # _add_subprocess_log rather than in TestCase.setUp so that this
            # addCleanup is registered after any cleanups for tempdirs that
            # subclasses might create, which will probably remove the log file
            # we want to read.
            self.addCleanup(self._subprocess_log_cleanup)
        # self._log_files is a set, so if a log file is reused we won't grab it
        # twice.
        self._log_files.add(log_file_path)

    def _subprocess_log_cleanup(self):
        for count, log_file_path in enumerate(self._log_files):
            # We use buffer_now=True to avoid holding the file open beyond
            # the life of this function, which might interfere with e.g.
            # cleaning tempdirs on Windows.
            # XXX: Testtools 0.9.5 doesn't have the content_from_file helper
            # detail_content = content.content_from_file(
            #    log_file_path, buffer_now=True)
            with open(log_file_path, "rb") as log_file:
                log_file_bytes = log_file.read()
            detail_content = content.Content(
                content.ContentType("text", "plain", {"charset": "utf8"}),
                lambda: [log_file_bytes],
            )
            self.addDetail("start_brz_subprocess-log-%d" % (count,), detail_content)

    def _popen(self, *args, **kwargs):
        """Place a call to Popen.

        Allows tests to override this method to intercept the calls made to
        Popen for introspection.
        """
        return subprocess.Popen(*args, **kwargs)

    def get_source_path(self):
        """Return the path of the directory containing breezy."""
        return os.path.dirname(os.path.dirname(breezy.__file__))

    def get_brz_path(self):
        """Return the path of the 'brz' executable for this test suite."""
        brz_path = os.path.join(self.get_source_path(), "brz")
        if not os.path.isfile(brz_path):
            # We are probably installed. Assume sys.argv is the right file
            brz_path = sys.argv[0]
        return brz_path

    def get_brz_command(self):
        bzr_path = self.get_brz_path()
        if bzr_path.endswith("__main__.py"):
            return [sys.executable, "-m", "breezy"]
        else:
            return [bzr_path]

    def finish_brz_subprocess(
        self,
        process,
        retcode=0,
        send_signal=None,
        universal_newlines=False,
        process_args=None,
    ):
        """Finish the execution of process.

        :param process: the Popen object returned from start_brz_subprocess.
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
            out = out.replace(b"\r\n", b"\n")
            err = err.replace(b"\r\n", b"\n")

        if retcode is not None and retcode != process.returncode:
            if process_args is None:
                process_args = "(unknown args)"
            trace.mutter("Output of brz %r:\n%s", process_args, out)
            trace.mutter("Error for brz %r:\n%s", process_args, err)
            self.fail(
                "Command brz %r failed with retcode %d != %d"
                % (process_args, retcode, process.returncode)
            )
        return [out, err]

    def check_tree_shape(self, tree, shape):
        """Compare a tree to a list of expected names.

        Fail if they are not precisely equal.
        """
        extras = []
        shape = list(shape)  # copy
        for path, ie in tree.iter_entries_by_dir():
            name = path.replace("\\", "/")
            if ie.kind == "directory":
                name = name + "/"
            if name == "/":
                pass  # ignore root entry
            elif name in shape:
                shape.remove(name)
            else:
                extras.append(name)
        if shape:
            self.fail("expected paths not found in inventory: {!r}".format(shape))
        if extras:
            self.fail("unexpected paths found in inventory: {!r}".format(extras))

    def apply_redirected(
        self, stdin=None, stdout=None, stderr=None, a_callable=None, *args, **kwargs
    ):
        """Call callable with redirected std io pipes.

        Returns the return code.
        """
        if not callable(a_callable):
            raise ValueError("a_callable must be callable.")
        if stdin is None:
            stdin = BytesIO(b"")
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
        self.overrideAttr(lockdir, "_DEFAULT_TIMEOUT_SECONDS", 0)

    def make_utf8_encoded_stringio(self, encoding_type=None):
        """Return a wrapped BytesIO, that will encode text input to UTF-8."""
        if encoding_type is None:
            encoding_type = "strict"
        bio = BytesIO()
        output_encoding = "utf-8"
        sio = codecs.getwriter(output_encoding)(bio, errors=encoding_type)
        sio.encoding = output_encoding
        return sio

    def disable_verb(self, verb):
        """Disable a smart server verb for one test."""
        from breezy.bzr.smart import request

        request_handlers = request.request_handlers
        orig_method = request_handlers.get(verb)
        orig_info = request_handlers.get_info(verb)
        request_handlers.remove(verb)
        self.addCleanup(request_handlers.register, verb, orig_method, info=orig_info)

    def __hash__(self):
        return id(self)


class CapturedCall:
    """A helper for capturing smart server calls for easy debug analysis."""

    def __init__(self, params, prefix_length):
        """Capture the call with params and skip prefix_length stack frames."""
        self.call = params
        import traceback

        # The last 5 frames are the __init__, the hook frame, and 3 smart
        # client frames. Beyond this we could get more clever, but this is good
        # enough for now.
        stack = traceback.extract_stack()[prefix_length:-5]
        self._stack = "".join(traceback.format_list(stack))

    def __str__(self):
        return self.call.method.decode("utf-8")

    def __repr__(self):
        return self.call.method.decode("utf-8")

    def stack(self):
        return self._stack


class TestCaseWithMemoryTransport(TestCase):
    """Common test class for tests that do not need disk resources.

    Tests that need disk resources should derive from TestCaseInTempDir
    orTestCaseWithTransport.

    TestCaseWithMemoryTransport sets the TEST_ROOT variable for all brz tests.

    For TestCaseWithMemoryTransport the ``test_home_dir`` is set to the name of
    a directory which does not exist. This serves to help ensure test isolation
    is preserved. ``test_dir`` is set to the TEST_ROOT, as is cwd, because they
    must exist. However, TestCaseWithMemoryTransport does not offer local file
    defaults for the transport in tests, nor does it obey the command line
    override, so tests that accidentally write to the common directory should
    be rare.

    :cvar TEST_ROOT: Directory containing all temporary directories, plus a
        ``.bzr`` directory that stops us ascending higher into the filesystem.
    """

    TEST_ROOT = None
    _TEST_NAME = "test"

    def __init__(self, methodName="runTest"):
        # allow test parameterization after test construction and before test
        # execution. Variables that the parameterizer sets need to be
        # ones that are not set by setUp, or setUp will trash them.
        super().__init__(methodName)
        self.vfs_transport_factory = default_transport
        self.transport_server = None
        self.transport_readonly_server = None
        self.__vfs_server = None

    def setUp(self):
        super().setUp()

        def _add_disconnect_cleanup(transport):
            """Schedule disconnection of given transport at test cleanup.

            This needs to happen for all connected transports or leaks occur.

            Note reconnections may mean we call disconnect multiple times per
            transport which is suboptimal but seems harmless.
            """
            self.addCleanup(transport.disconnect)

        _mod_transport.Transport.hooks.install_named_hook(
            "post_connect", _add_disconnect_cleanup, None
        )

        self._make_test_root()
        self.addCleanup(os.chdir, osutils.getcwd())
        self.makeAndChdirToTestDir()
        self.overrideEnvironmentForTesting()
        self.__readonly_server = None
        self.__server = None
        self.reduceLockdirTimeout()
        # Each test may use its own config files even if the local config files
        # don't actually exist. They'll rightly fail if they try to create them
        # though.
        self.overrideAttr(config, "_shared_stores", {})

    def get_transport(self, relpath=None):
        """Return a writeable transport.

        This transport is for the test scratch space relative to
        "self._test_root"

        :param relpath: a path relative to the base url.
        """
        t = _mod_transport.get_transport_from_url(self.get_url(relpath))
        self.assertFalse(t.is_readonly())
        return t

    def get_readonly_transport(self, relpath=None):
        """Return a readonly transport for the test scratch space.

        This can be used to test that operations which should only need
        readonly access in fact do not try to write.

        :param relpath: a path relative to the base url.
        """
        t = _mod_transport.get_transport_from_url(self.get_readonly_url(relpath))
        self.assertTrue(t.is_readonly())
        return t

    def create_transport_readonly_server(self):
        """Create a transport server from class defined at init.

        This is mostly a hook for daughter classes.
        """
        return self.transport_readonly_server()

    def get_readonly_server(self):
        """Get the server instance for the readonly transport.

        This is useful for some tests with specific servers to do diagnostics.
        """
        if self.__readonly_server is None:
            if self.transport_readonly_server is None:
                # readonly decorator requested
                self.__readonly_server = test_server.ReadonlyServer()
            else:
                # explicit readonly transport.
                self.__readonly_server = self.create_transport_readonly_server()
            self.start_server(self.__readonly_server, self.get_vfs_only_server())
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
            self.__vfs_server = memory.MemoryServer()
            self.start_server(self.__vfs_server)
        return self.__vfs_server

    def get_server(self):
        """Get the read/write server instance.

        This is useful for some tests with specific servers that need
        diagnostics.

        This is built from the self.transport_server factory. If that is None,
        then the self.get_vfs_server is returned.
        """
        if self.__server is None:
            if (
                self.transport_server is None
                or self.transport_server is self.vfs_transport_factory
            ):
                self.__server = self.get_vfs_only_server()
            else:
                # bring up a decorated means of access to the vfs only server.
                self.__server = self.transport_server()
                self.start_server(self.__server, self.get_vfs_only_server())
        return self.__server

    def _adjust_url(self, base, relpath):
        """Get a URL (or maybe a path) for the readwrite transport.

        This will either be backed by '.' or to an equivalent non-file based
        facility.
        relpath provides for clients to get a path relative to the base url.
        These should only be downwards relative, not upwards.
        """
        if relpath is not None and relpath != ".":
            if not base.endswith("/"):
                base = base + "/"
            # XXX: Really base should be a url; we did after all call
            # get_url()!  But sometimes it's just a path (from
            # LocalAbspathServer), and it'd be wrong to append urlescaped data
            # to a non-escaped local path.
            if base.startswith("./") or base.startswith("/"):
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

    def _create_safety_net(self):
        """Make a fake bzr directory.

        This prevents any tests propagating up onto the TEST_ROOT directory's
        real branch.
        """
        root = TestCaseWithMemoryTransport.TEST_ROOT
        try:
            # Make sure we get a readable and accessible home for brz.log
            # and/or config files, and not fallback to weird defaults (see
            # http://pad.lv/825027).
            self.assertIs(None, os.environ.get("BRZ_HOME", None))
            os.environ["BRZ_HOME"] = root
            from breezy.bzr.bzrdir import BzrDirMetaFormat1

            wt = controldir.ControlDir.create_standalone_workingtree(
                root, format=BzrDirMetaFormat1()
            )
            del os.environ["BRZ_HOME"]
        except Exception as e:
            self.fail("Fail to initialize the safety net: {!r}\n".format(e))
        # Hack for speed: remember the raw bytes of the dirstate file so that
        # we don't need to re-open the wt to check it hasn't changed.
        TestCaseWithMemoryTransport._SAFETY_NET_PRISTINE_DIRSTATE = (
            wt.control_transport.get_bytes("dirstate")
        )

    def _check_safety_net(self):
        """Check that the safety .bzr directory have not been touched.

        _make_test_root have created a .bzr directory to prevent tests from
        propagating. This method ensures than a test did not leaked.
        """
        root = TestCaseWithMemoryTransport.TEST_ROOT
        t = _mod_transport.get_transport_from_path(root)
        self.permit_url(t.base)
        if (
            t.get_bytes(".bzr/checkout/dirstate")
            != TestCaseWithMemoryTransport._SAFETY_NET_PRISTINE_DIRSTATE
        ):
            # The current test have modified the /bzr directory, we need to
            # recreate a new one or all the followng tests will fail.
            # If you need to inspect its content uncomment the following line
            # import pdb; pdb.set_trace()
            _rmtree_temp_dir(root + "/.bzr", test_id=self.id())
            self._create_safety_net()
            raise AssertionError("{}/.bzr should not be modified".format(root))

    def _make_test_root(self):
        if TestCaseWithMemoryTransport.TEST_ROOT is None:
            # Watch out for tricky test dir (on OSX /tmp -> /private/tmp)
            root = osutils.realpath(tempfile.mkdtemp(prefix="testbzr-", suffix=".tmp"))
            TestCaseWithMemoryTransport.TEST_ROOT = root

            self._create_safety_net()

            # The same directory is used by all tests, and we're not
            # specifically told when all tests are finished.  This will do.
            atexit.register(_rmtree_temp_dir, root)

        self.permit_dir(TestCaseWithMemoryTransport.TEST_ROOT)
        self.addCleanup(self._check_safety_net)

    def makeAndChdirToTestDir(self):
        """Create a temporary directories for this one test.

        This must set self.test_home_dir and self.test_dir and chdir to
        self.test_dir.

        For TestCaseWithMemoryTransport we chdir to the TEST_ROOT for this
        test.
        """
        os.chdir(TestCaseWithMemoryTransport.TEST_ROOT)
        self.test_dir = TestCaseWithMemoryTransport.TEST_ROOT
        self.test_home_dir = self.test_dir + "/MemoryTransportMissingHomeDir"
        self.permit_dir(self.test_dir)

    def make_branch(self, relpath, format=None, name=None):
        """Create a branch on the transport at relpath."""
        repo = self.make_repository(relpath, format=format)
        return repo.controldir.create_branch(append_revisions_only=False, name=name)

    def get_default_format(self):
        return "default"

    def resolve_format(self, format):
        """Resolve an object to a ControlDir format object.

        The initial format object can either already be
        a ControlDirFormat, None (for the default format),
        or a string with the name of the control dir format.

        :param format: Object to resolve
        :return A ControlDirFormat instance
        """
        if format is None:
            format = self.get_default_format()
        if isinstance(format, str):
            format = controldir.format_registry.make_controldir(format)
        return format

    def make_controldir(self, relpath, format=None):
        try:
            # might be a relative or absolute path
            maybe_a_url = self.get_url(relpath)
            segments = maybe_a_url.rsplit("/", 1)
            t = _mod_transport.get_transport(maybe_a_url)
            if len(segments) > 1 and segments[-1] not in ("", "."):
                t.ensure_base()
            format = self.resolve_format(format)
            return format.initialize_on_transport(t)
        except errors.UninitializableFormat:
            raise TestSkipped("Format {} is not initializable.".format(format))

    def make_repository(self, relpath, shared=None, format=None):
        """Create a repository on our default transport at relpath.

        Note that relpath must be a relative path, not a full url.
        """
        # FIXME: If you create a remoterepository this returns the underlying
        # real format, which is incorrect.  Actually we should make sure that
        # RemoteBzrDir returns a RemoteRepository.
        # maybe  mbp 20070410
        made_control = self.make_controldir(relpath, format=format)
        return made_control.create_repository(shared=shared)

    def make_smart_server(self, path, backing_server=None):
        if backing_server is None:
            backing_server = self.get_server()
        smart_server = test_server.SmartTCPServer_for_testing()
        self.start_server(smart_server, backing_server)
        remote_transport = _mod_transport.get_transport_from_url(
            smart_server.get_url()
        ).clone(path)
        return remote_transport

    def make_branch_and_memory_tree(self, relpath, format=None):
        """Create a branch on the default transport and a MemoryTree for it."""
        b = self.make_branch(relpath, format=format)
        return b.create_memorytree()

    def make_branch_builder(self, relpath, format=None):
        branch = self.make_branch(relpath, format=format)
        return branchbuilder.BranchBuilder(branch=branch)

    def overrideEnvironmentForTesting(self):
        test_home_dir = self.test_home_dir
        self.overrideEnv("HOME", test_home_dir)
        self.overrideEnv("BRZ_HOME", test_home_dir)
        self.overrideEnv("GNUPGHOME", os.path.join(test_home_dir, ".gnupg"))

    def setup_smart_server_with_call_log(self):
        """Sets up a smart server as the transport server with a call log."""
        self.transport_server = test_server.SmartTCPServer_for_testing
        self.hpss_connections = []
        self.hpss_calls = []
        import traceback

        # Skip the current stack down to the caller of
        # setup_smart_server_with_call_log
        prefix_length = len(traceback.extract_stack()) - 2

        def capture_hpss_call(params):
            self.hpss_calls.append(CapturedCall(params, prefix_length))

        def capture_connect(transport):
            self.hpss_connections.append(transport)

        client._SmartClient.hooks.install_named_hook("call", capture_hpss_call, None)
        _mod_transport.Transport.hooks.install_named_hook(
            "post_connect", capture_connect, None
        )

    def reset_smart_call_log(self):
        self.hpss_calls = []
        self.hpss_connections = []


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

    OVERRIDE_PYTHON = "python"

    def setUp(self):
        super().setUp()
        # Remove the protection set in isolated_environ, we have a proper
        # access to disk resources now.
        self.overrideEnv("BRZ_LOG", None)

    def check_file_contents(self, filename, expect):
        self.log("check contents of file {}".format(filename))
        with open(filename, "rb") as f:
            contents = f.read()
        if contents != expect:
            self.log("expected: {!r}".format(expect))
            self.log("actually: {!r}".format(contents))
            self.fail("contents of {} not as expected".format(filename))

    def _getTestDirPrefix(self):
        # create a directory within the top level test directory
        if sys.platform in ("win32", "cygwin"):
            name_prefix = re.sub('[<>*=+",:;_/\\-]', "_", self.id())
            # windows is likely to have path-length limits so use a short name
            name_prefix = name_prefix[-30:]
        else:
            name_prefix = re.sub("[/]", "_", self.id())
        return name_prefix

    def makeAndChdirToTestDir(self):
        """See TestCaseWithMemoryTransport.makeAndChdirToTestDir().

        For TestCaseInTempDir we create a temporary directory based on the test
        name and then create two subdirs - test and home under it.
        """
        name_prefix = osutils.pathjoin(
            TestCaseWithMemoryTransport.TEST_ROOT, self._getTestDirPrefix()
        )
        name = name_prefix
        for i in range(100):
            if os.path.exists(name):
                name = name_prefix + "_" + str(i)
            else:
                # now create test and home directories within this dir
                self.test_base_dir = name
                self.addCleanup(self.deleteTestDir)
                os.mkdir(self.test_base_dir)
                break
        self.permit_dir(self.test_base_dir)
        # 'sprouting' and 'init' of a branch both walk up the tree to find
        # stacking policy to honour; create a bzr dir with an unshared
        # repository (but not a branch - our code would be trying to escape
        # then!) to stop them, and permit it to be read.
        # control = controldir.ControlDir.create(self.test_base_dir)
        # control.create_repository()
        self.test_home_dir = self.test_base_dir + "/home"
        os.mkdir(self.test_home_dir)
        self.test_dir = self.test_base_dir + "/work"
        os.mkdir(self.test_dir)
        os.chdir(self.test_dir)
        # put name of test inside
        with open(self.test_base_dir + "/name", "w") as f:
            f.write(self.id())

    def deleteTestDir(self):
        os.chdir(TestCaseWithMemoryTransport.TEST_ROOT)
        _rmtree_temp_dir(self.test_base_dir, test_id=self.id())

    def build_tree(self, shape, line_endings="binary", transport=None):
        """Build a test tree according to a pattern.

        shape is a sequence of file specifications.  If the final
        character is '/', a directory is created.

        This assumes that all the elements in the tree being built are new.

        This doesn't add anything to a branch.

        :type shape:    list or tuple.
        :param line_endings: Either 'binary' or 'native'
            in binary mode, exact contents are written in native mode, the
            line endings match the default platform endings.
        :param transport: A transport to write to, for building trees on VFS's.
            If the transport is readonly or None, "." is opened automatically.
        :return: None
        """
        if type(shape) not in (list, tuple):
            raise AssertionError(
                "Parameter 'shape' should be "
                "a list or a tuple. Got {!r} instead".format(shape)
            )
        # It's OK to just create them using forward slashes on windows.
        if transport is None or transport.is_readonly():
            transport = _mod_transport.get_transport_from_path(".")
        for name in shape:
            self.assertIsInstance(name, str)
            if name[-1] == "/":
                transport.mkdir(urlutils.escape(name[:-1]))
            else:
                if line_endings == "binary":
                    end = b"\n"
                elif line_endings == "native":
                    end = os.linesep.encode("ascii")
                else:
                    raise errors.BzrError(
                        "Invalid line ending request {!r}".format(line_endings)
                    )
                content = b"contents of %s%s" % (name.encode("utf-8"), end)
                transport.put_bytes_non_atomic(urlutils.escape(name), content)

    build_tree_contents = staticmethod(treeshape.build_tree_contents)

    def assertInWorkingTree(self, path, root_path=".", tree=None):
        """Assert whether path or paths are in the WorkingTree."""
        if tree is None:
            tree = workingtree.WorkingTree.open(root_path)
        if not isinstance(path, str):
            for p in path:
                self.assertInWorkingTree(p, tree=tree)
        else:
            self.assertTrue(tree.is_versioned(path), path + " not in working tree.")

    def assertNotInWorkingTree(self, path, root_path=".", tree=None):
        """Assert whether path or paths are not in the WorkingTree."""
        if tree is None:
            tree = workingtree.WorkingTree.open(root_path)
        if not isinstance(path, str):
            for p in path:
                self.assertNotInWorkingTree(p, tree=tree)
        else:
            self.assertFalse(tree.is_versioned(path), path + " in working tree.")


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

    def setUp(self):
        super().setUp()
        self.__vfs_server = None

    def get_vfs_only_server(self):
        """See TestCaseWithMemoryTransport.

        This is useful for some tests with specific servers that need
        diagnostics.
        """
        if self.__vfs_server is None:
            self.__vfs_server = self.vfs_transport_factory()
            self.start_server(self.__vfs_server)
        return self.__vfs_server

    def make_branch_and_tree(self, relpath, format=None):
        """Create a branch on the transport and a tree locally.

        If the transport is not a LocalTransport, the Tree can't be created on
        the transport.  In that case if the vfs_transport_factory is
        LocalURLServer the working tree is created in the local
        directory backing the transport, and the returned tree's branch and
        repository will also be accessed locally. Otherwise a lightweight
        checkout is created and returned.

        We do this because we can't physically create a tree in the local
        path, with a branch reference to the transport_factory url, and
        a branch + repository in the vfs_transport, unless the vfs_transport
        namespace is distinct from the local disk - the two branch objects
        would collide. While we could construct a tree with its branch object
        pointing at the transport_factory transport in memory, reopening it
        would behaving unexpectedly, and has in the past caused testing bugs
        when we tried to do it that way.

        :param format: The BzrDirFormat.
        :returns: the WorkingTree.
        """
        # TODO: always use the local disk path for the working tree,
        # this obviously requires a format that supports branch references
        # so check for that by checking bzrdir.BzrDirFormat.get_default_format()
        # RBC 20060208
        format = self.resolve_format(format=format)
        if not format.supports_workingtrees:
            b = self.make_branch(relpath + ".branch", format=format)
            return b.create_checkout(relpath, lightweight=True)
        b = self.make_branch(relpath, format=format)
        try:
            return b.controldir.create_workingtree()
        except errors.NotLocalUrl:
            # We can only make working trees locally at the moment.  If the
            # transport can't support them, then we keep the non-disk-backed
            # branch and create a local checkout.
            if self.vfs_transport_factory is test_server.LocalURLServer:
                # the branch is colocated on disk, we cannot create a checkout.
                # hopefully callers will expect this.
                local_controldir = controldir.ControlDir.open(
                    self.get_vfs_only_url(relpath)
                )
                wt = local_controldir.create_workingtree()
                if wt.branch._format != b._format:
                    wt._branch = b
                    # Make sure that assigning to wt._branch fixes wt.branch,
                    # in case the implementation details of workingtree objects
                    # change.
                    self.assertIs(b, wt.branch)
                return wt
            else:
                return b.create_checkout(relpath, lightweight=True)

    def assertIsDirectory(self, relpath, transport):
        """Assert that relpath within transport is a directory.

        This may not be possible on all transports; in that case it propagates
        a TransportNotPossible.
        """
        try:
            mode = transport.stat(relpath).st_mode
        except _mod_transport.NoSuchFile:
            self.fail("path {} is not a directory; no such file".format(relpath))
        if not stat.S_ISDIR(mode):
            self.fail("path {} is not a directory; has mode {:#o}".format(relpath, mode))

    def assertTreesEqual(self, left, right):
        """Check that left and right have the same content and properties."""
        # we use a tree delta to check for equality of the content, and we
        # manually check for equality of other things such as the parents list.
        self.assertEqual(left.get_parent_ids(), right.get_parent_ids())
        differences = left.changes_from(right)
        self.assertFalse(
            differences.has_changed(),
            "Trees {!r} and {!r} are different: {!r}".format(left, right, differences),
        )

    def disable_missing_extensions_warning(self):
        """Some tests expect a precise stderr content.

        There is no point in forcing them to duplicate the extension related
        warning.
        """
        config.GlobalConfig().set_user_option("suppress_warnings", "missing_extensions")


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
        from breezy.tests import http_server

        super().setUp()
        if self.vfs_transport_factory != memory.MemoryServer:
            self.transport_readonly_server = http_server.HttpServer


def condition_id_re(pattern):
    """Create a condition filter which performs a re check on a test's id.

    :param pattern: A regular expression string.
    :return: A callable that returns True if the re matches.
    """
    filter_re = re.compile(pattern, 0)

    def condition(test):
        test_id = test.id()
        return filter_re.search(test_id)

    return condition


def condition_isinstance(klass_or_klass_list):
    """Create a condition filter which returns isinstance(param, klass).

    :return: A callable which when called with one parameter obj return the
        result of isinstance(obj, klass_or_klass_list).
    """

    def condition(obj):
        return isinstance(obj, klass_or_klass_list)

    return condition


def condition_id_in_list(id_list):
    """Create a condition filter which verify that test's id in a list.

    :param id_list: A TestIdList object.
    :return: A callable that returns True if the test's id appears in the list.
    """

    def condition(test):
        return id_list.includes(test.id())

    return condition


def condition_id_startswith(starts):
    """Create a condition filter verifying that test's id starts with a string.

    :param starts: A list of string.
    :return: A callable that returns True if the test's id starts with one of
        the given strings.
    """

    def condition(test):
        return any(test.id().startswith(start) for start in starts)

    return condition


def exclude_tests_by_condition(suite, condition):
    """Create a test suite which excludes some tests from suite.

    :param suite: The suite to get tests from.
    :param condition: A callable whose result evaluates True when called with a
        test case which should be excluded from the result.
    :return: A suite which contains the tests found in suite that fail
        condition.
    """
    result = []
    for test in iter_suite_tests(suite):
        if not condition(test):
            result.append(test)
    return TestUtil.TestSuite(result)


def filter_suite_by_condition(suite, condition):
    """Create a test suite by filtering another one.

    :param suite: The source suite.
    :param condition: A callable whose result evaluates True when called with a
        test case which should be included in the result.
    :return: A suite which contains the tests found in suite that pass
        condition.
    """
    result = []
    for test in iter_suite_tests(suite):
        if condition(test):
            result.append(test)
    return TestUtil.TestSuite(result)


def filter_suite_by_re(suite, pattern):
    """Create a test suite by filtering another one.

    :param suite:           the source suite
    :param pattern:         pattern that names must match
    :returns: the newly created suite
    """
    condition = condition_id_re(pattern)
    result_suite = filter_suite_by_condition(suite, condition)
    return result_suite


def filter_suite_by_id_list(suite, test_id_list):
    """Create a test suite by filtering another one.

    :param suite: The source suite.
    :param test_id_list: A list of the test ids to keep as strings.
    :returns: the newly created suite
    """
    condition = condition_id_in_list(test_id_list)
    result_suite = filter_suite_by_condition(suite, condition)
    return result_suite


def filter_suite_by_id_startswith(suite, start):
    """Create a test suite by filtering another one.

    :param suite: The source suite.
    :param start: A list of string the test id must start with one of.
    :returns: the newly created suite
    """
    condition = condition_id_startswith(start)
    result_suite = filter_suite_by_condition(suite, condition)
    return result_suite


def exclude_tests_by_re(suite, pattern):
    """Create a test suite which excludes some tests from suite.

    :param suite: The suite to get tests from.
    :param pattern: A regular expression string. Test ids that match this
        pattern will be excluded from the result.
    :return: A TestSuite that contains all the tests from suite without the
        tests that matched pattern. The order of tests is the same as it was in
        suite.
    """
    return exclude_tests_by_condition(suite, condition_id_re(pattern))


def preserve_input(something):
    """A helper for performing test suite transformation chains.

    :param something: Anything you want to preserve.
    :return: Something.
    """
    return something


def randomize_suite(suite):
    """Return a new TestSuite with suite's tests in random order.

    The tests in the input suite are flattened into a single suite in order to
    accomplish this. Any nested TestSuites are removed to provide global
    randomness.
    """
    tests = list(iter_suite_tests(suite))
    random.shuffle(tests)
    return TestUtil.TestSuite(tests)


def split_suite_by_condition(suite, condition):
    """Split a test suite into two by a condition.

    :param suite: The suite to split.
    :param condition: The condition to match on. Tests that match this
        condition are returned in the first test suite, ones that do not match
        are in the second suite.
    :return: A tuple of two test suites, where the first contains tests from
        suite matching the condition, and the second contains the remainder
        from suite. The order within each output suite is the same as it was in
        suite.
    """
    matched = []
    did_not_match = []
    for test in iter_suite_tests(suite):
        if condition(test):
            matched.append(test)
        else:
            did_not_match.append(test)
    return TestUtil.TestSuite(matched), TestUtil.TestSuite(did_not_match)


def split_suite_by_re(suite, pattern):
    """Split a test suite into two by a regular expression.

    :param suite: The suite to split.
    :param pattern: A regular expression string. Test ids that match this
        pattern will be in the first test suite returned, and the others in the
        second test suite returned.
    :return: A tuple of two test suites, where the first contains tests from
        suite matching pattern, and the second contains the remainder from
        suite. The order within each output suite is the same as it was in
        suite.
    """
    return split_suite_by_condition(suite, condition_id_re(pattern))


def run_suite(
    suite,
    name="test",
    verbose=False,
    pattern=".*",
    stop_on_failure=False,
    transport=None,
    lsprof_timed=None,
    bench_history=None,
    matching_tests_first=None,
    list_only=False,
    random_seed=None,
    exclude_pattern=None,
    strict=False,
    runner_class=None,
    suite_decorators=None,
    stream=None,
    result_decorators=None,
):
    """Run a test suite for brz selftest.

    :param runner_class: The class of runner to use. Must support the
        constructor arguments passed by run_suite which are more than standard
        python uses.
    :return: A boolean indicating success.
    """
    TestCase._gather_lsprof_in_benchmarks = lsprof_timed
    if verbose:
        verbosity = 2
    else:
        verbosity = 1
    if runner_class is None:
        runner_class = TextTestRunner
    if stream is None:
        stream = sys.stdout
    runner = runner_class(
        stream=stream,
        descriptions=0,
        verbosity=verbosity,
        bench_history=bench_history,
        strict=strict,
        result_decorators=result_decorators,
    )
    runner.stop_on_failure = stop_on_failure
    if isinstance(suite, unittest.TestSuite):
        # Empty out _tests list of passed suite and populate new TestSuite
        suite._tests[:], suite = [], TestSuite(suite)
    # built in decorator factories:
    decorators = [
        random_order(random_seed, runner),
        exclude_tests(exclude_pattern),
    ]
    if matching_tests_first:
        decorators.append(tests_first(pattern))
    else:
        decorators.append(filter_tests(pattern))
    if suite_decorators:
        decorators.extend(suite_decorators)
    # tell the result object how many tests will be running: (except if
    # --parallel=fork is being used. Robert said he will provide a better
    # progress design later -- vila 20090817)
    if fork_decorator not in decorators:
        decorators.append(CountingDecorator)
    for decorator in decorators:
        suite = decorator(suite)
    if list_only:
        # Done after test suite decoration to allow randomisation etc
        # to take effect, though that is of marginal benefit.
        if verbosity >= 2:
            stream.write("Listing tests only ...\n")
        if getattr(runner, "list", None) is not None:
            runner.list(suite)
        else:
            for t in iter_suite_tests(suite):
                stream.write("{}\n".format(t.id()))
        return True
    result = runner.run(suite)
    if strict and getattr(result, "wasStrictlySuccessful", False):
        return result.wasStrictlySuccessful()
    else:
        return result.wasSuccessful()


# A registry where get() returns a suite decorator.
parallel_registry = registry.Registry[str, Callable]()


def fork_decorator(suite):
    if getattr(os, "fork", None) is None:
        raise errors.CommandError(
            "platform does not support fork, try --parallel=subprocess instead."
        )
    concurrency = osutils.local_concurrency()
    if concurrency == 1:
        return suite
    from testtools import ConcurrentTestSuite

    return ConcurrentTestSuite(suite, fork_for_tests)


parallel_registry.register("fork", fork_decorator)


def subprocess_decorator(suite):
    concurrency = osutils.local_concurrency()
    if concurrency == 1:
        return suite
    from testtools import ConcurrentTestSuite

    return ConcurrentTestSuite(suite, reinvoke_for_tests)


parallel_registry.register("subprocess", subprocess_decorator)


def exclude_tests(exclude_pattern):
    """Return a test suite decorator that excludes tests."""
    if exclude_pattern is None:
        return identity_decorator

    def decorator(suite):
        return ExcludeDecorator(suite, exclude_pattern)

    return decorator


def filter_tests(pattern):
    if pattern == ".*":
        return identity_decorator

    def decorator(suite):
        return FilterTestsDecorator(suite, pattern)

    return decorator


def random_order(random_seed, runner):
    """Return a test suite decorator factory for randomising tests order.

    :param random_seed: now, a string which casts to an integer, or an integer.
    :param runner: A test runner with a stream attribute to report on.
    """
    if random_seed is None:
        return identity_decorator

    def decorator(suite):
        return RandomDecorator(suite, random_seed, runner.stream)

    return decorator


def tests_first(pattern):
    if pattern == ".*":
        return identity_decorator

    def decorator(suite):
        return TestFirstDecorator(suite, pattern)

    return decorator


def identity_decorator(suite):
    """Return suite."""
    return suite


class TestDecorator(TestUtil.TestSuite):
    """A decorator for TestCase/TestSuite objects.

    Contains rather than flattening suite passed on construction
    """

    def __init__(self, suite=None):
        super().__init__()
        if suite is not None:
            self.addTest(suite)

    # Don't need subclass run method with suite emptying
    run = unittest.TestSuite.run  # type: ignore


class CountingDecorator(TestDecorator):
    """A decorator which calls result.progress(self.countTestCases)."""

    def run(self, result):
        progress_method = getattr(result, "progress", None)
        if callable(progress_method):
            progress_method(self.countTestCases(), SUBUNIT_SEEK_SET)
        return super().run(result)


class ExcludeDecorator(TestDecorator):
    """A decorator which excludes test matching an exclude pattern."""

    def __init__(self, suite, exclude_pattern):
        super().__init__(exclude_tests_by_re(suite, exclude_pattern))


class FilterTestsDecorator(TestDecorator):
    """A decorator which filters tests to those matching a pattern."""

    def __init__(self, suite, pattern):
        super().__init__(filter_suite_by_re(suite, pattern))


class RandomDecorator(TestDecorator):
    """A decorator which randomises the order of its tests."""

    def __init__(self, suite, random_seed, stream):
        random_seed = self.actual_seed(random_seed)
        stream.write("Randomizing test order using seed {}\n\n".format(random_seed))
        # Initialise the random number generator.
        random.seed(random_seed)
        super().__init__(randomize_suite(suite))

    @staticmethod
    def actual_seed(seed):
        if seed == "now":
            # We convert the seed to an integer to make it reuseable across
            # invocations (because the user can reenter it).
            return int(time.time())
        else:
            # Convert the seed to an integer if we can
            try:
                return int(seed)
            except (TypeError, ValueError):
                pass
        return seed


class TestFirstDecorator(TestDecorator):
    """A decorator which moves named tests to the front."""

    def __init__(self, suite, pattern):
        super().__init__()
        self.addTests(split_suite_by_re(suite, pattern))


def partition_tests(suite, count):
    """Partition suite into count lists of tests."""
    # This just assigns tests in a round-robin fashion.  On one hand this
    # splits up blocks of related tests that might run faster if they shared
    # resources, but on the other it avoids assigning blocks of slow tests to
    # just one partition.  So the slowest partition shouldn't be much slower
    # than the fastest.
    partitions = [[] for i in range(count)]
    tests = iter_suite_tests(suite)
    for partition, test in zip(itertools.cycle(partitions), tests):
        partition.append(test)
    return partitions


def workaround_zealous_crypto_random():
    """Crypto.Random want to help us being secure, but we don't care here.

    This workaround some test failure related to the sftp server. Once paramiko
    stop using the controversial API in Crypto.Random, we may get rid of it.
    """
    try:
        from Crypto.Random import atfork

        atfork()
    except ModuleNotFoundError:
        pass


def fork_for_tests(suite):
    """Take suite and start up one runner per CPU by forking().

    :return: An iterable of TestCase-like objects which can each have
        run(result) called on them to feed tests to result.
    """
    concurrency = osutils.local_concurrency()
    result = []
    from subunit import ProtocolTestCase
    from subunit.test_results import AutoTimingTestResultDecorator

    class TestInOtherProcess(ProtocolTestCase):
        # Should be in subunit, I think. RBC.
        def __init__(self, stream, pid):
            ProtocolTestCase.__init__(self, stream)
            self.pid = pid

        def run(self, result):
            try:
                ProtocolTestCase.run(self, result)
            finally:
                pid, status = os.waitpid(self.pid, 0)
            # GZ 2011-10-18: If status is nonzero, should report to the result
            #                that something went wrong.

    test_blocks = partition_tests(suite, concurrency)
    # Clear the tests from the original suite so it doesn't keep them alive
    suite._tests[:] = []
    for process_tests in test_blocks:
        process_suite = TestUtil.TestSuite(process_tests)
        # Also clear each split list so new suite has only reference
        process_tests[:] = []
        c2pread, c2pwrite = os.pipe()
        pid = os.fork()
        if pid == 0:
            try:
                stream = os.fdopen(c2pwrite, "wb", 0)
                workaround_zealous_crypto_random()
                try:
                    import coverage
                except ModuleNotFoundError:
                    pass
                else:
                    coverage.process_startup()
                os.close(c2pread)
                # Leave stderr and stdout open so we can see test noise
                # Close stdin so that the child goes away if it decides to
                # read from stdin (otherwise its a roulette to see what
                # child actually gets keystrokes for pdb etc).
                sys.stdin.close()
                subunit_result = AutoTimingTestResultDecorator(
                    SubUnitBzrProtocolClientv1(stream)
                )
                process_suite.run(subunit_result)
            except:  # noqa: E722
                # Try and report traceback on stream, but exit with error even
                # if stream couldn't be created or something else goes wrong.
                # The traceback is formatted to a string and written in one go
                # to avoid interleaving lines from multiple failing children.
                tb = traceback.format_exc()
                if isinstance(tb, str):
                    tb = tb.encode("utf-8")
                try:
                    stream.write(tb)
                finally:
                    stream.flush()
                    os._exit(1)
            os._exit(0)
        else:
            os.close(c2pwrite)
            stream = os.fdopen(c2pread, "rb", 0)
            test = TestInOtherProcess(stream, pid)
            result.append(test)
    return result


def reinvoke_for_tests(suite):
    """Take suite and start up one runner per CPU using subprocess().

    :return: An iterable of TestCase-like objects which can each have
        run(result) called on them to feed tests to result.
    """
    concurrency = osutils.local_concurrency()
    result = []
    from subunit import ProtocolTestCase

    class TestInSubprocess(ProtocolTestCase):
        def __init__(self, process, name):
            ProtocolTestCase.__init__(self, process.stdout)
            self.process = process
            self.process.stdin.close()
            self.name = name

        def run(self, result):
            try:
                ProtocolTestCase.run(self, result)
            finally:
                self.process.wait()
                os.unlink(self.name)
            # print "pid %d finished" % finished_process

    test_blocks = partition_tests(suite, concurrency)
    for process_tests in test_blocks:
        # ugly; currently reimplement rather than reuses TestCase methods.
        bzr_path = os.path.dirname(os.path.dirname(breezy.__file__)) + "/bzr"
        if not os.path.isfile(bzr_path):
            # We are probably installed. Assume sys.argv is the right file
            bzr_path = sys.argv[0]
        bzr_path = [bzr_path]
        fd, test_list_file_name = tempfile.mkstemp()
        test_list_file = os.fdopen(fd, "wb", 1)
        for test in process_tests:
            test_list_file.write(test.id() + "\n")
        test_list_file.close()
        try:
            argv = bzr_path + [
                "selftest",
                "--load-list",
                test_list_file_name,
                "--subunit",
            ]
            if "--no-plugins" in sys.argv:
                argv.append("--no-plugins")
            # stderr=subprocess.STDOUT would be ideal, but until we prevent
            # noise on stderr it can interrupt the subunit protocol.
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
            )
            test = TestInSubprocess(process, test_list_file_name)
            result.append(test)
        except:
            os.unlink(test_list_file_name)
            raise
    return result


class ProfileResult(testtools.ExtendedToOriginalDecorator):
    """Generate profiling data for all activity between start and success.

    The profile data is appended to the test's _benchcalls attribute and can
    be accessed by the forwarded-to TestResult.

    While it might be cleaner do accumulate this in stopTest, addSuccess is
    where our existing output support for lsprof is, and this class aims to
    fit in with that: while it could be moved it's not necessary to accomplish
    test profiling, nor would it be dramatically cleaner.
    """

    def startTest(self, test):
        self.profiler = breezy.lsprof.BzrProfiler()
        # Prevent deadlocks in tests that use lsprof: those tests will
        # unavoidably fail.
        breezy.lsprof.BzrProfiler.profiler_block = 0
        self.profiler.start()
        testtools.ExtendedToOriginalDecorator.startTest(self, test)

    def addSuccess(self, test):
        stats = self.profiler.stop()
        try:
            calls = test._benchcalls
        except AttributeError:
            test._benchcalls = []
            calls = test._benchcalls
        calls.append(((test.id(), "", ""), stats))
        testtools.ExtendedToOriginalDecorator.addSuccess(self, test)

    def stopTest(self, test):
        testtools.ExtendedToOriginalDecorator.stopTest(self, test)
        self.profiler = None


# Controlled by "brz selftest -E=..." option
# Currently supported:
#   -Eallow_debug           Will no longer clear debug.debug_flags() so it
#                           preserves any flags supplied at the command line.
#   -Edisable_lock_checks   Turns errors in mismatched locks into simple prints
#                           rather than failing tests. And no longer raise
#                           LockContention when fctnl locks are not being used
#                           with proper exclusion rules.
#   -Ethreads               Will display thread ident at creation/join time to
#                           help track thread leaks
#   -Euncollected_cases     Display the identity of any test cases that weren't
#                           deallocated after being completed.
#   -Econfig_stats          Will collect statistics using addDetail
selftest_debug_flags: set[str] = set()


def selftest(
    verbose=False,
    pattern=".*",
    stop_on_failure=True,
    transport=None,
    test_suite_factory=None,
    lsprof_timed=None,
    bench_history=None,
    matching_tests_first=None,
    list_only=False,
    random_seed=None,
    exclude_pattern=None,
    strict=False,
    load_list=None,
    debug_flags=None,
    starting_with=None,
    runner_class=None,
    suite_decorators=None,
    stream=None,
    lsprof_tests=False,
):
    """Run the whole test suite under the enhanced runner."""
    # XXX: Very ugly way to do this...
    # Disable warning about old formats because we don't want it to disturb
    # any blackbox tests.
    from breezy import repository

    repository._deprecation_warning_done = True

    global default_transport
    if transport is None:
        transport = default_transport
    old_transport = default_transport
    default_transport = transport
    global selftest_debug_flags
    old_debug_flags = selftest_debug_flags
    if debug_flags is not None:
        selftest_debug_flags = set(debug_flags)
    try:
        if load_list is None:
            keep_only = None
        else:
            keep_only = load_test_id_list(load_list)
        if starting_with:
            starting_with = [
                test_prefix_alias_registry.resolve_alias(start)
                for start in starting_with
            ]
            # Always consider 'unittest' an interesting name so that failed
            # suites wrapped as test cases appear in the output.
            starting_with.append("unittest")
        if test_suite_factory is None:
            # Reduce loading time by loading modules based on the starting_with
            # patterns.
            suite = test_suite(keep_only, starting_with)
        else:
            suite = test_suite_factory()
        if starting_with:
            # But always filter as requested.
            suite = filter_suite_by_id_startswith(suite, starting_with)
        result_decorators = []
        if lsprof_tests:
            result_decorators.append(ProfileResult)
        return run_suite(
            suite,
            "testbzr",
            verbose=verbose,
            pattern=pattern,
            stop_on_failure=stop_on_failure,
            transport=transport,
            lsprof_timed=lsprof_timed,
            bench_history=bench_history,
            matching_tests_first=matching_tests_first,
            list_only=list_only,
            random_seed=random_seed,
            exclude_pattern=exclude_pattern,
            strict=strict,
            runner_class=runner_class,
            suite_decorators=suite_decorators,
            stream=stream,
            result_decorators=result_decorators,
        )
    finally:
        default_transport = old_transport
        selftest_debug_flags = old_debug_flags


def load_test_id_list(file_name):
    """Load a test id list from a text file.

    The format is one test id by line.  No special care is taken to impose
    strict rules, these test ids are used to filter the test suite so a test id
    that do not match an existing test will do no harm. This allows user to add
    comments, leave blank lines, etc.
    """
    test_list = []
    try:
        ftest = open(file_name)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise
        else:
            raise _mod_transport.NoSuchFile(file_name)

    for test_name in ftest.readlines():
        test_list.append(test_name.strip())
    ftest.close()
    return test_list


def suite_matches_id_list(test_suite, id_list):
    """Warns about tests not appearing or appearing more than once.

    :param test_suite: A TestSuite object.
    :param test_id_list: The list of test ids that should be found in
         test_suite.

    :return: (absents, duplicates) absents is a list containing the test found
        in id_list but not in test_suite, duplicates is a list containing the
        tests found multiple times in test_suite.

    When using a prefined test id list, it may occurs that some tests do not
    exist anymore or that some tests use the same id. This function warns the
    tester about potential problems in his workflow (test lists are volatile)
    or in the test suite itself (using the same id for several tests does not
    help to localize defects).
    """
    # Build a dict counting id occurrences
    tests = {}
    for test in iter_suite_tests(test_suite):
        id = test.id()
        tests[id] = tests.get(id, 0) + 1

    not_found = []
    duplicates = []
    for id in id_list:
        occurs = tests.get(id, 0)
        if not occurs:
            not_found.append(id)
        elif occurs > 1:
            duplicates.append(id)

    return not_found, duplicates


class TestIdList:
    """Test id list to filter a test suite.

    Relying on the assumption that test ids are built as:
    <module>[.<class>.<method>][(<param>+)], <module> being in python dotted
    notation, this class offers methods to :
    - avoid building a test suite for modules not refered to in the test list,
    - keep only the tests listed from the module test suite.
    """

    def __init__(self, test_id_list):
        # When a test suite needs to be filtered against us we compare test ids
        # for equality, so a simple dict offers a quick and simple solution.
        self.tests = {}.fromkeys(test_id_list, True)

        # While unittest.TestCase have ids like:
        # <module>.<class>.<method>[(<param+)],
        # doctest.DocTestCase can have ids like:
        # <module>
        # <module>.<class>
        # <module>.<function>
        # <module>.<class>.<method>

        # Since we can't predict a test class from its name only, we settle on
        # a simple constraint: a test id always begins with its module name.

        modules = {}
        for test_id in test_id_list:
            parts = test_id.split(".")
            mod_name = parts.pop(0)
            modules[mod_name] = True
            for part in parts:
                mod_name += "." + part
                modules[mod_name] = True
        self.modules = modules

    def refers_to(self, module_name):
        """Is there tests for the module or one of its sub modules."""
        return module_name in self.modules

    def includes(self, test_id):
        return test_id in self.tests


class TestPrefixAliasRegistry(registry.Registry):
    """A registry for test prefix aliases.

    This helps implement shorcuts for the --starting-with selftest
    option. Overriding existing prefixes is not allowed but not fatal (a
    warning will be emitted).
    """

    def register(self, key, obj, help=None, info=None, override_existing=False):
        """See Registry.register.

        Trying to override an existing alias causes a warning to be emitted,
        not a fatal execption.
        """
        try:
            super().register(key, obj, help=help, info=info, override_existing=False)
        except KeyError:
            actual = self.get(key)
            trace.note(
                "Test prefix alias {} is already used for {}, ignoring {}".format(key, actual, obj)
            )

    def resolve_alias(self, id_start):
        """Replace the alias by the prefix in the given string.

        Using an unknown prefix is an error to help catching typos.
        """
        parts = id_start.split(".")
        try:
            parts[0] = self.get(parts[0])
        except KeyError:
            raise errors.CommandError("{} is not a known test prefix alias".format(parts[0]))
        return ".".join(parts)


test_prefix_alias_registry = TestPrefixAliasRegistry()
"""Registry of test prefix aliases."""


# This alias allows to detect typos ('bzrlin.') by making all valid test ids
# appear prefixed ('breezy.' is "replaced" by 'breezy.').
test_prefix_alias_registry.register("breezy", "breezy")

# Obvious highest levels prefixes, feel free to add your own via a plugin
test_prefix_alias_registry.register("bd", "breezy.doc")
test_prefix_alias_registry.register("bu", "breezy.utils")
test_prefix_alias_registry.register("bt", "breezy.tests")
test_prefix_alias_registry.register("bgt", "breezy.git.tests")
test_prefix_alias_registry.register("bbt", "breezy.bzr.tests")
test_prefix_alias_registry.register("bb", "breezy.tests.blackbox")
test_prefix_alias_registry.register("bp", "breezy.plugins")


def _test_suite_testmod_names():
    """Return the standard list of test module names to test."""
    return [
        "breezy.bzr.tests",
        "breezy.git.tests",
        "breezy.tests.blackbox",
        "breezy.tests.commands",
        "breezy.tests.per_branch",
        "breezy.tests.per_controldir",
        "breezy.tests.per_controldir_colo",
        "breezy.tests.per_foreign_vcs",
        "breezy.tests.per_interrepository",
        "breezy.tests.per_intertree",
        "breezy.tests.per_interbranch",
        "breezy.tests.per_lock",
        "breezy.tests.per_merger",
        "breezy.tests.per_transport",
        "breezy.tests.per_tree",
        "breezy.tests.per_repository",
        "breezy.tests.per_repository_reference",
        "breezy.tests.per_uifactory",
        "breezy.tests.per_workingtree",
        "breezy.tests.test__annotator",
        "breezy.tests.test__known_graph",
        "breezy.tests.test_ancestry",
        "breezy.tests.test_annotate",
        "breezy.tests.test_atomicfile",
        "breezy.tests.test_bad_files",
        "breezy.tests.test_bisect",
        "breezy.tests.test_bisect_multi",
        "breezy.tests.test_branch",
        "breezy.tests.test_branchbuilder",
        "breezy.tests.test_bugtracker",
        "breezy.tests.test__chunks_to_lines",
        "breezy.tests.test_cache_utf8",
        "breezy.tests.test_chunk_writer",
        "breezy.tests.test_clean_tree",
        "breezy.tests.test_cmdline",
        "breezy.tests.test_commands",
        "breezy.tests.test_commit",
        "breezy.tests.test_commit_merge",
        "breezy.tests.test_config",
        "breezy.tests.test_bedding",
        "breezy.tests.test_conflicts",
        "breezy.tests.test_controldir",
        "breezy.tests.test_counted_lock",
        "breezy.tests.test_crash",
        "breezy.tests.test_decorators",
        "breezy.tests.test_delta",
        "breezy.tests.test_debug",
        "breezy.tests.test_diff",
        "breezy.tests.test_directory_service",
        "breezy.tests.test_dirty_tracker",
        "breezy.tests.test_email_message",
        "breezy.tests.test_eol_filters",
        "breezy.tests.test_errors",
        "breezy.tests.test_estimate_compressed_size",
        "breezy.tests.test_export",
        "breezy.tests.test_export_pot",
        "breezy.tests.test_extract",
        "breezy.tests.test_features",
        "breezy.tests.test_fetch",
        "breezy.tests.test_fetch_ghosts",
        "breezy.tests.test_fixtures",
        "breezy.tests.test_fifo_cache",
        "breezy.tests.test_filters",
        "breezy.tests.test_filter_tree",
        "breezy.tests.test_foreign",
        "breezy.tests.test_forge",
        "breezy.tests.test_generate_docs",
        "breezy.tests.test_globbing",
        "breezy.tests.test_gpg",
        "breezy.tests.test_graph",
        "breezy.tests.test_grep",
        "breezy.tests.test_help",
        "breezy.tests.test_hooks",
        "breezy.tests.test_http",
        "breezy.tests.test_http_response",
        "breezy.tests.test_https_ca_bundle",
        "breezy.tests.test_https_urllib",
        "breezy.tests.test_i18n",
        "breezy.tests.test_identitymap",
        "breezy.tests.test_ignores",
        "breezy.tests.test_import_tariff",
        "breezy.tests.test_info",
        "breezy.tests.test_lazy_import",
        "breezy.tests.test_lazy_regex",
        "breezy.tests.test_library_state",
        "breezy.tests.test_location",
        "breezy.tests.test_lock",
        "breezy.tests.test_lockable_files",
        "breezy.tests.test_lockdir",
        "breezy.tests.test_log",
        "breezy.tests.test_lru_cache",
        "breezy.tests.test_lsprof",
        "breezy.tests.test_mail_client",
        "breezy.tests.test_matchers",
        "breezy.tests.test_memorybranch",
        "breezy.tests.test_memorytree",
        "breezy.tests.test_merge",
        "breezy.tests.test_mergeable",
        "breezy.tests.test_merge_core",
        "breezy.tests.test_merge_directive",
        "breezy.tests.test_mergetools",
        "breezy.tests.test_missing",
        "breezy.tests.test_msgeditor",
        "breezy.tests.test_multiparent",
        "breezy.tests.test_multiwalker",
        "breezy.tests.test_mutabletree",
        "breezy.tests.test_nonascii",
        "breezy.tests.test_options",
        "breezy.tests.test_osutils",
        "breezy.tests.test_osutils_encodings",
        "breezy.tests.test_patch",
        "breezy.tests.test_patches",
        "breezy.tests.test_permissions",
        "breezy.tests.test_plugins",
        "breezy.tests.test_progress",
        "breezy.tests.test_pyutils",
        "breezy.tests.test_reconcile",
        "breezy.tests.test_reconfigure",
        "breezy.tests.test_registry",
        "breezy.tests.test_rename_map",
        "breezy.tests.test_revert",
        "breezy.tests.test_revision",
        "breezy.tests.test_revisionspec",
        "breezy.tests.test_revisiontree",
        "breezy.tests.test_rules",
        "breezy.tests.test_url_policy_open",
        "breezy.tests.test_sampler",
        "breezy.tests.test_scenarios",
        "breezy.tests.test_script",
        "breezy.tests.test_selftest",
        "breezy.tests.test_setup",
        "breezy.tests.test_sftp_transport",
        "breezy.tests.test_shelf",
        "breezy.tests.test_shelf_ui",
        "breezy.tests.test_smart_add",
        "breezy.tests.test_smtp_connection",
        "breezy.tests.test_source",
        "breezy.tests.test_ssh_transport",
        "breezy.tests.test_status",
        "breezy.tests.test_strace",
        "breezy.tests.test_subsume",
        "breezy.tests.test_switch",
        "breezy.tests.test_symbol_versioning",
        "breezy.tests.test_tag",
        "breezy.tests.test_test_server",
        "breezy.tests.test_textfile",
        "breezy.tests.test_textmerge",
        "breezy.tests.test_cethread",
        "breezy.tests.test_timestamp",
        "breezy.tests.test_trace",
        "breezy.tests.test_transactions",
        "breezy.tests.test_transform",
        "breezy.tests.test_transport",
        "breezy.tests.test_transport_log",
        "breezy.tests.test_tree",
        "breezy.tests.test_treebuilder",
        "breezy.tests.test_treeshape",
        "breezy.tests.test_tsort",
        "breezy.tests.test_ui",
        "breezy.tests.test_uncommit",
        "breezy.tests.test_upgrade",
        "breezy.tests.test_upgrade_stacked",
        "breezy.tests.test_upstream_import",
        "breezy.tests.test_urlutils",
        "breezy.tests.test_utextwrap",
        "breezy.tests.test_version",
        "breezy.tests.test_version_info",
        "breezy.tests.test_views",
        "breezy.tests.test_whitebox",
        "breezy.tests.test_win32utils",
        "breezy.tests.test_workspace",
        "breezy.tests.test_workingtree",
        "breezy.tests.test_wsgi",
    ]


def _test_suite_modules_to_doctest():
    """Return the list of modules to doctest."""
    if __doc__ is None:
        # GZ 2009-03-31: No docstrings with -OO so there's nothing to doctest
        return []
    return [
        "breezy",
        "breezy.branchbuilder",
        "breezy.bzr.inventory",
        "breezy.decorators",
        "breezy.iterablefile",
        "breezy.lockdir",
        "breezy.option",
        "breezy.pyutils",
        "breezy.symbol_versioning",
        "breezy.tests",
        "breezy.tests.fixtures",
        "breezy.timestamp",
        "breezy.version_info_formats.format_custom",
    ]


def test_suite(keep_only=None, starting_with=None):
    """Build and return TestSuite for the whole of breezy.

    :param keep_only: A list of test ids limiting the suite returned.

    :param starting_with: An id limiting the suite returned to the tests
         starting with it.

    This function can be replaced if you need to change the default test
    suite on a global basis, but it is not encouraged.
    """
    loader = TestUtil.TestLoader()

    if keep_only is not None:
        id_filter = TestIdList(keep_only)
    if starting_with:
        # We take precedence over keep_only because *at loading time* using
        # both options means we will load less tests for the same final result.
        def interesting_module(name):
            for start in starting_with:
                # Either the module name starts with the specified string
                # or it may contain tests starting with the specified string
                if name.startswith(start) or start.startswith(name):
                    return True
            return False

        loader = TestUtil.FilteredByModuleTestLoader(interesting_module)

    elif keep_only is not None:
        loader = TestUtil.FilteredByModuleTestLoader(id_filter.refers_to)

        def interesting_module(name):
            return id_filter.refers_to(name)

    else:
        loader = TestUtil.TestLoader()

        def interesting_module(name):
            # No filtering, all modules are interesting
            return True

    suite = loader.suiteClass()

    # modules building their suite with loadTestsFromModuleNames
    suite.addTest(loader.loadTestsFromModuleNames(_test_suite_testmod_names()))

    suite.addTest(loader.loadTestsFromModuleNames(["breezy.doc"]))

    for mod in _test_suite_modules_to_doctest():
        if not interesting_module(mod):
            # No tests to keep here, move along
            continue
        try:
            # note that this really does mean "report only" -- doctest
            # still runs the rest of the examples
            doc_suite = IsolatedDocTestSuite(
                mod, optionflags=doctest.REPORT_ONLY_FIRST_FAILURE
            )
        except ValueError as e:
            print("**failed to get doctest for: {}\n{}".format(mod, e))
            raise
        if len(doc_suite._tests) == 0:
            raise errors.BzrError("no doctests found in {}".format(mod))
        suite.addTest(doc_suite)

    default_encoding = sys.getdefaultencoding()
    for name, plugin in _mod_plugin.plugins().items():
        if not interesting_module(plugin.module.__name__):
            continue
        plugin_suite = plugin.test_suite()
        # We used to catch ImportError here and turn it into just a warning,
        # but really if you don't have --no-plugins this should be a failure.
        # mbp 20080213 - see http://bugs.launchpad.net/bugs/189771
        if plugin_suite is None:
            plugin_suite = plugin.load_plugin_tests(loader)
        if plugin_suite is not None:
            suite.addTest(plugin_suite)
        if default_encoding != sys.getdefaultencoding():
            trace.warning(
                'Plugin "%s" tried to reset default encoding to: %s',
                name,
                sys.getdefaultencoding(),
            )
            reload(sys)
            sys.setdefaultencoding(default_encoding)

    if keep_only is not None:
        # Now that the referred modules have loaded their tests, keep only the
        # requested ones.
        suite = filter_suite_by_id_list(suite, id_filter)
        # Do some sanity checks on the id_list filtering
        not_found, duplicates = suite_matches_id_list(suite, keep_only)
        if starting_with:
            # The tester has used both keep_only and starting_with, so he is
            # already aware that some tests are excluded from the list, there
            # is no need to tell him which.
            pass
        else:
            # Some tests mentioned in the list are not in the test suite. The
            # list may be out of date, report to the tester.
            for id in not_found:
                trace.warning('"%s" not found in the test suite', id)
        for id in duplicates:
            trace.warning('"%s" is used as an id by several tests', id)

    return suite


def multiply_scenarios(*scenarios):
    """Multiply two or more iterables of scenarios.

    It is safe to pass scenario generators or iterators.

    :returns: A list of compound scenarios: the cross-product of all
        scenarios, with the names concatenated and the parameters
        merged together.
    """
    return functools.reduce(_multiply_two_scenarios, map(list, scenarios))


def _multiply_two_scenarios(scenarios_left, scenarios_right):
    """Multiply two sets of scenarios.

    :returns: the cartesian product of the two sets of scenarios, that is
        a scenario for every possible combination of a left scenario and a
        right scenario.
    """
    return [
        ("{},{}".format(left_name, right_name), dict(left_dict, **right_dict))
        for left_name, left_dict in scenarios_left
        for right_name, right_dict in scenarios_right
    ]


def multiply_tests(tests, scenarios, result):
    """Multiply tests_list by scenarios into result.

    This is the core workhorse for test parameterisation.

    Typically the load_tests() method for a per-implementation test suite will
    call multiply_tests and return the result.

    :param tests: The tests to parameterise.
    :param scenarios: The scenarios to apply: pairs of (scenario_name,
        scenario_param_dict).
    :param result: A TestSuite to add created tests to.

    This returns the passed in result TestSuite with the cross product of all
    the tests repeated once for each scenario.  Each test is adapted by adding
    the scenario name at the end of its id(), and updating the test object's
    __dict__ with the scenario_param_dict.

    >>> import breezy.tests.test_sampler
    >>> r = multiply_tests(
    ...     breezy.tests.test_sampler.DemoTest('test_nothing'),
    ...     [('one', dict(param=1)),
    ...      ('two', dict(param=2))],
    ...     TestUtil.TestSuite())
    >>> tests = list(iter_suite_tests(r))
    >>> len(tests)
    2
    >>> tests[0].id()
    'breezy.tests.test_sampler.DemoTest.test_nothing(one)'
    >>> tests[0].param
    1
    >>> tests[1].param
    2
    """
    for test in iter_suite_tests(tests):
        apply_scenarios(test, scenarios, result)
    return result


def apply_scenarios(test, scenarios, result):
    """Apply the scenarios in scenarios to test and add to result.

    :param test: The test to apply scenarios to.
    :param scenarios: An iterable of scenarios to apply to test.
    :return: result
    :seealso: apply_scenario
    """
    for scenario in scenarios:
        result.addTest(apply_scenario(test, scenario))
    return result


def apply_scenario(test, scenario):
    """Copy test and apply scenario to it.

    :param test: A test to adapt.
    :param scenario: A tuple describing the scenario.
        The first element of the tuple is the new test id.
        The second element is a dict containing attributes to set on the
        test.
    :return: The adapted test.
    """
    new_id = "{}({})".format(test.id(), scenario[0])
    new_test = clone_test(test, new_id)
    for name, value in scenario[1].items():
        setattr(new_test, name, value)
    return new_test


def clone_test(test, new_id):
    """Clone a test giving it a new id.

    :param test: The test to clone.
    :param new_id: The id to assign to it.
    :return: The new test.
    """
    new_test = copy.copy(test)
    new_test.id = lambda: new_id
    # XXX: Workaround <https://bugs.launchpad.net/testtools/+bug/637725>, which
    # causes cloned tests to share the 'details' dict.  This makes it hard to
    # read the test output for parameterized tests, because tracebacks will be
    # associated with irrelevant tests.
    try:
        pass
    except AttributeError:
        # must be a different version of testtools than expected.  Do nothing.
        pass
    else:
        # Reset the '__details' dict.
        new_test._TestCase__details = {}
    return new_test


def permute_tests_for_extension(
    standard_tests, loader, py_module_name, ext_module_name
):
    """Helper for permutating tests against an extension module.

    This is meant to be used inside a modules 'load_tests()' function. It will
    create 2 scenarios, and cause all tests in the 'standard_tests' to be run
    against both implementations. Setting 'test.module' to the appropriate
    module. See breezy.tests.test__chk_map.load_tests as an example.

    :param standard_tests: A test suite to permute
    :param loader: A TestLoader
    :param py_module_name: The python path to a python module that can always
        be loaded, and will be considered the 'python' implementation. (eg
        'breezy._chk_map_py')
    :param ext_module_name: The python path to an extension module. If the
        module cannot be loaded, a single test will be added, which notes that
        the module is not available. If it can be loaded, all standard_tests
        will be run against that module.
    :return: (suite, feature) suite is a test-suite that has all the permuted
        tests. feature is the Feature object that can be used to determine if
        the module is available.
    """
    from .features import ModuleAvailableFeature

    py_module = pyutils.get_named_object(py_module_name)
    scenarios = [
        ("python", {"module": py_module}),
    ]
    suite = loader.suiteClass()
    feature = ModuleAvailableFeature(ext_module_name)
    if feature.available():
        scenarios.append(("C", {"module": feature.module}))
    else:

        class FailWithoutFeature(TestCase):
            def id(self):
                return ext_module_name + "." + super().id()

            def test_fail(self):
                self.requireFeature(feature)

        # the compiled module isn't available, so we add a failing test
        suite.addTest(loader.loadTestsFromTestCase(FailWithoutFeature))
    result = multiply_tests(standard_tests, scenarios, suite)
    return result, feature


def _rmtree_temp_dir(dirname, test_id=None):
    # If LANG=C we probably have created some bogus paths
    # which rmtree(unicode) will fail to delete
    # so make sure we are using rmtree(str) to delete everything
    # except on win32, where rmtree(str) will fail
    # since it doesn't have the property of byte-stream paths
    # (they are either ascii or mbcs)
    if sys.platform == "win32" and isinstance(dirname, bytes):
        # make sure we are using the unicode win32 api
        dirname = dirname.decode("mbcs")
    else:
        dirname = dirname.encode(sys.getfilesystemencoding())
    try:
        osutils.rmtree(dirname)
    except OSError as e:
        # We don't want to fail here because some useful display will be lost
        # otherwise. Polluting the tmp dir is bad, but not giving all the
        # possible info to the test runner is even worse.
        if test_id is not None:
            ui.ui_factory.clear_term()
            sys.stderr.write("\nWhile running: {}\n".format(test_id))
        # Ugly, but the last thing we want here is fail, so bear with it.
        printable_e = (
            str(e)
            .decode(osutils.get_user_encoding(), "replace")
            .encode("ascii", "replace")
        )
        sys.stderr.write(
            "Unable to remove testing dir {}\n{}".format(os.path.basename(dirname), printable_e)
        )


def probe_unicode_in_user_encoding():
    """Try to encode several unicode strings to use in unicode-aware tests.
    Return first successfull match.

    :return:  (unicode value, encoded plain string value) or (None, None)
    """
    possible_vals = ["m\xb5", "\xe1", "\u0410"]
    for uni_val in possible_vals:
        try:
            str_val = uni_val.encode(osutils.get_user_encoding())
        except UnicodeEncodeError:
            # Try a different character
            pass
        else:
            return uni_val, str_val
    return None, None


def probe_bad_non_ascii(encoding):
    """Try to find [bad] character with code [128..255]
    that cannot be decoded to unicode in some encoding.
    Return None if all non-ascii characters is valid
    for given encoding.
    """
    for i in range(128, 256):
        char = bytes([i])
        try:
            char.decode(encoding)
        except UnicodeDecodeError:
            return char
    return None


# Only define SubUnitBzrRunner if subunit is available.
try:
    from subunit import TestProtocolClient
    from subunit.test_results import AutoTimingTestResultDecorator

    class SubUnitBzrProtocolClientv1(TestProtocolClient):
        def stopTest(self, test):
            super().stopTest(test)
            _clear__type_equality_funcs(test)

        def addSuccess(self, test, details=None):
            # The subunit client always includes the details in the subunit
            # stream, but we don't want to include it in ours.
            if details is not None and "log" in details:
                del details["log"]
            return super().addSuccess(test, details)

    class SubUnitBzrRunnerv1(TextTestRunner):
        def run(self, test):
            result = AutoTimingTestResultDecorator(
                SubUnitBzrProtocolClientv1(self.stream)
            )
            test.run(result)
            return result
except ModuleNotFoundError:
    pass


try:
    from subunit.run import SubunitTestRunner

    class SubUnitBzrRunnerv2(TextTestRunner, SubunitTestRunner):
        def __init__(
            self,
            stream=sys.stderr,
            descriptions=0,
            verbosity=1,
            bench_history=None,
            strict=False,
            result_decorators=None,
        ):
            TextTestRunner.__init__(
                self,
                stream=stream,
                descriptions=descriptions,
                verbosity=verbosity,
                bench_history=bench_history,
                strict=strict,
                result_decorators=result_decorators,
            )
            SubunitTestRunner.__init__(self, verbosity=verbosity, stream=stream)

        run = SubunitTestRunner.run
except ModuleNotFoundError:
    pass
