# Copyright (C) 2010-2018 Jelmer Vernooij <jelmer@jelmer.uk>
# vim: encoding=utf-8
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


"""Tests for ref handling."""

from .... import tests

from ...git import refs


class BranchNameRefConversionTests(tests.TestCase):

    def test_head(self):
        self.assertEquals("", refs.ref_to_branch_name("HEAD"))
        self.assertEquals("HEAD", refs.branch_name_to_ref(""))

    def test_tag(self):
        self.assertRaises(ValueError, refs.ref_to_branch_name, "refs/tags/FOO")

    def test_branch(self):
        self.assertEquals("frost", refs.ref_to_branch_name("refs/heads/frost"))
        self.assertEquals("refs/heads/frost", refs.branch_name_to_ref("frost"))
