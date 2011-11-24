# Copyright (C) 2011 by Canonical Ltd
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

import os

from bzrlib import (
    tests,
    )

class TestPoMerger(tests.TestCaseWithTransport):

    def test_bad_config_options(self):
        # pot_file and po_files lengths should match
        pass

    def test_match_po_files(self):
        # hook will fire if the merged file matches one of the globs
        pass

    def test_no_pot_file(self):
        # hook won't fire if there is no pot file
        # - not present
        # - doesn't match
        pass

    def test_no_pot_file(self):
        # hook won't fire if there are conflicts in the pot file
        pass

