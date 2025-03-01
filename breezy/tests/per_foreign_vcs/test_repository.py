# Copyright (C) 2009, 2010 Canonical Ltd
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


"""Tests specific to Repository implementations that use foreign VCS'es."""

from breezy.tests import TestCase, TestCaseWithTransport


class TestRepositoryFormat(TestCase):
    def test_format_string(self):
        self.assertRaises(NotImplementedError, self.repository_format.get_format_string)

    def test_network_name(self):
        self.assertIsInstance(self.repository_format.network_name(), bytes)

    def test_format_description(self):
        self.assertIsInstance(self.repository_format.get_format_description(), str)


class ForeignRepositoryFactory:
    """Factory of repository for ForeignRepositoryTests."""

    def make_repository(self, transport):
        """Create a new, valid, repository. May or may not contain
        data.
        """
        raise NotImplementedError(self.make_repository)


class ForeignRepositoryTests(TestCaseWithTransport):
    """Basic tests for foreign repository implementations.

    These tests mainly make sure that the implementation covers the required
    bits of the API and returns semi-reasonable values, that are
    at least of the expected types and in the expected ranges.
    """

    # XXX: Some of these tests could be moved into a common testcase for
    # both native and foreign repositories.

    # Set to an instance of ForeignRepositoryFactory by the scenario
    repository_factory = None

    def make_repository(self):
        return self.repository_factory.make_repository(self.get_transport())

    def test_make_working_trees(self):
        """Test that Repository.make_working_trees() returns a boolean."""
        repo = self.make_repository()
        self.assertIsInstance(repo.make_working_trees(), bool)

    def test_get_physical_lock_status(self):
        """Test that a new repository is not locked by default."""
        repo = self.make_repository()
        self.assertFalse(repo.get_physical_lock_status())

    def test_is_shared(self):
        """Test that is_shared() returns a bool."""
        repo = self.make_repository()
        self.assertIsInstance(repo.is_shared(), bool)

    def test_gather_stats(self):
        """Test that gather_stats() will at least return a dictionary
        with the required keys.
        """
        repo = self.make_repository()
        stats = repo.gather_stats()
        self.assertIsInstance(stats, dict)
