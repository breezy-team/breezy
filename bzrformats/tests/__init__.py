"""Test suite for bzrformats package."""

import os
import unittest


def load_tests(loader, basic_tests, pattern):
    """Load tests for bzrformats using the standard unittest discovery mechanism."""
    suite = loader.suiteClass()
    # Add the tests for this module
    suite.addTests(basic_tests)

    # List of test modules to load
    testmod_names = [
        "per_inventory",
        "per_versionedfile",
        "test__btree_serializer",
        "test__chk_map",
        "test__dirstate_helpers",
        "test__groupcompress",
        "test_btree_index",
        "test_chk_map",
        "test_chk_serializer",
        "test_chunk_writer",
        "test_dirstate",
        "test_generate_ids",
        "test_groupcompress",
        "test_hashcache",
        "test_index",
        "test_inv",
        "test_inventory_delta",
        "test_knit",
        "test_pack",
        "test_rio",
        "test_serializer",
        "test_tuned_gzip",
        "test_versionedfile",
        "test_weave",
        "test_xml",
    ]

    # Load each test module
    prefix = __name__ + "."
    for testmod_name in testmod_names:
        suite.addTest(loader.loadTestsFromName(prefix + testmod_name))

    # Also load per_* modules
    per_modules = [
        "per_versionedfile",
        "per_inventory",
    ]

    for per_module in per_modules:
        try:
            suite.addTest(loader.loadTestsFromName(prefix + per_module))
        except (ImportError, AttributeError):
            # Skip if module doesn't exist or has no tests
            pass

    return suite


def test_suite():
    """Return the test suite for bzrformats (for backwards compatibility)."""
    loader = unittest.TestLoader()
    # Get the directory of this module
    test_dir = os.path.dirname(__file__)
    suite = loader.discover(test_dir, pattern="test_*.py")
    return suite
