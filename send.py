# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>

# Based on the original from bzr-svn:
# Copyright (C) 2009 Lukas Lalinsky <lalinsky@gmail.com>
# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import time
import bzrlib
from bzrlib import (
    branch as _mod_branch,
    diff as _mod_diff,
    merge_directive,
    osutils,
    revision as _mod_revision,
    )

from bzrlib.plugins.git import (
    version_info as bzr_git_version_info,
    )
from bzrlib.plugins.git.mapping import (
    object_mode,
    )
from bzrlib.plugins.git.object_store import (
    get_object_store,
    )

from cStringIO import StringIO
from dulwich.objects import (
    Blob,
    )


class GitDiffTree(_mod_diff.DiffTree):
    """Provides a text representation between two trees, formatted for svn."""

    def __init__(self, old_tree, new_tree, to_file, path_encoding='utf-8',
                 diff_text=None, extra_factories=None):
        super(GitDiffTree, self).__init__(old_tree, new_tree, to_file, path_encoding,
            diff_text, extra_factories)

    def _write_file_mode(self, old_mode, new_mode):
        if old_mode == new_mode:
            return
        if new_mode is not None:
            if old_mode is not None:
                self.to_file.write("old file mode %o\n" % old_mode)
            self.to_file.write("new file mode %o\n" % new_mode) 
        else:
            self.to_file.write("deleted file mode %o\n" % old_mode)

    def _get_rev(self, contents):
        if contents is None:
            return "0" * 7
        else:
            return Blob.from_string("".join(contents)).id[:7]

    def _write_contents_diff(self, old_path, old_mode, old_contents, new_path, new_mode, new_contents):
        if old_path is None:
            old_path = "/dev/null"
        else:
            old_path = "a/%s" % old_path
        if new_path is None:
            new_path = "/dev/null"
        else:
            new_path = "b/%s" % new_path
        self.to_file.write("diff --git %s %s\n" % (old_path, new_path))
        self._write_file_mode(old_mode, new_mode)
        old_rev = self._get_rev(old_contents)
        new_rev = self._get_rev(new_contents)
        self.to_file.write("index %s..%s %o\n" % (old_rev, new_rev, new_mode))
        _mod_diff.internal_diff(old_path, old_contents,
                                new_path, new_contents,
                                self.to_file)

    def _get_file_mode(self, tree, path, kind, executable):
        if path is None:
            return None
        return object_mode(kind, executable)

    def _show_diff(self, specific_files, extra_trees):
        iterator = self.new_tree.iter_changes(self.old_tree,
                                               specific_files=specific_files,
                                               extra_trees=extra_trees,
                                               require_versioned=True)
        has_changes = 0
        def get_encoded_path(path):
            if path is not None:
                return path.encode(self.path_encoding, "replace")
        for (file_id, paths, changed_content, versioned, parent, name, kind,
             executable) in iterator:
            # The root does not get diffed, and items with no known kind (that
            # is, missing) in both trees are skipped as well.
            if parent == (None, None) or kind == (None, None):
                continue
            oldpath, newpath = paths
            oldpath_encoded = get_encoded_path(paths[0])
            newpath_encoded = get_encoded_path(paths[1])
            old_present = (kind[0] is not None and versioned[0])
            if old_present is not None:
                old_contents = self.old_tree.get_file(file_id).readlines()
            else:
                old_contents = None
            new_present = (kind[1] is not None and versioned[1])
            if new_present is not None:
                new_contents = self.new_tree.get_file(file_id).readlines()
            else:
                new_contents = None
            renamed = (parent[0], name[0]) != (parent[1], name[1])
            old_mode = self._get_file_mode(self.old_tree, oldpath_encoded, kind[0], executable[0])
            new_mode = self._get_file_mode(self.new_tree, newpath_encoded, kind[1], executable[1])

            self._write_contents_diff(oldpath_encoded, old_mode, old_contents, 
                                      newpath_encoded, new_mode, new_contents)

            has_changes = (changed_content or renamed)

        return has_changes


class GitMergeDirective(merge_directive._BaseMergeDirective):

    def to_lines(self):
        return self.patch.splitlines(True)

    @classmethod
    def _generate_commit(cls, repository, revision_id, num, total):
        s = StringIO()
        store = get_object_store(repository)
        commit = store[store._lookup_revision_sha1(revision_id)]
        s.write("From %s %s\n" % (commit.id, time.ctime(commit.commit_time)))
        s.write("From: %s\n" % commit.author)
        s.write("Date: %s\n" % time.strftime("%a, %d %b %Y %H:%M:%S %Z"))
        s.write("Subject: [PATCH %d/%d] %s\n" % (num, total, commit.message))
        s.write("\n")
        s.write("---\n")
        s.write("TODO: Print diffstat\n")
        s.write("\n")
        try:
            lhs_parent = repository.get_revision(revision_id).parent_ids[0]
        except IndexError:
            lhs_parent = _mod_revision.NULL_REVISION
        tree_1 = repository.revision_tree(lhs_parent)
        tree_2 = repository.revision_tree(revision_id)
        differ = GitDiffTree.from_trees_options(tree_1, tree_2, s, 'utf8', None,
            'a/', 'b/', None)
        differ.show_diff(None, None)
        s.write("-- \n")
        s.write("bzr %s, bzr-git %d.%d.%d\n" % ((bzrlib.__version__, ) + bzr_git_version_info[:3]))
        summary = "%04d-%s" % (num, commit.message.splitlines()[0].replace(" ", "-"))
        return summary, s.getvalue()

    @classmethod
    def from_objects(cls, repository, revision_id, time, timezone,
                     target_branch, local_target_branch=None,
                     public_branch=None, message=None):
        submit_branch = _mod_branch.Branch.open(target_branch)
        submit_branch.lock_read()
        try:
            submit_revision_id = submit_branch.last_revision()
            repository.fetch(submit_branch.repository, submit_revision_id)
            summary, patch = cls._generate_commit(repository, revision_id, 1, 1)
        finally:
            submit_branch.unlock()
        return cls(revision_id, None, time, timezone, target_branch,
            patch, None, public_branch, message)


def send_git(branch, revision_id, submit_branch, public_branch,
              no_patch, no_bundle, message, base_revision_id):
    return GitMergeDirective.from_objects(
        branch.repository, revision_id, time.time(),
        osutils.local_time_offset(), submit_branch,
        public_branch=public_branch, message=message)
