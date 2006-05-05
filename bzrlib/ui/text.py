# Copyright (C) 2005 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA



"""Text UI, write output to the console.
"""

import getpass
import sys

import bzrlib.progress
from bzrlib.symbol_versioning import *
from bzrlib.ui import UIFactory


class TextUIFactory(UIFactory):
    """A UI factory for Text user interefaces."""

    def __init__(self, bar_type=None):
        """Create a TextUIFactory.

        :param bar_type: The type of progress bar to create. It defaults to 
                         letting the bzrlib.progress.ProgressBar factory auto
                         select.
        """
        super(TextUIFactory, self).__init__()
        self._bar_type = bar_type

    @deprecated_method(zero_eight)
    def progress_bar(self):
        """See UIFactory.nested_progress_bar()."""
        # this in turn is abstract, and creates either a tty or dots
        # bar depending on what we think of the terminal
        return bzrlib.progress.ProgressBar()

    def get_password(self, prompt='', **kwargs):
        """Prompt the user for a password.

        :param prompt: The prompt to present the user
        :param kwargs: Arguments which will be expanded into the prompt.
                       This lets front ends display different things if
                       they so choose.
        :return: The password string, return None if the user 
                 canceled the request.
        """
        prompt = (prompt % kwargs).encode(sys.stdout.encoding, 'replace')
        prompt += ': '
        try:
            return getpass.getpass(prompt)
        except KeyboardInterrupt:
            return None

    def nested_progress_bar(self):
        """Return a nested progress bar.
        
        The actual bar type returned depends on the progress module which
        may return a tty or dots bar depending on the terminal.
        """
        if self._progress_bar_stack is None:
            self._progress_bar_stack = bzrlib.progress.ProgressBarStack(
                klass=self._bar_type)
        return self._progress_bar_stack.get_nested()

    def clear_term(self):
        """Prepare the terminal for output.

        This will, clear any progress bars, and leave the cursor at the
        leftmost position."""
        if self._progress_bar_stack is None:
            return
        overall_pb = self._progress_bar_stack.bottom()
        if overall_pb is not None:
            overall_pb.clear()
