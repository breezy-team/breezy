# Copyright (C) 2006 Canonical Ltd
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

"""Blackbox tests for the 'brz testament' command."""

import re

from breezy.bzr.tests.test_testament import (
    REV_1_SHORT,
    REV_1_SHORT_STRICT,
    REV_2_TESTAMENT,
    TestamentSetup,
    osutils,
)


class TestTestament(TestamentSetup):
    """Run blackbox tests on 'brz testament'."""

    def test_testament_command(self):
        """Testament containing a file and a directory."""
        out, err = self.run_bzr("testament --long")
        self.assertEqualDiff(err, "")
        self.assertEqualDiff(out, REV_2_TESTAMENT.decode("ascii"))

    def test_testament_command_2(self):
        """Command getting short testament of previous version."""
        out, err = self.run_bzr("testament -r1")
        self.assertEqualDiff(err, "")
        self.assertEqualDiff(out, REV_1_SHORT.decode("ascii"))

    def test_testament_command_3(self):
        """Command getting short testament of previous version."""
        out, err = self.run_bzr("testament -r1 --strict")
        self.assertEqualDiff(err, "")
        self.assertEqualDiff(out, REV_1_SHORT_STRICT.decode("ascii"))

    def test_testament_non_ascii(self):
        self.wt.commit("Non \xe5ssci message")
        long_out, err = self.run_bzr_raw("testament --long", encoding="utf-8")
        self.assertEqualDiff(err, b"")
        long_out, err = self.run_bzr_raw("testament --long", encoding="ascii")
        short_out, err = self.run_bzr_raw("testament", encoding="ascii")
        self.assertEqualDiff(err, b"")
        sha1_re = re.compile(b"sha1: (?P<sha1>[a-f0-9]+)$", re.M)
        sha1 = sha1_re.search(short_out).group("sha1")
        self.assertEqual(sha1, osutils.sha_string(long_out))
