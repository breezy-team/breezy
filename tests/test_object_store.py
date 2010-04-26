# Copyright (C) 2010 Jelmer Vernooij <jelmer@samba.org>
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

"""Tests for bzr-git's object store."""

from dulwich.objects import (
    Blob,
    )

from bzrlib.graph import (
    DictParentsProvider,
    )
from bzrlib.tests import (
    TestCase,
    )

from bzrlib.plugins.git.object_store import (
    _check_expected_sha,
    _find_missing_bzr_revids,
    )


class ExpectedShaTests(TestCase):

    def setUp(self):
        super(ExpectedShaTests, self).setUp()
        self.obj = Blob()
        self.obj.data = "foo"

    def test_none(self):
        _check_expected_sha(None, self.obj)

    def test_hex(self):
        _check_expected_sha(self.obj.sha().hexdigest(), self.obj)
        self.assertRaises(AssertionError, _check_expected_sha, 
            "0" * 40, self.obj)

    def test_binary(self):
        _check_expected_sha(self.obj.sha().digest(), self.obj)
        self.assertRaises(AssertionError, _check_expected_sha, 
            "x" * 20, self.obj)


class FindMissingBzrRevidsTests(TestCase):

    def _find_missing(self, ancestry, want, have):
        return _find_missing_bzr_revids(
            DictParentsProvider(ancestry).get_parent_map,
            set(want), set(have))

    def test_simple(self):
        self.assertEquals(set(), self._find_missing({}, [], []))

    def test_up_to_date(self):
        self.assertEquals(set(),
                self._find_missing({"a": ["b"]}, ["a"], ["a"]))

    def test_one_missing(self):
        self.assertEquals(set(["a"]),
                self._find_missing({"a": ["b"]}, ["a"], ["b"]))
