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

"""Import processor that queries the input (and doesn't import)."""


from fastimport import (
    commands,
    processor,
    )


class QueryProcessor(processor.ImportProcessor):
    """An import processor that queries the input.

    No changes to the current repository are made.
    """

    known_params = commands.COMMAND_NAMES + commands.FILE_COMMAND_NAMES + \
        ['commit-mark']

    def __init__(self, params=None, verbose=False):
        processor.ImportProcessor.__init__(self, params, verbose)
        self.parsed_params = {}
        self.interesting_commit = None
        self._finished = False
        if params:
            if 'commit-mark' in params:
                self.interesting_commit = params['commit-mark']
                del params['commit-mark']
            for name, value in params.iteritems():
                if value == 1:
                    # All fields
                    fields = None
                else:
                    fields = value.split(',')
                self.parsed_params[name] = fields

    def pre_handler(self, cmd):
        """Hook for logic before each handler starts."""
        if self._finished:
            return
        if self.interesting_commit and cmd.name == 'commit':
            if cmd.mark == self.interesting_commit:
                print cmd.to_string()
                self._finished = True
            return
        if self.parsed_params.has_key(cmd.name):
            fields = self.parsed_params[cmd.name]
            str = cmd.dump_str(fields, self.parsed_params, self.verbose)
            print "%s" % (str,)

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

    def feature_handler(self, cmd):
        """Process a FeatureCommand."""
        feature = cmd.feature_name
        if feature not in commands.FEATURE_NAMES:
            self.warning("feature %s is not supported - parsing may fail"
                % (feature,))
