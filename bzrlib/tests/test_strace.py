# Copyright (C) 2007 Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

"""Tests for the strace-invoking support."""

import subprocess

from bzrlib.strace import StraceFeature, strace, StraceResult
from bzrlib.tests import TestCaseWithTransport


class TestStraceFeature(TestCaseWithTransport):

    def test_strace_detection(self):
        """Strace is available if its runnable."""
        try:
            proc = subprocess.Popen(['strace'],
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE)
            proc.communicate()
            found_strace = True
        except OSError, e:
            if e.errno == errno.ENOENT:
                # strace is not installed
                found_strace = False
            else:
                raise
        self.assertEqual(found_strace, StraceFeature.available())


class TestStrace(TestCaseWithTransport):

    _test_needs_features = [StraceFeature]

    def test_strace_callable_is_called(self):
        output = []
        def function(positional, *args, **kwargs):
            output.append((positional, args, kwargs))
        strace(function, "a", "b", c="c")
        self.assertEqual([("a", ("b",), {"c":"c"})], output)

    def test_strace_callable_result(self):
        def function():
            return "foo"
        result, strace_result = strace(function)
        self.assertEqual("foo", result)
        self.assertIsInstance(strace_result, StraceResult)

    def test_strace_result_has_raw_log(self):
        """Checks that a reasonable raw strace log was found by strace."""
        def function():
            self.build_tree(['myfile'])
        _, result = strace(function)
        self.assertContainsRe(result.raw_log, 'myfile')
