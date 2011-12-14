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


import cPickle
import threading

import bzrlib
from bzrlib import errors, tests
from bzrlib.tests import (
    features,
    )


_TXT_HEADER = "   CallCount    Recursive    Total(ms)   " + \
    "Inline(ms) module:lineno(function)\n"


def _junk_callable():
    "A simple routine to profile."
    result = sorted(['abc', 'def', 'ghi'])


def _collect_stats():
    "Collect and return some dummy profile data."
    from bzrlib.lsprof import profile
    ret, stats = profile(_junk_callable)
    return stats


class TestStatsSave(tests.TestCaseInTempDir):

    _test_needs_features = [features.lsprof_feature]

    def setUp(self):
        super(tests.TestCaseInTempDir, self).setUp()
        self.stats = _collect_stats()

    def _tempfile(self, ext):
        dir = self.test_dir
        return bzrlib.osutils.pathjoin(dir, "tmp_profile_data." + ext)

    def test_stats_save_to_txt(self):
        f = self._tempfile("txt")
        self.stats.save(f)
        lines = open(f).readlines()
        self.assertEqual(lines[0], _TXT_HEADER)

    def test_stats_save_to_callgrind(self):
        f = self._tempfile("callgrind")
        self.stats.save(f)
        lines = open(f).readlines()
        self.assertEqual(lines[0], "events: Ticks\n")
        f = bzrlib.osutils.pathjoin(self.test_dir, "callgrind.out.foo")
        self.stats.save(f)
        lines = open(f).readlines()
        self.assertEqual(lines[0], "events: Ticks\n")
        # Test explicit format nommination
        f2 = self._tempfile("txt")
        self.stats.save(f2, format="callgrind")
        lines2 = open(f2).readlines()
        self.assertEqual(lines2[0], "events: Ticks\n")

    def test_stats_save_to_pickle(self):
        f = self._tempfile("pkl")
        self.stats.save(f)
        data1 = cPickle.load(open(f))
        self.assertEqual(type(data1), bzrlib.lsprof.Stats)


class TestBzrProfiler(tests.TestCase):

    _test_needs_features = [features.lsprof_feature]

    def test_start_call_stuff_stop(self):
        profiler = bzrlib.lsprof.BzrProfiler()
        profiler.start()
        try:
            def a_function():
                pass
            a_function()
        finally:
            stats = profiler.stop()
        stats.freeze()
        lines = [str(data) for data in stats.data]
        lines = [line for line in lines if 'a_function' in line]
        self.assertLength(1, lines)

    def test_block_0(self):
        # When profiler_block is 0, reentrant profile requests fail.
        self.overrideAttr(bzrlib.lsprof.BzrProfiler, 'profiler_block', 0)
        inner_calls = []
        def inner():
            profiler = bzrlib.lsprof.BzrProfiler()
            self.assertRaises(errors.BzrError, profiler.start)
            inner_calls.append(True)
        bzrlib.lsprof.profile(inner)
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
            calls.append('profiled')
        def do_profile():
            bzrlib.lsprof.profile(profiled)
            calls.append('after_profiled')
        thread = threading.Thread(target=do_profile)
        bzrlib.lsprof.BzrProfiler.profiler_lock.acquire()
        try:
            try:
                thread.start()
            finally:
                bzrlib.lsprof.BzrProfiler.profiler_lock.release()
        finally:
            thread.join()
        self.assertLength(2, calls)
