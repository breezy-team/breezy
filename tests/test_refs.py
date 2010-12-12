# Copyright (C) 2010 Jelmer Vernooij
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Tests for ref handling."""

from bzrlib import tests

from bzrlib.plugins.git import refs


class BranchNameRefConversionTests(tests.TestCase):

    def test_head(self):
        self.assertEquals("HEAD", refs.ref_to_branch_name("HEAD"))
        self.assertEquals("HEAD", refs.branch_name_to_ref("HEAD"))
        self.assertEquals(None, refs.branch_name_to_ref(None))

    def test_tag(self):
        self.assertRaises(ValueError, refs.ref_to_branch_name, "refs/tags/FOO")

    def test_branch(self):
        self.assertEquals("frost", refs.ref_to_branch_name("refs/heads/frost"))
        self.assertEquals("refs/heads/frost", refs.branch_name_to_ref("frost"))

    def test_default(self):
        self.assertEquals("mydefault",
            refs.branch_name_to_ref(None, "mydefault"))
        self.assertEquals(None,
            refs.branch_name_to_ref(None))


class ExtractTagTests(tests.TestCase):

    def test_ignore_branch(self):
        self.assertEquals({},
            refs.extract_tags({
                "HEAD": "ref: foo", "refs/branches/blala": "la"}))

    def test_tags(self):
        self.assertEquals({"mytag": ("mysha", None)},
            refs.extract_tags({
                "HEAD": "ref: foo", "refs/tags/mytag": "mysha"}))

    def test_ignores_peels(self):
        self.assertEquals({"mytag": ("actualsha", "mysha")},
            refs.extract_tags({
                "HEAD": "ref: foo",
                "refs/tags/mytag": "mysha",
                "refs/tags/mytag^{}": "actualsha"}))

    def test_non_ascii_name(self):
        self.assertEquals({u'myt\xe2g': ("actualsha", None)},
            refs.extract_tags({
                "HEAD": "ref: foo",
                "refs/tags/myt\xc3\xa2g": "actualsha"}))

    def test_non_utf8_name(self):
        self.assertEquals({},
            refs.extract_tags({
                'refs/tags/LIBGEE_0_2_\xc20': "actualsha"}))
