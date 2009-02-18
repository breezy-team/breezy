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
#
# vim: fileencoding=utf-8

"""Core engine for the fast-export command."""

# TODO: if a new_git_branch below gets merged repeatedly, the tip of the branch
# is not updated (because the parent of commit is already merged, so we don't
# set new_git_branch to the previously used name)

import sys
from email.Utils import parseaddr

import bzrlib.branch
import bzrlib.revision
from bzrlib import errors as bazErrors
from bzrlib.trace import note, warning

from bzrlib.plugins.fastimport import commands, helpers, marks_file


class BzrFastExporter(object):

    def __init__(self, source, git_branch=None, checkpoint=-1,
        import_marks_file=None, export_marks_file=None):
        self.source = source
        self.outf = sys.stdout
        self.git_branch = git_branch
        self.checkpoint = checkpoint
        self.import_marks_file = import_marks_file
        self.export_marks_file = export_marks_file

        self.revid_to_mark = {}
        self.branch_names = {}
        if self.import_marks_file:
            marks_info = marks_file.import_marks(self.import_marks_file)
            if marks_info is not None:
                self.revid_to_mark = helpers.invert_dict(marks_info[0])
                self.branch_names = marks_info[1]
        
    def run(self):
        # Open the source
        self.branch = bzrlib.branch.Branch.open_containing(self.source)[0]

        # Export the data
        self.branch.repository.lock_read()
        try:
            for revid in self.branch.revision_history():
                self.emit_commit(revid, self.git_branch)
            if self.branch.supports_tags():
                self.emit_tags()
        finally:
            self.branch.repository.unlock()

        # Save the marks if requested
        self._save_marks()

    def note(self, message):
        note("bzr fast-export: %s" % message)

    def warning(self, message):
        warning("bzr fast-export: %s" % message)

    def print_cmd(self, cmd):
        self.outf.write("%r\n" % cmd)

    def _save_marks(self):
        if self.export_marks_file:
            revision_ids = helpers.invert_dict(self.revid_to_mark)
            marks_file.export_marks(self.export_marks_file, revision_ids,
                self.branch_names)
 
    def is_empty_dir(self, tree, path):
        path_id = tree.path2id(path)
        if path_id == None:
            warning("Skipping empty_dir detection, could not find path_id...")
            return False

        # Continue if path is not a directory
        if tree.kind(path_id) != 'directory':
            return False

        # Use treewalk to find the contents of our directory
        contents = list(tree.walkdirs(prefix=path))[0]
        if len(contents[1]) == 0:
            return True
        else:
            return False

    def emit_commit(self, revid, git_branch):
        if revid in self.revid_to_mark:
            return

        # Get the Revision object
        try:
            revobj = self.branch.repository.get_revision(revid)
        except bazErrors.NoSuchRevision:
            # This is a ghost revision. Mark it as not found and next!
            self.revid_to_mark[revid] = -1
            return
 
        # Checkpoint if it's time for that
        ncommits = len(self.revid_to_mark)
        if (self.checkpoint > 0 and ncommits
            and ncommits % self.checkpoint == 0):
            self.note("Exported %i commits - checkpointing" % ncommits)
            self._save_marks()
            self.print_cmd(commands.CheckpointCommand())

        # Emit parents
        nparents = len(revobj.parent_ids)
        if nparents:
            for parent in revobj.parent_ids:
                self.emit_commit(parent, git_branch)
            ncommits = len(self.revid_to_mark)

        # Get the primary parent
        if nparents == 0:
            if ncommits:
                # This is a parentless commit but it's not the first one
                # output. We need to create a new temporary branch for it
                # otherwise git-fast-import will assume the previous commit
                # was this one's parent
                git_branch = self._next_tmp_branch_name()
            parent = bzrlib.revision.NULL_REVISION
        else:
            parent = revobj.parent_ids[0]

        # Print the commit
        git_ref = 'refs/heads/%s' % (git_branch,)
        mark = self.revid_to_mark[revid] = ncommits + 1
        file_cmds = self._get_filecommands(parent, revid)
        self.print_cmd(self._get_commit_command(git_ref, mark, revobj,
            file_cmds))

    def _get_commit_command(self, git_ref, mark, revobj, file_cmds):
        # Get the committer and author info
        committer = revobj.committer
        name, email = parseaddr(committer)
        committer_info = (name, email, revobj.timestamp, revobj.timezone)
        author = revobj.get_apparent_author()
        if author != committer:
            name, email = parseaddr(author)
            author_info = (name, email, revobj.timestamp, revobj.timezone)
        else:
            author_info = None

        # Get the parents in terms of marks
        non_ghost_parents = []
        for p in revobj.parent_ids:
            parent_mark = self.revid_to_mark[p]
            if parent_mark != -1:
                non_ghost_parents.append(":%s" % parent_mark)
        if non_ghost_parents:
            from_ = non_ghost_parents[0]
            merges = non_ghost_parents[1:]
        else:
            from_ = None
            merges = None

        # Build and return the result
        return commands.CommitCommand(git_ref, mark, author_info,
            committer_info, revobj.message, from_, merges, iter(file_cmds))

    def _get_revision_trees(self, parent, revision_id):
        try:
            tree_old = self.branch.repository.revision_tree(parent)
        except bazErrors.UnexpectedInventoryFormat:
            self.warning("Parent is malformed - diffing against previous parent")
            # We can't find the old parent. Let's diff against his parent
            pp = self.branch.repository.get_revision(parent)
            tree_old = self.branch.repository.revision_tree(pp.parent_ids[0])
        tree_new = None
        try:
            tree_new = self.branch.repository.revision_tree(revision_id)
        except bazErrors.UnexpectedInventoryFormat:
            # We can't really do anything anymore
            self.warning("Revision %s is malformed - skipping", revision_id)
        return tree_old, tree_new

    def _get_filecommands(self, parent, revision_id):
        """Get the list of FileCommands for the changes between two revisions."""
        tree_old, tree_new = self._get_revision_trees(parent, revision_id)
        changes = tree_new.changes_from(tree_old)

        # Make "modified" have 3-tuples, as added does
        my_modified = [ x[0:3] for x in changes.modified ]

        # We have to keep track of previous renames in this commit
        file_cmds = []
        renamed = []
        for (oldpath, newpath, id_, kind,
                text_modified, meta_modified) in changes.renamed:
            if (self.is_empty_dir(tree_old, oldpath)):
                self.note("Skipping empty dir %s in rev %s" % (oldpath,
                    revision_id))
                continue
            for old, new in renamed:
                # If a previous rename is found in this rename, we should
                # adjust the path
                if old in oldpath:
                    oldpath = oldpath.replace(old + "/", new + "/") 
                    self.note("Fixing recursive rename for %s" % oldpath)
            renamed.append([oldpath, newpath])
            file_cmds.append(commands.FileRenameCommand(oldpath, newpath))
            if text_modified or meta_modified:
                my_modified.append((newpath, id_, kind))

        # Record deletes
        for path, id_, kind in changes.removed:
            for old, new in renamed:
                path = path.replace(old + "/", new + "/")
            file_cmds.append(commands.FileDeleteCommand(path))

        # Map kind changes to a delete followed by an add
        for path, id_, kind1, kind2 in changes.kind_changed:
            for old, new in renamed:
                path = path.replace(old + "/", new + "/")
            file_cmds.append(commands.FileDeleteCommand(path))
            my_modified.append((path, id_, kind2))

        # Record modifications
        for path, id_, kind in changes.added + my_modified:
            if kind == 'file':
                text = tree_new.get_file_text(id_)
                file_cmds.append(commands.FileModifyCommand(path, 'file',
                    tree_new.is_executable(id_), None, text))
            elif kind == 'symlink':
                file_cmds.append(commands.FileModifyCommand(path, 'symlink',
                    False, None, tree_new.get_symlink_target(id_)))
            else:
                # Should we do something here for importers that
                # can handle directory and tree-reference changes?
                continue
        return file_cmds

    def emit_tags(self):
        for tag, revid in self.branch.tags.get_tag_dict().items():
            try:
                mark = self.revid_to_mark[revid]
            except KeyError:
                self.warning('not creating tag %r pointing to non-existent '
                    'revision %s' % (tag, revid))
            else:
                git_ref = 'refs/tags/%s' % tag
                self.print_cmd(commands.ResetCommand(git_ref, ":" + mark))

    def _next_tmp_branch_name(self):
        """Return a unique branch name. The name will start with "tmp"."""
        prefix = 'tmp'
        if prefix not in self.branch_names:
            self.branch_names[prefix] = 0
        else:
            self.branch_names[prefix] += 1
            prefix = '%s.%d' % (prefix, self.branch_names[prefix])
        return prefix
