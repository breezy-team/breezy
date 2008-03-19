
import sys

sys.path.insert(0, "build/lib/bzrlib/plugins/")

import builddeb

suite = builddeb.test_suite()

import unittest

result = unittest.TextTestRunner(verbosity=2).run(suite)

if not result.wasSuccessful():
    raise sys.exit(1)

