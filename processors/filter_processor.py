# Copyright (C) 2009 Canonical Ltd
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


from bzrlib import osutils
from bzrlib.trace import (
    warning,
    )
from fastimport import (
    commands,
    processor,
    )
from bzrlib.plugins.fastimport import (
    helpers,
    )


class FilterProcessor(processor.ImportProcessor):
    """An import processor that filters the input to include/exclude objects.

    No changes to the current repository are made.

    Here are the supported parameters:

    * include_paths - a list of paths that commits must change in order to
      be kept in the output stream

    * exclude_paths - a list of paths that should not appear in the output
      stream
    """

    known_params = [
        'include_paths',
        'exclude_paths',
        ]

    def pre_process(self):
        self.includes = self.params.get('include_paths')
        self.excludes = self.params.get('exclude_paths')
        # What's the new root, if any
        self.new_root = helpers.common_directory(self.includes)
        # Buffer of blobs until we know we need them: mark -> cmd
        self.blobs = {}
        # These are the commits we've output so far
        self.interesting_commits = set()
        # Map of commit-id to list of parents
        self.parents = {}

    def pre_handler(self, cmd):
        self.command = cmd
        # Should this command be included in the output or not?
        self.keep = False
        # Blobs to dump into the output before dumping the command itself
        self.referenced_blobs = []

    def post_handler(self, cmd):
        if not self.keep:
            return
        # print referenced blobs and the command
        for blob_id in self.referenced_blobs:
            self._print_command(self.blobs[blob_id])
        self._print_command(self.command)

    def progress_handler(self, cmd):
        """Process a ProgressCommand."""
        # These always pass through
        self.keep = True

    def blob_handler(self, cmd):
        """Process a BlobCommand."""
        # These never pass through directly. We buffer them and only
        # output them if referenced by an interesting command.
        self.blobs[cmd.id] = cmd
        self.keep = False

    def checkpoint_handler(self, cmd):
        """Process a CheckpointCommand."""
        # These always pass through
        self.keep = True

    def commit_handler(self, cmd):
        """Process a CommitCommand."""
        # These pass through if they meet the filtering conditions
        interesting_filecmds = self._filter_filecommands(cmd.file_iter)
        if interesting_filecmds:
            # If all we have is a single deleteall, skip this commit
            if len(interesting_filecmds) == 1 and isinstance(
                interesting_filecmds[0], commands.FileDeleteAllCommand):
                pass
            else:
                # Remember just the interesting file commands
                self.keep = True
                cmd.file_iter = iter(interesting_filecmds)

                # Record the referenced blobs
                for fc in interesting_filecmds:
                    if isinstance(fc, commands.FileModifyCommand):
                        if (fc.dataref is not None and
                            fc.kind != 'directory'):
                            self.referenced_blobs.append(fc.dataref)

                # Update from and merges to refer to commits in the output
                cmd.from_ = self._find_interesting_from(cmd.from_)
                cmd.merges = self._find_interesting_merges(cmd.merges)
                self.interesting_commits.add(cmd.id)

        # Keep track of the parents
        if cmd.from_ and cmd.merges:
            parents = [cmd.from_] + cmd.merges
        elif cmd.from_:
            parents = [cmd.from_]
        else:
            parents = None
        self.parents[":" + cmd.mark] = parents

    def reset_handler(self, cmd):
        """Process a ResetCommand."""
        if cmd.from_ is None:
            # We pass through resets that init a branch because we have to
            # assume the branch might be interesting.
            self.keep = True
        else:
            # Keep resets if they indirectly reference something we kept
            cmd.from_ = self._find_interesting_from(cmd.from_)
            self.keep = cmd.from_ is not None

    def tag_handler(self, cmd):
        """Process a TagCommand."""
        # Keep tags if they indirectly reference something we kept
        cmd.from_ = self._find_interesting_from(cmd.from_)
        self.keep = cmd.from_ is not None

    def feature_handler(self, cmd):
        """Process a FeatureCommand."""
        feature = cmd.feature_name
        if feature not in commands.FEATURE_NAMES:
            self.warning("feature %s is not supported - parsing may fail"
                % (feature,))
        # These always pass through
        self.keep = True

    def _print_command(self, cmd):
        """Wrapper to avoid adding unnecessary blank lines."""
        text = repr(cmd)
        self.outf.write(text)
        if not text.endswith("\n"):
            self.outf.write("\n")

    def _filter_filecommands(self, filecmd_iter):
        """Return the filecommands filtered by includes & excludes.
        
        :return: a list of FileCommand objects
        """
        if self.includes is None and self.excludes is None:
            return list(filecmd_iter())

        # Do the filtering, adjusting for the new_root
        result = []
        for fc in filecmd_iter():
            if (isinstance(fc, commands.FileModifyCommand) or
                isinstance(fc, commands.FileDeleteCommand)):
                if self._path_to_be_kept(fc.path):
                    fc.path = self._adjust_for_new_root(fc.path)
                else:
                    continue
            elif isinstance(fc, commands.FileDeleteAllCommand):
                pass
            elif isinstance(fc, commands.FileRenameCommand):
                fc = self._convert_rename(fc)
            elif isinstance(fc, commands.FileCopyCommand):
                fc = self._convert_copy(fc)
            else:
                warning("cannot handle FileCommands of class %s - ignoring",
                        fc.__class__)
                continue
            if fc is not None:
                result.append(fc)
        return result

    def _path_to_be_kept(self, path):
        """Does the given path pass the filtering criteria?"""
        if self.excludes and (path in self.excludes
                or osutils.is_inside_any(self.excludes, path)):
            return False
        if self.includes:
            return (path in self.includes
                or osutils.is_inside_any(self.includes, path))
        return True

    def _adjust_for_new_root(self, path):
        """Adjust a path given the new root directory of the output."""
        if self.new_root is None:
            return path
        elif path.startswith(self.new_root):
            return path[len(self.new_root):]
        else:
            return path

    def _find_interesting_parent(self, commit_ref):
        while True:
            if commit_ref in self.interesting_commits:
                return commit_ref
            parents = self.parents.get(commit_ref)
            if not parents:
                return None
            commit_ref = parents[0]

    def _find_interesting_from(self, commit_ref):
        if commit_ref is None:
            return None
        return self._find_interesting_parent(commit_ref)

    def _find_interesting_merges(self, commit_refs):
        if commit_refs is None:
            return None
        merges = []
        for commit_ref in commit_refs:
            parent = self._find_interesting_parent(commit_ref)
            if parent is not None:
                merges.append(parent)
        if merges:
            return merges
        else:
            return None

    def _convert_rename(self, fc):
        """Convert a FileRenameCommand into a new FileCommand.
        
        :return: None if the rename is being ignored, otherwise a
          new FileCommand based on the whether the old and new paths
          are inside or outside of the interesting locations.
          """
        old = fc.old_path
        new = fc.new_path
        keep_old = self._path_to_be_kept(old)
        keep_new = self._path_to_be_kept(new)
        if keep_old and keep_new:
            fc.old_path = self._adjust_for_new_root(old)
            fc.new_path = self._adjust_for_new_root(new)
            return fc
        elif keep_old:
            # The file has been renamed to a non-interesting location.
            # Delete it!
            old = self._adjust_for_new_root(old)
            return commands.FileDeleteCommand(old)
        elif keep_new:
            # The file has been renamed into an interesting location
            # We really ought to add it but we don't currently buffer
            # the contents of all previous files and probably never want
            # to. Maybe fast-import-info needs to be extended to
            # remember all renames and a config file can be passed
            # into here ala fast-import?
            warning("cannot turn rename of %s into an add of %s yet" %
                (old, new))
        return None

    def _convert_copy(self, fc):
        """Convert a FileCopyCommand into a new FileCommand.
        
        :return: None if the copy is being ignored, otherwise a
          new FileCommand based on the whether the source and destination
          paths are inside or outside of the interesting locations.
          """
        src = fc.src_path
        dest = fc.dest_path
        keep_src = self._path_to_be_kept(src)
        keep_dest = self._path_to_be_kept(dest)
        if keep_src and keep_dest:
            fc.src_path = self._adjust_for_new_root(src)
            fc.dest_path = self._adjust_for_new_root(dest)
            return fc
        elif keep_src:
            # The file has been copied to a non-interesting location.
            # Ignore it!
            return None
        elif keep_dest:
            # The file has been copied into an interesting location
            # We really ought to add it but we don't currently buffer
            # the contents of all previous files and probably never want
            # to. Maybe fast-import-info needs to be extended to
            # remember all copies and a config file can be passed
            # into here ala fast-import?
            warning("cannot turn copy of %s into an add of %s yet" %
                (src, dest))
        return None
