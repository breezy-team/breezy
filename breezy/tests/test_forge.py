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

from .. import forge as _mod_forge
from .. import registry, tests, urlutils
from ..forge import (
    Forge,
    MergeProposal,
    UnsupportedForge,
    api_base_url,
    determine_title,
    get_forge,
    get_proposal_by_url,
)
from ..transport import get_transport


class SampleMergeProposal(MergeProposal):
    """Sample merge proposal."""


class SampleForge(Forge):
    _locations: list[str] = []

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
            determine_title(
                """\
Make some change.

And here are some more details.
"""
            ),
        )
        self.assertEqual(
            "Make some change",
            determine_title(
                """\
Make some change. And another one.

With details.
"""
            ),
        )
        self.assertEqual(
            "Release version 5.1",
            determine_title(
                """\
Release version 5.1

And here are some more details.
"""
            ),
        )
        self.assertEqual(
            "Release version 5.1",
            determine_title(
                """\

Release version 5.1

And here are some more details.
"""
            ),
        )


class ApiBaseUrlTests(tests.TestCase):
    def test_https_default_port(self):
        self.assertEqual(
            "https://gitlab.com/", api_base_url("https://gitlab.com/jelmer/example")
        )

    def test_http_keeps_scheme_and_port(self):
        self.assertEqual(
            "http://forge.example.com:3000/",
            api_base_url("http://forge.example.com:3000/jelmer/example"),
        )

    def test_https_keeps_non_default_port(self):
        self.assertEqual(
            "https://forge.example.com:8443/",
            api_base_url("https://forge.example.com:8443/jelmer/example"),
        )

    def test_explicit_default_port_dropped(self):
        # A token stored against the port-less URL must still match.
        self.assertEqual(
            "https://forge.example.com/",
            api_base_url("https://forge.example.com:443/jelmer/example"),
        )
        self.assertEqual(
            "http://forge.example.com/",
            api_base_url("http://forge.example.com:80/jelmer/example"),
        )

    def test_ssh_falls_back_to_https(self):
        # A git+ssh URL's port is an SSH port, not a web one.
        self.assertEqual(
            "https://forge.example.com/",
            api_base_url("git+ssh://git@forge.example.com:2222/jelmer/example"),
        )

    def test_credentials_are_dropped(self):
        self.assertEqual(
            "http://forge.example.com:3000/",
            api_base_url("http://user:pw@forge.example.com:3000/jelmer/example"),
        )

    def test_ipv6_host_is_bracketed(self):
        self.assertEqual(
            "http://[2001:db8::1]:3000/",
            api_base_url("http://[2001:db8::1]:3000/jelmer/example"),
        )

    def test_root_instance_matches_the_old_base(self):
        # The stored token is matched against transport.base.
        self.assertEqual(
            get_transport("https://gitlab.com").base,
            api_base_url("https://gitlab.com/jelmer/example"),
        )

    def test_subpath_is_dropped(self):
        # Known limitation, see the docstring.
        self.assertEqual(
            "https://example.com/",
            api_base_url("https://example.com/forge/jelmer/example"),
        )
