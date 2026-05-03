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

"""Compatibility shim for per_transport tests.

The per_transport tests have been moved to the dromedary package.
"""

import testscenarios
from dromedary import ConnectedTransport, Transport
from dromedary.tests.per_transport import (
    TransportTests as _DromedaryTransportTests,
)
from dromedary.tests.per_transport import (
    get_transport_test_permutations,
    transport_test_permutations,
)

__all__ = [
    "TransportTests",
    "get_transport_test_permutations",
    "transport_test_permutations",
]

from breezy.tests import TestNotApplicable, test_server
from breezy.transport.remote import RemoteTransport


def _dedupe_scenarios(scenarios):
    """Drop duplicate scenario IDs, preferring the most specific transport class.

    Both `breezy.transport.http` and `dromedary.http.urllib` are present in
    the transport registry — breezy installs its smart-aware HttpTransport
    on top of dromedary's, but doesn't displace dromedary's factory. Their
    `get_test_permutations()` therefore both yield (HttpTransport, HttpServer)
    and (HTTPS_transport, HTTPSServer) entries, with the same scenario id but
    different transport classes. Keep the breezy subclass so the smart-medium
    behaviour is exercised; drop the dromedary base.
    """
    by_id = {}
    for name, params in scenarios:
        existing = by_id.get(name)
        if existing is None:
            by_id[name] = params
            continue
        new_cls = params["transport_class"]
        old_cls = existing["transport_class"]
        if issubclass(new_cls, old_cls) and new_cls is not old_cls:
            by_id[name] = params
        # Otherwise keep the existing entry (already-seen wins on ties or
        # when the new entry is a base class of what we already have).
    return [(name, params) for name, params in by_id.items()]


def load_tests(loader, standard_tests, pattern):
    """Multiply tests for transport implementations.

    Build the suite explicitly from this module's TransportTests rather
    than reusing standard_tests: the dromedary base class is also in this
    module's namespace via the import above, and unittest's auto-
    discovery would otherwise pick it up under its `dromedary.*` module
    path and run it without scenario parameters.
    """
    TransportTests.scenarios = _dedupe_scenarios(transport_test_permutations())
    suite = loader.loadTestsFromTestCase(TransportTests)
    return testscenarios.load_tests_apply_scenarios(loader, suite, pattern)


class TransportTests(_DromedaryTransportTests):
    """Breezy-flavoured transport tests.

    Inherits the full transport test suite from dromedary, and overrides the
    post-connect hook tests to use breezy's RemoteTransport for the
    smart-medium dispatch (which dromedary doesn't know about).
    """

    def setUp(self):
        super().setUp()
        self.overrideEnv("BRZ_NO_SMART_VFS", None)

    def test_has_root_works(self):
        # Lives here (not in dromedary) because the SmartTCPServer_for_testing
        # check is breezy-specific.
        if self.transport_server is test_server.SmartTCPServer_for_testing:
            raise TestNotApplicable(
                "SmartTCPServer_for_testing intentionally does not allow access to /."
            )
        current_transport = self.get_transport()
        self.assertTrue(current_transport.has("/"))
        root = current_transport.clone("/")
        self.assertTrue(root.has(""))

    def test_hook_post_connection_one(self):
        log = []
        Transport.hooks.install_named_hook("post_connect", log.append, None)
        t = self.get_transport()
        self.assertEqual([], log)
        t.has("non-existant")
        if isinstance(t, RemoteTransport):
            self.assertEqual([t.get_smart_medium()], log)
        elif isinstance(t, ConnectedTransport):
            self.assertEqual([t], log)
        else:
            self.assertEqual([], log)

    def test_hook_post_connection_multi(self):
        log = []
        Transport.hooks.install_named_hook("post_connect", log.append, None)
        t1 = self.get_transport()
        t2 = t1.clone(".")
        t3 = self.get_transport()
        self.assertEqual([], log)
        t1.has("x")
        t2.has("x")
        t3.has("x")
        if isinstance(t1, RemoteTransport):
            self.assertEqual([t.get_smart_medium() for t in [t1, t3]], log)
        elif isinstance(t1, ConnectedTransport):
            self.assertEqual([t1, t3], log)
        else:
            self.assertEqual([], log)
