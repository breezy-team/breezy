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

"""Tests for profiling data collection."""


import cPickle
import os

import bzrlib
from bzrlib.lsprof import profile
from bzrlib.tests import TestCaseInTempDir


_TXT_HEADER = "   CallCount    Recursive    Total(ms)   " + \
    "Inline(ms) module:lineno(function)\n"


def _junk_callable():
    "A simple routine to profile."
    result = sorted(['abc', 'def', 'ghi'])


def _collect_stats():
    "Collect and return some dummy profile data."
    ret, stats = profile(_junk_callable)
    return stats


class TestStatsSave(TestCaseInTempDir):

    def setUp(self):
        super(TestCaseInTempDir, self).setUp()
        self.stats = _collect_stats()

    def _tempfile(self, ext):
        dir = self.test_dir
        return os.path.join(dir, "tmp_profile_data." + ext)

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
