# Copyright (C) 2007, 2009, 2010, 2011 Canonical Ltd
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

"""Tests for profiling data collection."""

import pickle
import threading

from .. import errors, osutils, tests
from ..tests import features

lsprof = features.lsprof_feature.module


_TXT_HEADER = (
    "   CallCount    Recursive    Total(ms)   " + "Inline(ms) module:lineno(function)\n"
)


def _junk_callable():
    """A simple routine to profile."""
    sorted(["abc", "def", "ghi"])


def _collect_stats():
    """Collect and return some dummy profile data."""
    ret, stats = lsprof.profile(_junk_callable)
    return stats


class TestStats(tests.TestCaseInTempDir):
    _test_needs_features = [features.lsprof_feature]

    def setUp(self):
        super(tests.TestCaseInTempDir, self).setUp()
        self.stats = _collect_stats()

    def _temppath(self, ext):
        return osutils.pathjoin(self.test_dir, "tmp_profile_data." + ext)

    def test_save_to_txt(self):
        path = self._temppath("txt")
        self.stats.save(path)
        with open(path) as f:
            lines = f.readlines()
            self.assertEqual(lines[0], _TXT_HEADER)

    def test_save_to_callgrind(self):
        path1 = self._temppath("callgrind")
        self.stats.save(path1)
        with open(path1) as f:
            self.assertEqual(f.readline(), "events: Ticks\n")

        path2 = osutils.pathjoin(self.test_dir, "callgrind.out.foo")
        self.stats.save(path2)
        with open(path2) as f:
            self.assertEqual(f.readline(), "events: Ticks\n")

        # Test explicit format nommination
        path3 = self._temppath("txt")
        self.stats.save(path3, format="callgrind")
        with open(path3) as f:
            self.assertEqual(f.readline(), "events: Ticks\n")

    def test_save_to_pickle(self):
        path = self._temppath("pkl")
        self.stats.save(path)
        with open(path, "rb") as f:
            data1 = pickle.load(f)  # noqa: S301
            self.assertEqual(type(data1), lsprof.Stats)

    def test_sort(self):
        self.stats.sort()
        code_list = [d.inlinetime for d in self.stats.data]
        self.assertEqual(code_list, sorted(code_list, reverse=True))

    def test_sort_totaltime(self):
        self.stats.sort("totaltime")
        code_list = [d.totaltime for d in self.stats.data]
        self.assertEqual(code_list, sorted(code_list, reverse=True))

    def test_sort_code(self):
        """Cannot sort by code object would need to get filename etc."""
        self.assertRaises(ValueError, self.stats.sort, "code")


class TestBzrProfiler(tests.TestCase):
    _test_needs_features = [features.lsprof_feature]

    def test_start_call_stuff_stop(self):
        profiler = lsprof.BzrProfiler()
        profiler.start()
        try:

            def a_function():
                pass

            a_function()
        finally:
            stats = profiler.stop()
        stats.freeze()
        lines = [str(data) for data in stats.data]
        lines = [line for line in lines if "a_function" in line]
        self.assertLength(1, lines)

    def test_block_0(self):
        # When profiler_block is 0, reentrant profile requests fail.
        self.overrideAttr(lsprof.BzrProfiler, "profiler_block", 0)
        inner_calls = []

        def inner():
            profiler = lsprof.BzrProfiler()
            self.assertRaises(errors.BzrError, profiler.start)
            inner_calls.append(True)

        lsprof.profile(inner)
        self.assertLength(1, inner_calls)

    def test_block_1(self):
        # When profiler_block is 1, concurrent profiles serialise.
        # This is tested by manually acquiring the profiler lock, then
        # starting a thread that tries to profile, and releasing the lock.
        # We know due to test_block_0 that two profiles at once hit the lock,
        # so while this isn't perfect (we'd want a callback on the lock being
        # entered to allow lockstep evaluation of the actions), its good enough
        # to be confident regressions would be caught. Alternatively, if this
        # is flakey, a fake Lock object can be used to trace the calls made.
        calls = []

        def profiled():
            calls.append("profiled")

        def do_profile():
            lsprof.profile(profiled)
            calls.append("after_profiled")

        thread = threading.Thread(target=do_profile)
        lsprof.BzrProfiler.profiler_lock.acquire()
        try:
            try:
                thread.start()
            finally:
                lsprof.BzrProfiler.profiler_lock.release()
        finally:
            thread.join()
        self.assertLength(2, calls)
