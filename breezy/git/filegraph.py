# Copyright (C) 2011 Canonical Ltd
# Copyright (C) 2012-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""File graph access."""

import posixpath
import stat

from dulwich.errors import NotTreeError
from dulwich.object_store import tree_lookup_path
from dulwich.objects import SubmoduleEncountered

from ..revision import NULL_REVISION
from .mapping import encode_git_path


class GitFileLastChangeScanner:
    def __init__(self, repository):
        self.repository = repository
        self.store = self.repository._git.object_store

    def find_last_change_revision(self, path, commit_id):
        if not isinstance(path, bytes):
            raise TypeError(path)
        store = self.store
        while True:
            commit = store[commit_id]
            try:
                target_mode, target_sha = tree_lookup_path(
                    store.__getitem__, commit.tree, path
                )
            except SubmoduleEncountered as e:
                revid = self.repository.lookup_foreign_revision_id(commit_id)
                revtree = self.repository.revision_tree(revid)
                store = revtree._get_submodule_store(e.path)
                commit_id = e.sha
                path = posixpath.relpath(path, e.path)
            else:
                break
        if path == b"":
            target_mode = stat.S_IFDIR
        if target_mode is None:
            raise AssertionError(
                "sha {!r} for {!r} in {!r}".format(target_sha, path, commit_id)
            )
        while True:
            parent_commits = []
            for parent_id in commit.parents:
                try:
                    parent_commit = store[parent_id]
                    mode, sha = tree_lookup_path(
                        store.__getitem__, parent_commit.tree, path
                    )
                except (KeyError, NotTreeError):
                    continue
                else:
                    parent_commits.append(parent_commit)
                if path == b"":
                    mode = stat.S_IFDIR
                # Candidate found iff, mode or text changed,
                # or is a directory that didn't previously exist.
                if mode != target_mode or (
                    not stat.S_ISDIR(target_mode) and sha != target_sha
                ):
                    return (store, path, commit.id)
            if parent_commits == []:
                break
            commit = parent_commits[0]
        return (store, path, commit.id)


class GitFileParentProvider:
    def __init__(self, change_scanner):
        self.change_scanner = change_scanner
        self.store = self.change_scanner.repository._git.object_store

    def _get_parents(self, file_id, text_revision):
        commit_id, mapping = self.change_scanner.repository.lookup_bzr_revision_id(
            text_revision
        )
        try:
            path = encode_git_path(mapping.parse_file_id(file_id))
        except ValueError:
            raise KeyError(file_id)
        text_parents = []
        for commit_parent in self.store[commit_id].parents:
            try:
                (store, path, text_parent) = (
                    self.change_scanner.find_last_change_revision(path, commit_parent)
                )
            except KeyError:
                continue
            if text_parent not in text_parents:
                text_parents.append(text_parent)
        return tuple(
            [
                (file_id, self.change_scanner.repository.lookup_foreign_revision_id(p))
                for p in text_parents
            ]
        )

    def get_parent_map(self, keys):
        ret = {}
        for key in keys:
            (file_id, text_revision) = key
            if text_revision == NULL_REVISION:
                ret[key] = ()
                continue
            if not isinstance(file_id, bytes):
                raise TypeError(file_id)
            if not isinstance(text_revision, bytes):
                raise TypeError(text_revision)
            try:
                ret[key] = self._get_parents(file_id, text_revision)
            except KeyError:
                pass
        return ret
