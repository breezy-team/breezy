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
    'BzrLibraryState',
    ]

import sys

import bzrlib


class BzrLibraryState(object):
    """The state about how bzrlib has been configured.

    This is the core state needed to make use of bzr. The current instance is
    currently always exposed as bzrlib.global_state, but we desired to move
    to a point where no global state is needed at all.
    
    :ivar saved_state: The bzrlib.global_state at the time __enter__ was
        called.
    :ivar cleanups: An ObjectWithCleanups which can be used for cleanups that
        should occur when the use of bzrlib is completed. This is initialised
        in __enter__ and executed in __exit__.
    """

    def __init__(self, setup_ui=True, stdin=None, stdout=None, stderr=None):
        """Create library start for normal use of bzrlib.

        Most applications that embed bzrlib, including bzr itself, should just
        call bzrlib.initialize(), but it is possible to use the state class
        directly.

        More options may be added in future so callers should use named
        arguments.

        BzrLibraryState implements the Python 2.5 Context Manager protocol
        PEP343, and can be used with the with statement. Upon __enter__ the
        global variables in use by bzr are set, and they are cleared on
        __exit__.

        :param setup_ui: If true (default) use a terminal UI; otherwise 
            some other ui_factory must be assigned to `bzrlib.ui.ui_factory` by
            the caller.
        :param stdin, stdout, stderr: If provided, use these for terminal IO;
            otherwise use the files in `sys`.
        """
        self.setup_ui = setup_ui
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr

    def __enter__(self):
        # NB: This function tweaks so much global state it's hard to test it in
        # isolation within the same interpreter.  It's not reached on normal
        # in-process run_bzr calls.  If it's broken, we expect that
        # TestRunBzrSubprocess may fail.
        import bzrlib
        if bzrlib.version_info[3] == 'final':
            from bzrlib.symbol_versioning import suppress_deprecation_warnings
            warning_cleanup = suppress_deprecation_warnings(override=True)
        else:
            warning_cleanup = None

        import bzrlib.cleanup
        import bzrlib.trace
        self.cleanups = bzrlib.cleanup.ObjectWithCleanups()
        if warning_cleanup:
            self.cleanups.add_cleanup(warning_cleanup)
        bzrlib.trace.enable_default_logging()

        if self.setup_ui:
            import bzrlib.ui
            stdin = self.stdin or sys.stdin
            stdout = self.stdout or sys.stdout
            stderr = self.stderr or sys.stderr
            bzrlib.ui.ui_factory = bzrlib.ui.make_ui_for_terminal(
                stdin, stdout, stderr)
        self.saved_state = bzrlib.global_state
        bzrlib.global_state = self
        return self # This is bound to the 'as' clause in a with statement.

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanups.cleanup_now()
        import bzrlib.ui
        bzrlib.trace._flush_stdout_stderr()
        bzrlib.trace._flush_trace()
        import bzrlib.osutils
        bzrlib.osutils.report_extension_load_failures()
        bzrlib.ui.ui_factory.__exit__(None, None, None)
        bzrlib.ui.ui_factory = None
        global global_state
        global_state = self.saved_state
        return False # propogate exceptions.
