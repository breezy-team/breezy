# Copyright (C) 2026 Breezy developers
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

"""Compatibility shim for transport tests.

The transport tests have been moved to the :mod:`dromedary.tests.test_transport`
package; this shim re-exports its public surface so existing callers
(and type checkers) keep working. Enumerated imports rather than
``from X import *`` so ``mypy`` can see the attributes —
star imports don't propagate attribute visibility through the
type checker.

:class:`TestTransportImplementation` is a breezy-side override that uses
breezy's :class:`~breezy.tests.TestCaseInTempDir` as the base class so the
breezy isolated environment (``EMAIL``, ``BRZ_HOME`` etc.) is applied. The
dromedary version inherits from dromedary's own ``TestCaseInTempDir`` and
therefore doesn't isolate the user environment, which causes brz commits in
tests to fail with ``NoWhoami`` on hosts where ``EMAIL`` isn't set.
"""

from dromedary import urlutils
from dromedary.tests.test_transport import (
    BackupTransportHandler,
    BadTransportHandler,
    ChrootDecoratorTransportTest,
    FakeNFSDecoratorTests,
    FakeVFATDecoratorTests,
    PathFilteringDecoratorTransportTest,
    ReadonlyDecoratorTransportTest,
    TestChrootServer,
    TestCoalesceOffsets,
    TestConnectedTransport,
    TestHooks,
    TestKind,
    TestLocalTransportMutation,
    TestLocalTransports,
    TestLocalTransportWriteStream,
    TestMemoryServer,
    TestMemoryTransport,
    TestReusedTransports,
    TestSSHConnections,
    TestTransport,
    TestTransportFromPath,
    TestTransportFromUrl,
    TestTransportTrace,
    TestWin32LocalTransport,
)

from . import TestCaseInTempDir


class TestTransportImplementation(TestCaseInTempDir):
    """Implementation verification for transports.

    To verify a transport we need a server factory, which is a callable
    that accepts no parameters and returns an implementation of
    :class:`breezy.transport.Server`.

    That Server is then used to construct transport instances and test
    the transport via loopback activity.

    This mirrors :class:`dromedary.tests.test_transport.TestTransportImplementation`,
    but uses breezy's :class:`TestCaseInTempDir` as the base so that breezy's
    test environment isolation (``isolated_environ``) is applied.
    """

    def setUp(self):
        super().setUp()
        self._server = self.transport_server()
        self.start_server(self._server)

    def get_transport(self, relpath=None):
        """Return a connected transport to the local directory.

        :param relpath: a path relative to the base url.
        """
        from breezy.transport import get_transport_from_url

        base_url = self._server.get_url()
        url = self._adjust_url(base_url, relpath)
        t = get_transport_from_url(url)
        if not isinstance(t, self.transport_class):
            # We did not get the correct transport class type. Override the
            # regular connection behaviour by direct construction.
            t = self.transport_class(url)
        return t

    def build_tree(self, shape, line_endings="binary", transport=None):
        """Build a tree of files via the test transport.

        Transport implementation tests need to operate on files at the test
        server (which may not be a local filesystem) rather than the process
        cwd, so this overrides the cwd-based ``TestCaseInTempDir`` version.
        If ``transport`` is None or read-only, falls back to a transport on
        the current working directory.
        """
        import os

        if transport is None or transport.is_readonly():
            from breezy.transport import get_transport_from_path

            transport = get_transport_from_path(".")
        for name in shape:
            escaped = urlutils.escape(name.rstrip("/"))
            if name.endswith("/"):
                transport.mkdir(escaped)
            else:
                if line_endings == "binary":
                    end = b"\n"
                elif line_endings == "native":
                    end = os.linesep.encode("ascii")
                else:
                    raise ValueError(f"Invalid line ending request {line_endings!r}")
                content = b"contents of %s%s" % (name.encode("utf-8"), end)
                transport.put_bytes(escaped, content)


__all__ = [
    "BackupTransportHandler",
    "BadTransportHandler",
    "ChrootDecoratorTransportTest",
    "FakeNFSDecoratorTests",
    "FakeVFATDecoratorTests",
    "PathFilteringDecoratorTransportTest",
    "ReadonlyDecoratorTransportTest",
    "TestChrootServer",
    "TestCoalesceOffsets",
    "TestConnectedTransport",
    "TestHooks",
    "TestKind",
    "TestLocalTransportMutation",
    "TestLocalTransportWriteStream",
    "TestLocalTransports",
    "TestMemoryServer",
    "TestMemoryTransport",
    "TestReusedTransports",
    "TestSSHConnections",
    "TestTransport",
    "TestTransportFromPath",
    "TestTransportFromUrl",
    "TestTransportImplementation",
    "TestTransportTrace",
    "TestWin32LocalTransport",
]
