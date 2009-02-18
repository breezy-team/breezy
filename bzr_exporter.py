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

# There is a bug in git 1.5.4.3 and older by which unquoting a string consumes
# one extra character. Set this variable to True to work-around it. It only
# happens when renaming a file whose name contains spaces and/or quotes, and
# the symptom is:
#   % git-fast-import
#   fatal: Missing space after source: R "file 1.txt" file 2.txt
# http://git.kernel.org/?p=git/git.git;a=commit;h=c8744d6a8b27115503565041566d97c21e722584
GIT_FAST_IMPORT_NEEDS_EXTRA_SPACE_AFTER_QUOTE = False

# TODO: if a new_git_branch below gets merged repeteadly, the tip of the branch
# is not updated (because the parent of commit is already merged, so we don't
# set new_git_branch to the previously used name)

import os
import re
import sys
from email.Utils import quote, parseaddr

import bzrlib.branch
import bzrlib.revision
from bzrlib import errors as bazErrors
from bzrlib.trace import note, warning

from bzrlib.plugins.fastimport import helpers, marks_file


class BzrFastExporter(object):

    def __init__(self, source, git_branch=None, checkpoint=-1,
        import_marks_file=None, export_marks_file=None):
        self.source = source
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
            self.revmap = self.branch.get_revision_id_to_revno_map()
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

        try:
            revobj = self.branch.repository.get_revision(revid)
        except bazErrors.NoSuchRevision:
            # This is a ghost revision. Mark it as not found and next!
            self.revid_to_mark[revid] = -1
            return
 
        ncommits = len(self.revid_to_mark)
        if (self.checkpoint > 0 and ncommits
            and ncommits % self.checkpoint == 0):
            self.note("Exported %i commits; forcing checkpoint" % ncommits)
            self._save_marks()
            sys.stdout.write("checkpoint\n")

        mark = self.revid_to_mark[revid] = len(self.revid_to_mark) + 1
        nparents = len(revobj.parent_ids)

        # This is a parentless commit. We need to create a new branch
        # otherwise git-fast-import will assume the previous commit
        # was this one's parent
        for parent in revobj.parent_ids:
            self.emit_commit(parent, git_branch)

        if nparents == 0:
            git_branch = self.next_available_branch_name()
            parent = bzrlib.revision.NULL_REVISION
        else:
            parent = revobj.parent_ids[0]

        stream = 'commit refs/heads/%s\nmark :%d\n' % (git_branch, mark)

        rawdate = '%d %s' % (int(revobj.timestamp), '%+03d%02d' % (
                    revobj.timezone / 3600, (revobj.timezone / 60) % 60))

        author = revobj.get_apparent_author()
        if author != revobj.committer:
            stream += 'author %s %s\n' % (
                self.name_with_angle_brackets(author), rawdate)

        stream += 'committer %s %s\n' % (
                self.name_with_angle_brackets(revobj.committer), rawdate)

        message = revobj.message.encode('utf-8')
        stream += 'data %d\n%s\n' % (len(message), revobj.message)

        didFirstParent = False
        for p in revobj.parent_ids:
            if self.revid_to_mark[p] == -1:
                self.note("This is a merge with a ghost-commit. Skipping "
                    "second parent.")
                continue

            if p == parent and not didFirstParent:
                s = "from"
                didFirstParent = True
            else:
                s = "merge"
            stream += '%s :%d\n' % (s, self.revid_to_mark[p])

        sys.stdout.write(stream.encode('utf-8'))

        ##

        try:
            tree_old = self.branch.repository.revision_tree(parent)
        except bazErrors.UnexpectedInventoryFormat:
            self.note("Parent is malformed.. diffing against previous parent")
            # We can't find the old parent. Let's diff against his parent
            pp = self.branch.repository.get_revision(parent)
            tree_old = self.branch.repository.revision_tree(pp.parent_ids[0])
        
        tree_new = None
        try:
            tree_new = self.branch.repository.revision_tree(revobj.revision_id)
        except bazErrors.UnexpectedInventoryFormat:
            # We can't really do anything anymore
            self.note("This commit is malformed. Skipping diff")
            return

        changes = tree_new.changes_from(tree_old)

        # make "modified" have 3-tuples, as added does
        my_modified = [ x[0:3] for x in changes.modified ]

        # We have to keep track of previous renames in this commit
        renamed = []
        for (oldpath, newpath, id_, kind,
                text_modified, meta_modified) in changes.renamed:
            
            if (self.is_empty_dir(tree_old, oldpath)):
                self.note("Skipping empty dir %s in rev %s" % (oldpath,
                    revobj.revision_id))
                continue

            for old, new in renamed:
                # If a previous rename is found in this rename, we should
                # adjust the path
                if old in oldpath:
                    oldpath = oldpath.replace(old + "/", new + "/") 
                    self.note("Fixing recursive rename for %s" % oldpath)

            renamed.append([oldpath, newpath])

            sys.stdout.write('R %s %s\n' % (self.my_quote(oldpath, True),
                                                    self.my_quote(newpath)))
            if text_modified or meta_modified:
                my_modified.append((newpath, id_, kind))

        for path, id_, kind in changes.removed:
            for old, new in renamed:
                path = path.replace(old + "/", new + "/")
            sys.stdout.write('D %s\n' % (self.my_quote(path),))

        for path, id_, kind1, kind2 in changes.kind_changed:
            for old, new in renamed:
                path = path.replace(old + "/", new + "/")
            sys.stdout.write('D %s\n' % (self.my_quote(path),))
            my_modified.append((path, id_, kind2))

        for path, id_, kind in changes.added + my_modified:
            if kind in ('file', 'symlink'):
                entry = tree_new.inventory[id_]
                if kind == 'file':
                    mode = entry.executable and '755' or '644'
                    text = tree_new.get_file_text(id_)
                else: # symlink
                    mode = '120000'
                    text = entry.symlink_target
            else:
                continue

            sys.stdout.write('M %s inline %s\n' % (mode, self.my_quote(path)))
            sys.stdout.write('data %d\n%s\n' % (len(text), text))

    def emit_tags(self):
        for tag, revid in self.branch.tags.get_tag_dict().items():
            try:
                mark = self.revid_to_mark[revid]
            except KeyError:
                self.warning('not creating tag %r pointing to non-existent '
                    'revision %s' % (tag, revid))
            else:
                # According to git-fast-import(1), the extra LF is optional here;
                # however, versions of git up to 1.5.4.3 had a bug by which the LF
                # was needed. Always emit it, since it doesn't hurt and maintains
                # compatibility with older versions.
                # http://git.kernel.org/?p=git/git.git;a=commit;h=655e8515f279c01f525745d443f509f97cd805ab
                sys.stdout.write('reset refs/tags/%s\nfrom :%d\n\n' % (
                    tag, mark))

    ##

    def my_quote(self, string, quote_spaces=False):
        """Encode path in UTF-8 and quote it if necessary.

        A quote is needed if path starts with a quote character ("). If
        :param quote_spaces: is True, the path will be quoted if it contains any
        space (' ') characters.
        """
        # TODO: escape LF
        string = string.encode('utf-8')
        if string.startswith('"') or quote_spaces and ' ' in string:
            return '"%s"%s' % (quote(string),
                    GIT_FAST_IMPORT_NEEDS_EXTRA_SPACE_AFTER_QUOTE and ' ' or '')
        else:
            return string

    def name_with_angle_brackets(self, string):
        """Ensure there is a part with angle brackets in string."""
        name, email = parseaddr(string)
        if not name:
            if '@' in email or '<' in string:
                return '<%s>' % (email,)
            else:
                return '%s <>' % (string,)
        else:
            return '%s <%s>' % (name, email)

    def next_available_branch_name(self):
        """Return an unique branch name. The name will start with "tmp".
        """
        prefix = 'tmp'

        if prefix not in self.branch_names:
            self.branch_names[prefix] = 0
        else:
            self.branch_names[prefix] += 1
            prefix = '%s.%d' % (prefix, self.branch_names[prefix])

        return prefix
