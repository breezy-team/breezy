# Copyright (C) 2008 Canonical Ltd
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

"""Import processor that supports all Bazaar repository formats."""


from bzrlib.trace import (
    note,
    warning,
    )
from bzrlib.plugins.fastimport import processor


class GenericProcessor(processor.ImportProcessor):
    """An import processor that handles basic imports.

    Current features supported:

    * progress reporting works
    * checkpoints are ignored
    * some basic statistics are dumped on completion.

    Other commands produce errors.
    """

    def pre_process(self):
        # Init statistics
        self._revision_count = 0
        self._branch_count = 0
        self._tag_count = 0
        self._file_count = 0
        self._dir_count = 0
        self._symlink_count = 0

    def post_process(self):
        # Dump statistics
        note("Imported %d revisions into %d branches with %d tags.",
            self._revision_count, self._branch_count, self._tag_count)
        note("%d files, %d directories, %d symlinks.",
            self._file_count, self._dir_count, self._symlink_count)

    def progress_handler(self, cmd):
        """Process a ProgressCommand."""
        note("progress %s" % (cmd.message,))

    def checkpoint_handler(self, cmd):
        """Process a CheckpointCommand."""
        warning("ignoring checkpoint command")
