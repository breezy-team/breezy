# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>

# Based on a similar file written for bzr-svn:
# Copyright (C) 2009 Lukas Lalinsky <lalinsky@gmail.com>

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
from bzrlib import (
    branch as _mod_branch,
    errors,
    merge_directive,
    osutils,
    revision as _mod_revision
    )


class GitDiffWriter(object):

    def __init__(self, repository, base_revision_id):
        self.repository = repository
        self.base_revision_id = base_revision_id
        self.tree_rev_info = {}

    def get_git_rev_info(self, tree):
        if tree in self.tree_rev_info:
            return self.tree_rev_info[tree]
        revision_id = tree.get_revision_id()
        if revision_id == self.base_revision_id:
            rev_info = '(working copy)'
        elif _mod_revision.is_null(revision_id):
            rev_info = '(revision 0)'
        else:
            info = self.repository.lookup_revision_id(revision_id)
            rev_info = '(revision %d)' % info[0][2]
        self.tree_rev_info[tree] = rev_info
        return rev_info

    def diff_text(self, difftext, file_id, old_path, new_path, old_kind, new_kind):
        if 'file' not in (old_kind, new_kind):
            return difftext.CANNOT_DIFF
        from_file_id = to_file_id = file_id
        if old_kind == 'file':
            old_date = self.get_git_rev_info(difftext.old_tree)
        elif old_kind is None:
            old_date = None
            from_file_id = None
        else:
            return difftext.CANNOT_DIFF
        if new_kind == 'file':
            new_date = self.get_git_rev_info(difftext.new_tree)
        elif new_kind is None:
            new_date = None
            to_file_id = None
        else:
            return difftext.CANNOT_DIFF
        from_label = '%s%s\t%s' % (difftext.old_label, old_path, old_date or '(revision 0)')
        to_label = '%s%s\t%s' % (difftext.new_label, new_path, new_date or '(revision 0)')
        return difftext.diff_text(from_file_id, to_file_id, from_label, to_label)


class GitMergeDirective(merge_directive._BaseMergeDirective):

    def to_lines(self):
        return self.patch.splitlines(True)

    @classmethod
    def _generate_diff(cls, repository, target_repository, revision_id, ancestor_id):
        from bzrlib.diff import DiffText
        writer = GitDiffWriter(target_repository, revision_id)
        def DiffText_diff(self, file_id, old_path, new_path, old_kind, new_kind):
            return writer.diff_text(self, file_id, old_path, new_path, old_kind, new_kind)
        old_DiffText_diff = DiffText.diff
        DiffText.diff = DiffText_diff
        patch = merge_directive._BaseMergeDirective._generate_diff(
            repository, revision_id, ancestor_id)
        DiffText.diff = old_DiffText_diff
        return patch

    @classmethod
    def from_objects(cls, repository, revision_id, time, timezone,
                     target_branch, local_target_branch=None,
                     public_branch=None, message=None):
        submit_branch = _mod_branch.Branch.open(target_branch)
        if submit_branch.get_parent() is not None:
            submit_branch = _mod_branch.Branch.open(submit_branch.get_parent())

        submit_branch.lock_read()
        try:
            submit_revision_id = submit_branch.last_revision()
            submit_revision_id = _mod_revision.ensure_null(submit_revision_id)
            repository.fetch(submit_branch.repository, submit_revision_id)
            graph = repository.get_graph()
            ancestor_id = graph.find_unique_lca(revision_id,
                                                submit_revision_id)
            patch = cls._generate_diff(repository, submit_branch.repository,
                                    revision_id, ancestor_id)
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
