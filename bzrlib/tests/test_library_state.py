# Copyright (C) 2010 Canonical Ltd
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

"""Tests for BzrLibraryState."""

import bzrlib
from bzrlib import (
    library_state,
    tests,
    ui as _mod_ui
    )


# TODO: once sufficiently cleaned up this should be able to be TestCase.
class TestLibraryState(tests.TestCaseWithTransport):

    def test_ui_is_used(self):
        ui = _mod_ui.SilentUIFactory()
        state = library_state.BzrLibraryState(ui=ui)
        orig_ui = _mod_ui.ui_factory
        state.__enter__()
        try:
            self.assertEqual(ui, _mod_ui.ui_factory)
        finally:
            state.__exit__(None, None, None)
            self.assertEqual(orig_ui, _mod_ui.ui_factory)
