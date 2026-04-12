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

import io
import logging
import os
import re
import tempfile
import unittest


class TestNotApplicable(unittest.TestCase.skipException if hasattr(unittest.TestCase, 'skipException') else unittest.SkipTest):
    """Test is not applicable to the current situation."""


TestSkipped = unittest.SkipTest


def multiply_tests(tests, scenarios, result):
    """Multiply tests by scenarios, adding them to result."""
    for test in tests:
        for scenario_id, scenario_attrs in scenarios:
            new_test = clone_test(test, scenario_id)
            for name, value in scenario_attrs.items():
                setattr(new_test, name, value)
            result.addTest(new_test)
    return result


def clone_test(test, new_id):
    """Clone a test case with a new id suffix."""
    new_test = test.__class__(test._testMethodName)
    new_test._scenario_suffix = "(" + new_id + ")"
    return new_test


class Feature:
    """A feature that may or may not be available."""

    def available(self):
        try:
            return self._probe()
        except Exception:
            return False

    def _probe(self):
        raise NotImplementedError


class _Win32Feature(Feature):
    def _probe(self):
        import sys
        return sys.platform == "win32"


class _ParamikoFeature(Feature):
    def _probe(self):
        import importlib.util
        return importlib.util.find_spec("paramiko") is not None


win32_feature = _Win32Feature()
paramiko = _ParamikoFeature()


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

    def assertRaises(self, exc_type, callable=None, *args, **kwargs):
        if callable is not None:
            try:
                callable(*args, **kwargs)
            except exc_type as e:
                return e
            else:
                raise AssertionError(f"{exc_type.__name__} not raised")
        return super().assertRaises(exc_type)

    def assertLength(self, expected, container):
        if len(container) != expected:
            raise AssertionError(
                f"Expected length {expected}, got {len(container)}: {container!r}"
            )

    def assertListRaises(self, exc_type, callable, *args, **kwargs):
        """Assert that fully consuming an iterator raises the given exception."""
        try:
            list(callable(*args, **kwargs))
        except exc_type:
            return
        raise AssertionError(f"{exc_type.__name__} not raised")

    def assertTransportMode(self, transport, path, mode):
        """Assert a file's mode bits via transport.stat()."""
        actual_mode = transport.stat(path).st_mode & 0o777
        if actual_mode != mode:
            raise AssertionError(
                f"mode mismatch for {path!r}: expected {mode:o}, got {actual_mode:o}"
            )

    def assertEqualDiff(self, expected, actual, msg=None):
        """Assert two values are equal; on failure print a diff."""
        if expected == actual:
            return
        if isinstance(expected, bytes) and isinstance(actual, bytes):
            try:
                expected_text = expected.decode("utf-8")
                actual_text = actual.decode("utf-8")
            except UnicodeDecodeError:
                raise AssertionError(
                    f"{msg + ': ' if msg else ''}{expected!r} != {actual!r}"
                )
        else:
            expected_text = str(expected)
            actual_text = str(actual)
        import difflib

        diff = "\n".join(
            difflib.unified_diff(
                expected_text.splitlines(),
                actual_text.splitlines(),
                lineterm="",
                fromfile="expected",
                tofile="actual",
            )
        )
        raise AssertionError(
            f"{msg + chr(10) if msg else ''}values not equal:\n{diff}"
        )

    def overrideAttr(self, obj, attr_name, new_value=None):
        """Temporarily replace an attribute, restoring it after the test."""
        old_value = getattr(obj, attr_name)
        if new_value is not None:
            setattr(obj, attr_name, new_value)
        self.addCleanup(setattr, obj, attr_name, old_value)

    def recordCalls(self, obj, attr_name):
        """Replace a callable with a wrapper that records calls.

        Returns the list of call records. Restores the original after the test.
        """
        calls = []
        orig = getattr(obj, attr_name)

        def recorder(*args, **kwargs):
            calls.append((args, kwargs))
            return orig(*args, **kwargs)

        setattr(obj, attr_name, recorder)
        self.addCleanup(setattr, obj, attr_name, orig)
        return calls


class TestCase(_AssertHelpersMixin, unittest.TestCase):
    """Base test case for dromedary tests with extra assertion helpers."""

    def setUp(self):
        super().setUp()
        self._log_stream = io.StringIO()
        self._log_handler = logging.StreamHandler(self._log_stream)
        self._log_handler.setFormatter(logging.Formatter("%(message)s"))
        dromedary_logger = logging.getLogger("dromedary")
        dromedary_logger.addHandler(self._log_handler)
        dromedary_logger.setLevel(logging.DEBUG)
        self.addCleanup(dromedary_logger.removeHandler, self._log_handler)

    def get_log(self):
        """Return captured log output."""
        return self._log_stream.getvalue()

    def log(self, *args):
        """Append a message to the captured test log."""
        if len(args) == 1:
            msg = args[0]
        else:
            msg = args[0] % args[1:]
        self._log_stream.write(str(msg) + "\n")

    def start_server(self, server):
        """Start a test server, registering cleanup to stop it."""
        server.start_server()
        self.addCleanup(server.stop_server)

    def requireFeature(self, feature):
        """Skip test if feature is not available."""
        if not feature.available():
            raise unittest.SkipTest(f"Feature not available: {feature!r}")

    def assertContainsRe(self, haystack, needle, flags=0):
        """Assert that a string matches a regular expression."""
        if not re.search(needle, haystack, flags):
            raise AssertionError(
                f"pattern {needle!r} not found in {haystack!r}"
            )

    def overrideEnv(self, name, new_value):
        """Temporarily override an environment variable."""
        old_value = os.environ.get(name)
        if new_value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = new_value

        def restore():
            if old_value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old_value

        self.addCleanup(restore)

    @staticmethod
    def _adjust_url(base, relpath):
        """Get a URL for the transport, adjusted by relpath."""
        if relpath is not None and relpath != ".":
            if not base.endswith("/"):
                base = base + "/"
            if base.startswith("./") or base.startswith("/"):
                base += relpath
            else:
                from dromedary import urlutils

                base += urlutils.escape(relpath)
        return base


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

    def build_tree(self, shape, line_endings="binary"):
        """Build a test tree of local files and directories under cwd.

        shape is a sequence of file specifications. If the final
        character is '/', a directory is created.
        """
        for name in shape:
            if name.endswith("/"):
                os.mkdir(name.rstrip("/"))
            else:
                if line_endings == "binary":
                    end = b"\n"
                elif line_endings == "native":
                    end = os.linesep.encode("ascii")
                else:
                    raise ValueError(f"Invalid line ending request {line_endings!r}")
                content = b"contents of %s%s" % (name.encode("utf-8"), end)
                with open(name, "wb") as f:
                    f.write(content)

    def build_tree_contents(self, entries):
        """Build a tree with explicit file contents under cwd."""
        for name, content in entries:
            with open(name, "wb") as f:
                f.write(content)


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
