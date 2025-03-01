# Copyright (C) 2019 Breezy Developers
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

import os
from typing import List

from .. import forge as _mod_forge
from .. import registry, tests, urlutils
from ..forge import (
    Forge,
    MergeProposal,
    UnsupportedForge,
    determine_title,
    get_forge,
    get_proposal_by_url,
)


class SampleMergeProposal(MergeProposal):
    """Sample merge proposal."""


class SampleForge(Forge):
    _locations: List[str] = []

    @classmethod
    def _add_location(cls, url):
        cls._locations.append(url)

    @classmethod
    def probe_from_url(cls, url, possible_transports=None):
        for b in cls._locations:
            if url.startswith(b):
                return cls()
        raise UnsupportedForge(url)

    def hosts(self, branch):
        return any(branch.user_url.startswith(b) for b in self._locations)

    @classmethod
    def iter_instances(cls):
        return iter([cls()])

    def get_proposal_by_url(self, url):
        for b in self._locations:
            if url.startswith(b):
                return MergeProposal()
        raise UnsupportedForge(url)


class SampleForgeTestCase(tests.TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self._old_forges = _mod_forge.forges
        _mod_forge.forges = registry.Registry()
        self.forge = SampleForge()
        os.mkdir("hosted")
        SampleForge._add_location(
            urlutils.local_path_to_url(os.path.join(self.test_dir, "hosted"))
        )
        _mod_forge.forges.register("sample", self.forge)

    def tearDown(self):
        super().tearDown()
        _mod_forge.forges = self._old_forges
        SampleForge._locations = []


class TestGetForgeTests(SampleForgeTestCase):
    def test_get_forge(self):
        tree = self.make_branch_and_tree("hosted/branch")
        self.assertIs(self.forge, get_forge(tree.branch, [self.forge]))
        self.assertIsInstance(get_forge(tree.branch), SampleForge)

        tree = self.make_branch_and_tree("blah")
        self.assertRaises(UnsupportedForge, get_forge, tree.branch)


class TestGetProposal(SampleForgeTestCase):
    def test_get_proposal_by_url(self):
        self.assertRaises(UnsupportedForge, get_proposal_by_url, "blah")

        url = urlutils.local_path_to_url(
            os.path.join(self.test_dir, "hosted", "proposal")
        )
        self.assertIsInstance(get_proposal_by_url(url), MergeProposal)


class DetermineTitleTests(tests.TestCase):
    def test_determine_title(self):
        self.assertEqual(
            "Make some change",
            determine_title("""\
Make some change.

And here are some more details.
"""),
        )
        self.assertEqual(
            "Make some change",
            determine_title("""\
Make some change. And another one.

With details.
"""),
        )
        self.assertEqual(
            "Release version 5.1",
            determine_title("""\
Release version 5.1

And here are some more details.
"""),
        )
        self.assertEqual(
            "Release version 5.1",
            determine_title("""\

Release version 5.1

And here are some more details.
"""),
        )
