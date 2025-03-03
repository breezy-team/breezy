#    __init__.py -- Testsuite for quilt
#    Copyright (C) 2019 Jelmer Vernooij <jelmer@jelmer.uk>
#
#    Breezy is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    Breezy is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with Breezy; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

__all__ = [
    "TestCaseInTempDir",
    "TestCaseWithTransport",
    "TestUtil",
    "load_tests",
    "multiply_tests",
    "quilt_feature",
]


from ....tests import TestCaseInTempDir, TestCaseWithTransport, TestUtil, multiply_tests
from ....tests.features import ExecutableFeature

quilt_feature = ExecutableFeature("quilt")


def load_tests(loader, basic_tests, pattern):
    testmod_names = [
        "test_merge",
        "test_wrapper",
    ]
    basic_tests.addTest(
        loader.loadTestsFromModuleNames(
            ["{}.{}".format(__name__, i) for i in testmod_names]
        )
    )

    return basic_tests
