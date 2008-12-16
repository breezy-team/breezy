# Copyright (C) 2005, 2008 Canonical Ltd
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



"""Text UI, write output to the console.
"""

import sys
import time

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import getpass

from bzrlib import (
    progress,
    osutils,
    )
""")

from bzrlib.ui import CLIUIFactory


class TextUIFactory(CLIUIFactory):
    """A UI factory for Text user interefaces."""

    def __init__(self,
                 bar_type=None,
                 stdout=None,
                 stderr=None):
        """Create a TextUIFactory.

        :param bar_type: The type of progress bar to create. It defaults to 
                         letting the bzrlib.progress.ProgressBar factory auto
                         select.   Deprecated.
        """
        super(TextUIFactory, self).__init__()
        if stdout is None:
            self.stdout = sys.stdout
        else:
            self.stdout = stdout
        if stderr is None:
            self.stderr = sys.stderr
        else:
            self.stderr = stderr
        if bar_type:
            symbol_versioning.warn(symbol_versioning.deprecated_in((1, 11, 0))
                % "bar_type parameter")
        # paints progress, network activity, etc
        self._progress_view = progress.TextProgressView(self.stderr)

    def prompt(self, prompt):
        """Emit prompt on the CLI."""
        self.stdout.write(prompt)
        
    def clear_term(self):
        """Prepare the terminal for output.

        This will, clear any progress bars, and leave the cursor at the
        leftmost position."""
        # XXX: If this is preparing to write to stdout, but that's for example
        # directed into a file rather than to the terminal, and the progress
        # bar _is_ going to the terminal, we shouldn't need
        # to clear it.  We might need to separately check for the case of 
        self._progress_view.clear()

    def note(self, msg):
        """Write an already-formatted message, clearing the progress bar if necessary."""
        self.clear_term()
        self.stdout.write(msg + '\n')

    def report_transport_activity(self, transport, byte_count, direction):
        """Called by transports as they do IO.
        
        This may update a progress bar, spinner, or similar display.
        By default it does nothing.
        """
        self._progress_view.show_transport_activity(byte_count)

    def show_progress(self, task):
        """A task has been updated and wants to be displayed.
        """
        self._progress_view.show_progress(task)

    def progress_finished(self, task):
        CLIUIFactory.progress_finished(self, task)
        if not self._task_stack:
            # finished top-level task
            self._progress_view.clear()
