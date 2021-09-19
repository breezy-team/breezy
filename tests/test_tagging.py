# Copyright (C) 2010 Canonical Limited
# vim: ts=4 sts=4 sw=4
#
# This file is part of bzr-builddeb.
#
# bzr-builddeb is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# bzr-builddeb is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with bzr-builddeb; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

"""Tests for builddeb.tagging."""

from .. import tagging
from ....tests import (
    TestCase,
    )


class TestDebVersionSort(TestCase):

    def test_sort(self):
        tags = [("1.0", "revid"), ("1.0.1", "revid"), ("1.0~1", "revid")]
        tagging.sort_debversion(None, tags)
        self.assertEquals(
            tags,
            [("1.0~1", "revid"), ("1.0", "revid"), ("1.0.1", "revid")])
