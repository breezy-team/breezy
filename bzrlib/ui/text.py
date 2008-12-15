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
                         select.
        """
        super(TextUIFactory, self).__init__()
        self._bar_type = bar_type
        if stdout is None:
            self.stdout = sys.stdout
        else:
            self.stdout = stdout
        if stderr is None:
            self.stderr = sys.stderr
        else:
            self.stderr = stderr
        # total bytes read/written so far
        self._total_byte_count = 0
        self._bytes_since_update = 0
        self._last_activity_time = None
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

    def report_transport_activity(self, transport, byte_count, direction):
        """Called by transports as they do IO.
        
        This may update a progress bar, spinner, or similar display.
        By default it does nothing.
        """
        # XXX: Probably there should be a transport activity model, and that
        # too should be seen by the progress view, rather than being poked in
        # here.
        self._total_byte_count += byte_count
        self._bytes_since_update += byte_count
        now = time.time()
        if self._last_activity_time is None:
            self._last_activity_time = now
        elif now >= (self._last_activity_time + 0.2):
            # guard against clock stepping backwards, and don't update too
            # often
            rate = self._bytes_since_update / (now - self._last_activity_time)
            msg = ("%6dkB @ %6.1fkB/s" %
                (self._total_byte_count>>10, int(rate)>>10,))
            self._last_activity_time = now
            self._bytes_since_update = 0
            self._progress_view.show_transport_activity(msg)

    def show_progress(self, task):
        """A task has been updated and wants to be displayed.
        """
        self._progress_view.show_progress(task)

    def progress_finished(self, task):
        CLIUIFactory.progress_finished(self, task)
        if not self._task_stack:
            # finished top-level task
            self._progress_view.clear()
