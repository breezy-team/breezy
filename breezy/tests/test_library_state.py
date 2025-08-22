# Copyright (C) 2010, 2011 Canonical Ltd
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

import breezy

from .. import library_state, tests
from .. import ui as _mod_ui
from . import fixtures


# TODO: once sufficiently cleaned up this should be able to be TestCase.
class TestLibraryState(tests.TestCaseWithTransport):
    """Test cases for BzrLibraryState context management."""

    def test_ui_is_used(self):
        """Test that the specified UI factory is used during library state context."""
        self.overrideAttr(breezy, "_global_state", None)
        ui = _mod_ui.SilentUIFactory()
        state = library_state.BzrLibraryState(
            ui=ui, trace=fixtures.RecordingContextManager()
        )
        orig_ui = _mod_ui.ui_factory
        state.__enter__()
        try:
            self.assertEqual(ui, _mod_ui.ui_factory)
        finally:
            state.__exit__(None, None, None)
            self.assertEqual(orig_ui, _mod_ui.ui_factory)

    def test_trace_context(self):
        """Test that trace context managers are properly entered and exited."""
        self.overrideAttr(breezy, "_global_state", None)
        tracer = fixtures.RecordingContextManager()
        ui = _mod_ui.SilentUIFactory()
        state = library_state.BzrLibraryState(ui=ui, trace=tracer)
        state.__enter__()
        try:
            self.assertEqual(["__enter__"], tracer._calls)
        finally:
            state.__exit__(None, None, None)
            self.assertEqual(["__enter__", "__exit__"], tracer._calls)

    def test_ui_not_specified(self):
        """Test behavior when UI factory is not specified in library state."""
        self.overrideAttr(breezy, "_global_state", None)
        state = library_state.BzrLibraryState(
            ui=None, trace=fixtures.RecordingContextManager()
        )
        orig_ui = _mod_ui.ui_factory
        state.__enter__()
        try:
            self.assertEqual(orig_ui, _mod_ui.ui_factory)
        finally:
            state.__exit__(None, None, None)
            self.assertEqual(orig_ui, _mod_ui.ui_factory)
