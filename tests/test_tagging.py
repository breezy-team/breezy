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

"""Tests for bzrlib.plugins.builddeb.tagging."""

from bzrlib.plugins.builddeb import tagging
from bzrlib.tests import (
    TestCase,
    )


class TestIsUpstreamTag(TestCase):

    def test_plain_version(self):
        self.assertFalse(tagging.is_upstream_tag('2.1'))

    def test_simple_upstream(self):
        self.assertTrue(tagging.is_upstream_tag('upstream-2.1'))

    def test_distro_upstream(self):
        self.assertTrue(tagging.is_upstream_tag('upstream-debian-2.1'))

    def test_git_upstream(self):
        self.assertTrue(tagging.is_upstream_tag('upstream/2.1'))


class TestUpstreamTagVersion(TestCase):

    def test_simple_upstream(self):
        self.assertEqual('2.1', tagging.upstream_tag_version('upstream-2.1'))

    def test_distro_upstream(self):
        self.assertEqual('2.1',
            tagging.upstream_tag_version('upstream-debian-2.1'))

    def test_git_upstream(self):
        self.assertEqual('2.1', tagging.upstream_tag_version('upstream/2.1'))


class TestDebVersionSort(TestCase):

    def test_sort(self):
        tags = [("1.0", "revid"), ("1.0.1", "revid"), ("1.0~1", "revid")]
        tagging.sort_debversion(None, tags)
        self.assertEquals(tags,
            [("1.0~1", "revid"), ("1.0", "revid"), ("1.0.1", "revid")])
