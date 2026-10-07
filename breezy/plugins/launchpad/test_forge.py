# Copyright (C) 2026 Breezy Developers
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

"""Tests for the Launchpad forge."""

from ...forge import UnsupportedForge
from ...tests import TestCase
from .forge import Launchpad


class TestProbeFromHostname(TestCase):
    def test_git(self):
        self.assertIsInstance(
            Launchpad.probe_from_hostname("git.launchpad.net"), Launchpad
        )

    def test_bazaar(self):
        self.assertIsInstance(
            Launchpad.probe_from_hostname("bazaar.launchpad.net"), Launchpad
        )

    def test_subdomain(self):
        self.assertIsInstance(
            Launchpad.probe_from_hostname("git.staging.launchpad.net"), Launchpad
        )

    def test_other_host(self):
        self.assertRaises(
            UnsupportedForge, Launchpad.probe_from_hostname, "example.com"
        )

    def test_other_launchpad_host(self):
        self.assertRaises(
            UnsupportedForge, Launchpad.probe_from_hostname, "answers.launchpad.net"
        )

    def test_hostname_is_not_a_pattern(self):
        self.assertRaises(UnsupportedForge, Launchpad.probe_from_hostname, ".*")
