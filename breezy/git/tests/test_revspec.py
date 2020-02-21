# Copyright (C) 2010-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Test the git revision specifiers."""

from ...tests import TestCase

from ..revspec import (
    valid_git_sha1,
    )


class Sha1ValidTests(TestCase):

    def test_invalid(self):
        self.assertFalse(valid_git_sha1(b"git-v1:abcde"))

    def test_valid(self):
        self.assertTrue(valid_git_sha1(b"aabbccddee"))
        self.assertTrue(valid_git_sha1(b"aabbccd"))
