# Copyright (C) 2005, 2006 Canonical Ltd
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

"""API Documentation for breezy.

This documentation is made up of doctest testable examples.

Look for `breezy/doc/api/*.txt` to read it.

This documentation documents the current best practice in using the library.
For details on specific apis, see pydoc on the api, or read the source.
"""

import doctest
import os

from breezy import tests


def make_new_test_id(test):
    new_id = "{}.DocFileTest({})".format(__name__, test.id())
    return lambda: new_id


def load_tests(loader, basic_tests, pattern):
    """This module creates its own test suite with DocFileSuite."""
    dir_ = os.path.dirname(__file__)
    if os.path.isdir(dir_):
        candidates = os.listdir(dir_)
    else:
        candidates = []
    scripts = [candidate for candidate in candidates if candidate.endswith(".txt")]
    # since this module doesn't define tests, we ignore basic_tests
    suite = doctest.DocFileSuite(
        *scripts,
        setUp=tests.isolated_doctest_setUp,
        tearDown=tests.isolated_doctest_tearDown,
    )
    # DocFileCase reduces the test id to the base name of the tested file, we
    # want the module to appears there.
    for t in tests.iter_suite_tests(suite):
        t.id = make_new_test_id(t)
    return suite
