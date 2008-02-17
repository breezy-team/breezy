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

"""Import processor that filters the input (and doesn't import)."""


from bzrlib.plugins.fastimport import (
    commands,
    processor,
    )


class FilterProcessor(processor.ImportProcessor):
    """An import processor that filters the input.

    No changes to the current repository are made.
    """

    known_params = commands.COMMAND_NAMES

    def __init__(self, target=None, params=None, verbose=False):
        # Allow creation without a target
        processor.ImportProcessor.__init__(self, target, params, verbose)

    def pre_handler(self, cmd):
        """Hook for logic before each handler starts."""
        if self.params.get(cmd.name):
            print "%s" % (cmd,)

    def progress_handler(self, cmd):
        """Process a ProgressCommand."""
        pass

    def blob_handler(self, cmd):
        """Process a BlobCommand."""
        pass

    def checkpoint_handler(self, cmd):
        """Process a CheckpointCommand."""
        pass

    def commit_handler(self, cmd):
        """Process a CommitCommand."""
        for fc in cmd.file_iter():
            pass

    def reset_handler(self, cmd):
        """Process a ResetCommand."""
        pass

    def tag_handler(self, cmd):
        """Process a TagCommand."""
        pass
