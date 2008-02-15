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

"""Processor of import commands.

This module provides core processing functionality including an abstract class
for basing real processors on. See the processors package for examples.
"""


import errors


class ImportProcessor(object):
    """Base class for import processors.
    
    Subclasses should override the pre_*, post_* and *_handler
    methods as appropriate.
    """

    def __init__(self, target, verbose=False):
        self.target = target
        self.verbose = verbose

    def process(self, command_iter):
        """Import data into Bazaar by processing a stream of commands.

        :param command_iter: an iterator providing commands
        """
        self.pre_process()
        for cmd in command_iter():
            try:
                handler = self.__class__.__dict__[cmd.name + "_handler"]
            except KeyError:
                raise errors.MissingHandler(cmd.name)
            else:
                # TODO: put hooks around processing each command?
                handler(self, cmd)
        self.post_process()

    def pre_process(self):
        """Hook for logic at start of processing."""
        pass

    def post_process(self):
        """Hook for logic at end of processing."""
        pass

    def progress_handler(self, cmd):
        """Process a ProgressCommand."""
        raise NotImplementedError(self.progress_handler)

    def blob_handler(self, cmd):
        """Process a BlobCommand."""
        raise NotImplementedError(self.blob_handler)

    def checkpoint_handler(self, cmd):
        """Process a CheckpointCommand."""
        raise NotImplementedError(self.checkpoint_handler)

    def commit_handler(self, cmd):
        """Process a CommitCommand."""
        raise NotImplementedError(self.commit_handler)

    def reset_handler(self, cmd):
        """Process a ResetCommand."""
        raise NotImplementedError(self.reset_handler)

    def tag_handler(self, cmd):
        """Process a TagCommand."""
        raise NotImplementedError(self.tag_handler)


class CommitHandler(object):
    """Base class for commit handling.
    
    Subclasses should override the pre_*, post_* and *_handler
    methods as appropriate.
    """

    def __init__(self, command):
        self.command = command

    def process(self):
        self.pre_process_files()
        for fc in self.command.file_iter():
            try:
                handler = self.__class__.__dict__[fc.name + "_handler"]
            except KeyError:
                raise errors.MissingHandler(fc.name)
            else:
                handler(self, fc)
        self.post_process_files()

    def pre_process_files(self):
        """Prepare for committing."""
        pass

    def post_process_files(self):
        """Save the revision."""
        pass

    def modify_handler(self, filecmd):
        """Handle a filemodify command."""
        raise NotImplementedError(self.modify_handler)

    def delete_handler(self, filecmd):
        """Handle a filedelete command."""
        raise NotImplementedError(self.delete_handler)

    def copy_handler(self, filecmd):
        """Handle a filecopy command."""
        raise NotImplementedError(self.copy_handler)

    def rename_handler(self, filecmd):
        """Handle a filerename command."""
        raise NotImplementedError(self.rename_handler)

    def deleteall_handler(self, filecmd):
        """Handle a filedeleteall command."""
        raise NotImplementedError(self.deleteall_handler)
