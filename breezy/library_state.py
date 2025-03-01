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

"""The core state needed to make use of bzr is managed here."""

__all__ = [
    "BzrLibraryState",
]


import contextlib

import breezy

from .lazy_import import lazy_import

lazy_import(
    globals(),
    """
from breezy import (
    config,
    osutils,
    symbol_versioning,
    trace,
    ui,
    )
""",
)


class BzrLibraryState:
    """The state about how breezy has been configured.

    This is the core state needed to make use of bzr. The current instance is
    currently always exposed as breezy._global_state, but we desired to move
    to a point where no global state is needed at all.

    :ivar exit_stack: An ExitStack which can be used for cleanups that
        should occur when the use of breezy is completed. This is initialised
        in __enter__ and executed in __exit__.
    """

    def __init__(self, ui, trace):
        """Create library start for normal use of breezy.

        Most applications that embed breezy, including bzr itself, should just
        call breezy.initialize(), but it is possible to use the state class
        directly. The initialize() function provides sensible defaults for a
        CLI program, such as a text UI factory.

        More options may be added in future so callers should use named
        arguments.

        BzrLibraryState implements the Python 2.5 Context Manager protocol
        PEP343, and can be used with the with statement. Upon __enter__ the
        global variables in use by bzr are set, and they are cleared on
        __exit__.

        :param ui: A breezy.ui.ui_factory to use.
        :param trace: A breezy.trace.Config context manager to use, perhaps
            breezy.trace.DefaultConfig.
        """
        self._ui = ui
        self._trace = trace
        # There is no overrides by default, they are set later when the command
        # arguments are parsed.
        self.cmdline_overrides = config.CommandLineStore()
        # No config stores are cached to start with
        self.config_stores = {}  # By url
        self.started = False

    def __enter__(self):
        if not self.started:
            self._start()
        return self  # This is bound to the 'as' clause in a with statement.

    def _start(self):
        """Do all initialization."""
        # NB: This function tweaks so much global state it's hard to test it in
        # isolation within the same interpreter.  It's not reached on normal
        # in-process run_bzr calls.  If it's broken, we expect that
        # TestRunBzrSubprocess may fail.
        self.exit_stack = contextlib.ExitStack()

        if breezy.version_info[3] == "final":
            self.exit_stack.callback(
                symbol_versioning.suppress_deprecation_warnings(override=True)
            )

        self._trace.__enter__()

        self._orig_ui = breezy.ui.ui_factory
        if self._ui is not None:
            breezy.ui.ui_factory = self._ui
            self._ui.__enter__()

        if breezy._global_state is not None:
            raise RuntimeError("Breezy already initialized")
        breezy._global_state = self
        self.started = True

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            # Save config changes
            for _k, store in self.config_stores.items():
                store.save_changes()
        self.exit_stack.close()
        trace._flush_stdout_stderr()
        trace._flush_trace()
        osutils.report_extension_load_failures()
        if self._ui is not None:
            self._ui.__exit__(None, None, None)
        self._trace.__exit__(None, None, None)
        ui.ui_factory = self._orig_ui
        breezy._global_state = None
        return False  # propogate exceptions.
