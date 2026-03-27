"""Compatibility shim for per_transport tests.

The per_transport tests have been moved to the dromedary package.
"""

from dromedary.tests.test_transport import TestTransportImplementation
from dromedary.tests.per_transport import *  # noqa: F403, F401


def load_tests(loader, standard_tests, pattern):
    """Multiply tests for transport implementations."""
    TransportTests.scenarios = transport_test_permutations()
    return testscenarios.load_tests_apply_scenarios(
        loader, standard_tests, pattern
    )


class TransportTests(TestTransportImplementation):
    def setUp(self):
        super().setUp()
        self.overrideEnv("BRZ_NO_SMART_VFS", None)

    def test_hook_post_connection_one(self):
        """Fire post_connect hook after a ConnectedTransport is first used."""
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
        """Fire post_connect hook once per unshared underlying connection."""
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
