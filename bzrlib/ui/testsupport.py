# Copyright (C) 2006-2010 Canonical Ltd
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

"""UI implementations for use in testing.
"""


from bzrlib import (
    ui,
    )


class CapturingUIFactory(ui.UIFactory):
    """A UI Factory for testing - capture the updates made through it."""

    def __init__(self):
        super(CapturingUIFactory, self).__init__()
        self._calls = []
        self.depth = 0

    def clear(self):
        """See progress.ProgressTask.clear()."""

    def clear_term(self):
        """See progress.ProgressTask.clear_term()."""

    def finished(self):
        """See progress.ProgressTask.finished()."""
        self.depth -= 1

    def note(self, fmt_string, *args, **kwargs):
        """See progress.ProgressTask.note()."""

    def progress_bar(self):
        return self

    def nested_progress_bar(self):
        self.depth += 1
        return self

    def update(self, message, count=None, total=None):
        """See progress.ProgressTask.update()."""
        if self.depth == 1:
            self._calls.append(("update", count, total, message))


