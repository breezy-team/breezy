# Copyright (C) 2005-2012, 2016 Canonical Ltd
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

"""Tests for dromedary transport functionality."""

import os
import tempfile
import unittest


class _AssertHelpersMixin:
    """Extra assertion methods for dromedary tests."""

    def assertStartsWith(self, s, prefix, msg=None):
        if not s.startswith(prefix):
            if msg is None:
                msg = f"{s!r} does not start with {prefix!r}"
            raise AssertionError(msg)

    def assertEndsWith(self, s, suffix, msg=None):
        if not s.endswith(suffix):
            if msg is None:
                msg = f"{s!r} does not end with {suffix!r}"
            raise AssertionError(msg)

    def overrideAttr(self, obj, attr_name, new_value=None):
        """Temporarily replace an attribute, restoring it after the test."""
        old_value = getattr(obj, attr_name)
        if new_value is not None:
            setattr(obj, attr_name, new_value)
        self.addCleanup(setattr, obj, attr_name, old_value)


class TestCase(_AssertHelpersMixin, unittest.TestCase):
    """Base test case for dromedary tests with extra assertion helpers."""

    pass


class TestCaseInTempDir(TestCase):
    """A test case that runs in a temporary directory.

    Creates a fresh temporary directory before each test and changes into it.
    The original directory is restored and the temporary directory is cleaned
    up after each test.
    """

    def setUp(self):
        super().setUp()
        self._original_dir = os.getcwd()
        self._tempdir = tempfile.mkdtemp(prefix="dromedary-test-")
        os.chdir(self._tempdir)
        self.addCleanup(self._cleanup_tempdir)

    def _cleanup_tempdir(self):
        os.chdir(self._original_dir)
        import shutil

        shutil.rmtree(self._tempdir, ignore_errors=True)

    @property
    def test_dir(self):
        """The path to the temporary directory for this test."""
        return self._tempdir


class TestCaseWithMemoryTransport(TestCase):
    """A test case that provides a memory transport.

    Provides get_transport() to obtain a memory transport for testing.
    """

    def setUp(self):
        super().setUp()
        from dromedary.memory import MemoryServer

        self._memory_server = MemoryServer()
        self._memory_server.start_server()
        self.addCleanup(self._memory_server.stop_server)

    def get_transport(self, relpath=""):
        """Return a memory transport for testing."""
        import dromedary

        base_url = self._memory_server.get_url()
        t = dromedary.get_transport_from_url(base_url)
        if relpath:
            t = t.clone(relpath)
        return t


class TestCaseWithTransport(TestCaseInTempDir):
    """A test case that provides transport access to a temporary directory."""

    def get_transport(self, relpath=""):
        """Return a local transport for the test's temporary directory."""
        from dromedary import get_transport_from_path

        path = os.path.join(self._tempdir, relpath) if relpath else self._tempdir
        os.makedirs(path, exist_ok=True)
        return get_transport_from_path(path)
