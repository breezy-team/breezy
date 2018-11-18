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

"""UI implementations for use in testing.
"""


from .. import (
    progress,
    ui,
    )


class ProgressRecordingUIFactory(ui.UIFactory, progress.DummyProgress):
    """Captures progress updates made through it.

    This is overloaded as both the UIFactory and the progress model."""

    def __init__(self):
        super(ProgressRecordingUIFactory, self).__init__()
        self._calls = []
        self.depth = 0

    def nested_progress_bar(self):
        self.depth += 1
        return self

    def finished(self):
        self.depth -= 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.finished()
        return False

    def update(self, message, count=None, total=None):
        if self.depth == 1:
            self._calls.append(("update", count, total, message))
