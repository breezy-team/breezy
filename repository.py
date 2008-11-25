# Copyright (C) 2007 Canonical Ltd
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

"""An adapter between a Git Repository and a Bazaar Branch"""

import git
import os
import time

import bzrlib
from bzrlib import (
    deprecated_graph,
    errors,
    inventory,
    osutils,
    repository,
    revision,
    revisiontree,
    urlutils,
    versionedfile,
    )
from bzrlib.foreign import (
        ForeignRevision,
        )
from bzrlib.transport import get_transport

from bzrlib.plugins.git.foreign import (
    ForeignRepository,
    versionedfiles,
    )
from bzrlib.plugins.git.mapping import default_mapping


class GitRepository(ForeignRepository):
    """An adapter to git repositories for bzr."""

    _serializer = None

    def __init__(self, gitdir, lockfiles):
        self.base = gitdir.root_transport.base
        self.bzrdir = gitdir
        self.control_files = lockfiles
        self._git = gitdir._git
        self.texts = None
        self.signatures = versionedfiles.VirtualSignatureTexts(self)
        self.revisions = versionedfiles.VirtualRevisionTexts(self)
        self._format = GitFormat()
        self._fallback_repositories = []

    def _all_revision_ids(self):
        if self._git.heads == []:
            return set()
        ret = set()
        skip = 0
        max_count = 1000
        cms = None
        while cms != []:
            cms = self._git.commits("--all", max_count=max_count, skip=skip)
            skip += max_count
            ret.update([default_mapping.revision_id_foreign_to_bzr(cm.id) for cm in cms])
        return ret

    def is_shared(self):
        return True

    def supports_rich_root(self):
        return False

    #def get_revision_delta(self, revision_id):
    #    parent_revid = self.get_revision(revision_id).parent_ids[0]
    #    diff = self._git.diff(ids.convert_revision_id_bzr_to_git(parent_revid),
    #                   ids.convert_revision_id_bzr_to_git(revision_id))

    def get_ancestry(self, revision_id):
        revision_id = revision.ensure_null(revision_id)
        ret = []
        if revision_id != revision.NULL_REVISION:
            skip = 0
            max_count = 1000
            cms = None
            while cms != []:
                cms = self._git.commits(self.lookup_git_revid(revision_id, default_mapping), max_count=max_count, skip=skip)
                skip += max_count
                ret += [default_mapping.revision_id_foreign_to_bzr(cm.id) for cm in cms]
        return [None] + ret

    def get_signature_text(self, revision_id):
        raise errors.NoSuchRevision(self, revision_id)

    def has_signature_for_revision_id(self, revision_id):
        return False

    def get_parent_map(self, revision_ids):
        ret = {}
        for revid in revision_ids:
            if revid == revision.NULL_REVISION:
                ret[revid] = ()
            else:
                commit = self._git.commit(self.lookup_git_revid(revid, default_mapping))
                ret[revid] = tuple([default_mapping.revision_id_foreign_to_bzr(p.id) for p in commit.parents])
        return ret

    def lookup_git_revid(self, bzr_revid, mapping):
        try:
            return mapping.revision_id_bzr_to_foreign(bzr_revid)
        except errors.InvalidRevisionId:
            raise errors.NoSuchRevision(bzr_revid, self)

    def get_revision(self, revision_id):
        git_commit_id = self.lookup_git_revid(revision_id, default_mapping)
        commit = self._git.commit(git_commit_id)
        # print "fetched revision:", git_commit_id
        revision = self._parse_rev(commit, default_mapping)
        return revision

    def has_revision(self, revision_id):
        try:
            self.get_revision(revision_id)
        except NoSuchRevision:
            return False
        else:
            return True

    def get_revisions(self, revisions):
        return [self.get_revision(r) for r in revisions]

    @classmethod
    def _parse_rev(klass, commit, mapping):
        """Convert a git commit to a bzr revision.

        :return: a `bzrlib.revision.Revision` object.
        """
        rev = ForeignRevision(commit.id, mapping, mapping.revision_id_foreign_to_bzr(commit.id))
        rev.parent_ids = tuple([mapping.revision_id_foreign_to_bzr(p.id) for p in commit.parents])
        rev.message = commit.message.decode("utf-8", "replace")
        rev.committer = str(commit.committer).decode("utf-8", "replace")
        rev.properties['author'] = str(commit.author).decode("utf-8", "replace")
        rev.timestamp = time.mktime(commit.committed_date)
        rev.timezone = 0
        return rev

    def revision_trees(self, revids):
        for revid in revids:
            yield self.revision_tree(revid)

    def revision_tree(self, revision_id):
        revision_id = revision.ensure_null(revision_id)

        if revision_id == revision.NULL_REVISION:
            inv = inventory.Inventory(root_id=None)
            inv.revision_id = revision_id
            return revisiontree.RevisionTree(self, inv, revision_id)

        return GitRevisionTree(self, revision_id)

    def get_inventory(self, revision_id):
        assert revision_id != None
        return self.revision_tree(revision_id).inventory

    def set_make_working_trees(self, trees):
        pass


def escape_file_id(file_id):
    return file_id.replace('_', '__').replace(' ', '_s')


def unescape_file_id(file_id):
    return file_id.replace("_s", " ").replace("__", "_")


class GitRevisionTree(revisiontree.RevisionTree):

    def __init__(self, repository, revision_id):
        self._repository = repository
        self.revision_id = revision_id
        git_id = repository.lookup_git_revid(revision_id, default_mapping)
        self.tree = repository._git.commit(git_id).tree
        self._inventory = inventory.Inventory(revision_id=revision_id)
        self._inventory.root.revision = revision_id
        self._build_inventory(self.tree, self._inventory.root, "")

    def get_revision_id(self):
        return self.revision_id

    def get_file_text(self, file_id):
        entry = self._inventory[file_id]
        if entry.kind == 'directory': return ""
        return self._repository._git.blob(entry.text_id).data

    def _build_inventory(self, tree, ie, path):
        assert isinstance(path, str)
        for b in tree.contents:
            basename = b.name.decode("utf-8")
            if path == "":
                child_path = b.name
            else:
                child_path = urlutils.join(path, b.name)
            file_id = escape_file_id(child_path.encode('utf-8'))
            if b.mode[0] == '0':
                child_ie = inventory.InventoryDirectory(file_id, basename, ie.file_id)
            elif b.mode[0] == '1':
                if b.mode[1] == '0':
                    child_ie = inventory.InventoryFile(file_id, basename, ie.file_id)
                    child_ie.text_sha1 = osutils.sha_string(b.data)
                elif b.mode[1] == '2':
                    child_ie = inventory.InventoryLink(file_id, basename, ie.file_id)
                    child_ie.text_sha1 = osutils.sha_string("")
                else:
                    raise AssertionError(
                        "Unknown file kind, perms=%r." % (b.mode,))
                child_ie.text_id = b.id
                child_ie.text_size = b.size
            else:
                raise AssertionError(
                    "Unknown blob kind, perms=%r." % (b.mode,))
            child_ie.executable = bool(int(b.mode[3:], 8) & 0111)
            child_ie.revision = self.revision_id
            self._inventory.add(child_ie)
            if b.mode[0] == '0':
                self._build_inventory(b, child_ie, child_path)


class GitFormat(object):

    supports_tree_reference = False

    def get_format_description(self):
        return "Git Repository"
