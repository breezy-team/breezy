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

"""Import processor that dump stats about the input (and doesn't import)."""


from bzrlib.trace import (
    note,
    warning,
    )
from bzrlib.plugins.fastimport import (
    commands,
    processor,
    )


# Maximum number of parents for a merge commit
_MAX_PARENTS = 16


class InfoProcessor(processor.ImportProcessor):
    """An import processor that dumps statistics about the input.

    No changes to the current repository are made.

    As well as providing useful information about an import
    stream before importing it, this processor is useful for
    benchmarking the speed at which data can be extracted from
    the source.
    """

    def __init__(self, target=None, params=None, verbose=False):
        # Allow creation without a target
        processor.ImportProcessor.__init__(self, target, params, verbose)


    def pre_process(self):
        # Init statistics
        self.cmd_counts = {}
        for cmd in commands.COMMAND_NAMES:
            self.cmd_counts[cmd] = 0
        self.file_cmd_counts = {}
        for fc in commands.FILE_COMMAND_NAMES:
            self.file_cmd_counts[fc] = 0
        self.parent_counts = {}
        for i in xrange(0, _MAX_PARENTS):
            self.parent_counts[i] = 0
        self.committers = set()
        self.separate_authors_found = False
        self.symlinks_found = False
        self.executables_found = False

    def post_process(self):
        # Dump statistics
        note("Command counts:")
        for cmd in commands.COMMAND_NAMES:
            note("\t%d\t%s", self.cmd_counts[cmd], cmd)
        note("File command counts:")
        for fc in commands.FILE_COMMAND_NAMES:
            note("\t%d\t%s", self.file_cmd_counts[fc], fc)
        if self.cmd_counts['commit']:
            note("Parent counts:")
            for i in xrange(0, _MAX_PARENTS):
                count = self.parent_counts[i]
                if count > 0:
                    note("\t%d\t%d", count, i)
            note("Other information:")
            note("\t%d\t%s" % (len(self.committers), 'unique committers'))
            note("\t%s\t%s" % (_found(self.separate_authors_found),
                'separate authors'))
            note("\t%s\t%s" % (_found(self.executables_found), 'executables'))
            note("\t%s\t%s" % (_found(self.symlinks_found), 'symlinks'))

    def progress_handler(self, cmd):
        """Process a ProgressCommand."""
        self.cmd_counts[cmd.name] += 1

    def blob_handler(self, cmd):
        """Process a BlobCommand."""
        self.cmd_counts[cmd.name] += 1

    def checkpoint_handler(self, cmd):
        """Process a CheckpointCommand."""
        self.cmd_counts[cmd.name] += 1

    def commit_handler(self, cmd):
        """Process a CommitCommand."""
        self.cmd_counts[cmd.name] += 1
        self.parent_counts[len(cmd.parents)] += 1
        self.committers.add(cmd.committer)
        if cmd.author is not None:
            self.separate_authors_found = True
        for fc in cmd.file_iter():
            self.file_cmd_counts[fc.name] += 1
            if isinstance(fc, commands.FileModifyCommand):
                if fc.is_executable:
                    self.executables_found = True
                if fc.kind == commands.SYMLINK_KIND:
                    self.symlinks_found = True

    def reset_handler(self, cmd):
        """Process a ResetCommand."""
        self.cmd_counts[cmd.name] += 1

    def tag_handler(self, cmd):
        """Process a TagCommand."""
        self.cmd_counts[cmd.name] += 1


def _found(b):
    """Format a found boolean as a string."""
    return ['no', 'found'][b]
