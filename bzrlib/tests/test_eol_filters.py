# Copyright (C) 2009 Canonical Ltd
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

"""Tests for eol conversion."""


from bzrlib.filters.eol import (
    _to_crlf_converter,
    _to_lf_converter,
    )
from bzrlib.tests import TestCase


# Sample files
_sample_file1 = """hello\nworld\r\n"""


class TestEolFilters(TestCase):

    def test_to_lf(self):
        result = _to_lf_converter([_sample_file1])
        self.assertEqual(["hello\nworld\n"], result)

    def test_to_crlf(self):
        result = _to_crlf_converter([_sample_file1])
        self.assertEqual(["hello\r\nworld\r\n"], result)
