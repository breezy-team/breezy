# Copyright (C) 2006 by Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Symbol versioning tests."""

import bzrlib.symbol_versioning as symbol_versioning
from bzrlib.tests import TestCase


@symbol_versioning.deprecated_function(symbol_versioning.zero_seven)
def deprecated_function():
    return 1


class TestDeprecationWarnings(TestCase):

    def capture_warning(self, message, category):
        self._warnings.append((message, category))

    def setUp(self):
        super(TestDeprecationWarnings, self).setUp()
        self._warnings = []
    
    @symbol_versioning.deprecated_method(symbol_versioning.zero_seven)
    def deprecated_method(self):
        return 1

    def test_deprecated_method(self):
        expected_warning = (
            "bzrlib.tests.test_symbol_versioning."
            "TestDeprecationWarnings.deprecated_method "
            "was deprecated in version 0.7", DeprecationWarning)
        self.check_deprecated_callable(expected_warning,
                                       self.deprecated_method)

    def test_deprecated_function(self):
        expected_warning = (
            "bzrlib.tests.test_symbol_versioning.deprecated_function "
            "was deprecated in version 0.7", DeprecationWarning)
        self.check_deprecated_callable(expected_warning,
                                       deprecated_function)

    def check_deprecated_callable(self, expected_warning, deprecated_callable):
        old_warning_method = symbol_versioning.warn
        try:
            symbol_versioning.set_warning_method(self.capture_warning)
            self.assertEqual(1, deprecated_callable())
            self.assertEqual([expected_warning], self._warnings)
            deprecated_callable()
            self.assertEqual([expected_warning, expected_warning],
                             self._warnings)
        finally:
            symbol_versioning.set_warning_method(old_warning_method)
