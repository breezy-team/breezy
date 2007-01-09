# Copyright (C) 2005 Canonical Ltd
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

"""Tests for verifying validity and obsolescence of transport hints."""

from bzrlib import errors
from bzrlib.tests import TestCase
from bzrlib.transport import (
    TransportHints,
    TransportGetHints,
    )

class TestHintsValidity(TestCase):

    def test_unknown_hint(self):
        """Check that unknown hints are trapped"""
        self.assertRaises(errors.UnknownHint,
                          TransportHints,
                          with_sugar_on_top=True)

    def test_valid_hint(self):
        """Check that valid hints are recognized"""
        hints = TransportGetHints(follow_redirections=False)
        self.assertEquals(hints.get('follow_redirections'),False)


    def test_deprecated_hint(self):
        """Check that deprecated hints are detected"""
        class DeprecatedHints(TransportGetHints):
            _deprecated_hints = TransportGetHints._deprecated_hints
            # Hopefully, we will not clash with existing hint names...
            _deprecated_hints['fossil_fuel'] = 'Use solar_cells instead'


        self.callDeprecated(['hint fossil_fuel is deprecated: '
                             'Use solar_cells instead'],
                            DeprecatedHints, fossil_fuel=True)

