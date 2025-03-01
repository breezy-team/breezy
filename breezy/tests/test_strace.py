# Copyright (C) 2007-2011 Canonical Ltd
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

"""Tests for the strace-invoking support."""

import threading

from breezy import strace, tests
from breezy.strace import StraceResult, strace_detailed
from breezy.tests.features import strace_feature


class TestStrace(tests.TestCaseWithTransport):
    _test_needs_features = [strace_feature]

    def setUp(self):
        # NB: see http://pad.lv/626679 and
        # <https://code.launchpad.net/~mbp/bzr/626679-strace/+merge/34157>:
        # testing strace by connecting to ourselves has repeatedly caused
        # hangs in running the test suite; these are fixable given enough
        # determination but given that strace is not used by any other tests
        # at the moment and that it's only test-support code, we just leave it
        # untested -- mbp 20100901
        raise tests.TestSkipped("strace selftests are broken and disabled")

    def _check_threads(self):
        # For bug #226769, it was decided that the strace tests should not be
        # run when more than one thread is active. A lot of tests are currently
        # leaking threads for good or bad reasons, once they are fixed or
        # strace itself is fixed (bug #103133), we can get rid of the
        # restriction.
        active = threading.activeCount()
        if active > 1:  # There is always the main thread at least
            self.knownFailure(
                "%d active threads, bug #103133 needs to be fixed." % active
            )

    def strace_detailed_or_skip(self, *args, **kwargs):
        """Run strace, but cope if it's not allowed."""
        try:
            return strace_detailed(*args, **kwargs)
        except strace.StraceError as e:
            if e.err_messages.startswith(
                "attach: ptrace(PTRACE_ATTACH, ...): Operation not permitted"
            ):
                raise tests.TestSkipped("ptrace not permitted")
            else:
                raise

    def test_strace_callable_is_called(self):
        self._check_threads()

        output = []

        def function(positional, *args, **kwargs):
            output.append((positional, args, kwargs))

        self.strace_detailed_or_skip(
            function, ["a", "b"], {"c": "c"}, follow_children=False
        )
        self.assertEqual([("a", ("b",), {"c": "c"})], output)

    def test_strace_callable_result(self):
        self._check_threads()

        def function():
            return "foo"

        result, strace_result = self.strace_detailed_or_skip(
            function, [], {}, follow_children=False
        )
        self.assertEqual("foo", result)
        self.assertIsInstance(strace_result, StraceResult)

    def test_strace_result_has_raw_log(self):
        """Checks that a reasonable raw strace log was found by strace."""
        self._check_threads()

        def function():
            self.build_tree(["myfile"])

        unused, result = self.strace_detailed_or_skip(
            function, [], {}, follow_children=False
        )
        self.assertContainsRe(result.raw_log, "myfile")
