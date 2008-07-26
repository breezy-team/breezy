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
from bzrlib.transport import get_transport

from bzrlib.plugins.git import (
    cache,
    ids,
    )


cachedbs = {}


class GitRepository(repository.Repository):
    """An adapter to git repositories for bzr."""

    _serializer = None

    def __init__(self, gitdir, lockfiles):
        self.base = gitdir.root_transport.base
        self.bzrdir = gitdir
        self.control_files = lockfiles
        self._git = git.repo.Repo(gitdir.root_transport.local_abspath("."))
        self._revision_cache = {}
        self._blob_cache = {}
        self._blob_info_cache = {}
        cache_dir = cache.create_cache_dir()
        cachedir_transport = get_transport(cache_dir)
        cache_file = os.path.join(cache_dir, 'cache-%s' % ids.NAMESPACE)
        if not cachedbs.has_key(cache_file):
            cachedbs[cache_file] = cache.sqlite3.connect(cache_file)
        self.cachedb = cachedbs[cache_file]
        self._init_cachedb()
        self.texts = None
        self.signatures = versionedfile.VirtualSignatureTexts(self)
        self.revisions = None
        self._format = GitFormat()
        self._fallback_repositories = []

    def _init_cachedb(self):
        self.cachedb.executescript("""
        create table if not exists inventory (
            revid blob);
        create unique index if not exists inventory_revid
            on inventory (revid);
        create table if not exists entry_revision (
            inventory blob,
            path blob,
            gitid blob,
            executable integer,
            revision blob);
        create unique index if not exists entry_revision_revid_path
            on entry_revision (inventory, path);
        """)
        self.cachedb.commit()

    def is_shared(self):
        return True

    def supports_rich_root(self):
        return False

    def get_ancestry(self, revision_id):
        param = [ids.convert_revision_id_bzr_to_git(revision_id)]
        git_ancestry = self._git.get_ancestry(param)
        # print "fetched ancestry:", param
        return [None] + [
            ids.convert_revision_id_git_to_bzr(git_id)
            for git_id in git_ancestry]

    def get_signature_text(self, revision_id):
        raise errors.NoSuchRevision(self, revision_id)

    def has_signature_for_revision_id(self, revision_id):
        return False

    def get_parent_map(self, revision_ids):
        ret = {}
        for revid in revision_ids:
            commit = self._git.commit(ids.convert_revision_id_bzr_to_git(revid))
            ret[revid] = tuple([ids.convert_revision_id_git_to_bzr(p.id) for p in commit.parents])
        return ret

    def get_revision(self, revision_id):
        if revision_id in self._revision_cache:
            return self._revision_cache[revision_id]
        git_commit_id = ids.convert_revision_id_bzr_to_git(revision_id)
        commit = self._git.commit(git_commit_id)
        # print "fetched revision:", git_commit_id
        revision = self._parse_rev(commit)
        self._revision_cache[revision_id] = revision
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
    def _parse_rev(klass, commit):
        """Convert a git commit to a bzr revision.

        :return: a `bzrlib.revision.Revision` object.
        """
        rev = revision.Revision(ids.convert_revision_id_git_to_bzr(commit.id))
        rev.parent_ids = tuple([ids.convert_revision_id_git_to_bzr(p.id) for p in commit.parents])
        rev.inventory_sha1 = ""
        rev.message = commit.message
        rev.committer = str(commit.committer)
        rev.properties['author'] = str(commit.author)
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

    def _fetch_blob(self, git_id):
        lines = self._git.cat_file('blob', git_id)
        # print "fetched blob:", git_id
        if self._building_inventory is not None:
            self._building_inventory.git_file_data[git_id] = lines
        return lines

    def _get_blob(self, git_id):
        try:
            return self._blob_cache[git_id]
        except KeyError:
            return self._fetch_blob(git_id)

    def _get_blob_caching(self, git_id):
        try:
            return self._blob_cache[git_id]
        except KeyError:
            lines = self._fetch_blob(git_id)
            self._blob_cache[git_id] = lines
            return lines

    def _get_blob_info(self, git_id):
        try:
            return self._blob_info_cache[git_id]
        except KeyError:
            lines = self._get_blob(git_id)
            size = sum(len(line) for line in lines)
            sha1 = osutils.sha_strings(lines)
            self._blob_info_cache[git_id] = (size, sha1)
            return size, sha1

    def get_inventory(self, revision_id):
        assert revision_id != None
        return self.revision_tree(revision_id).inventory

    def _set_entry_text_info(self, inv, entry, git_id):
        if entry.kind == 'directory':
            return
        size, sha1 = self._get_blob_info(git_id)
        entry.text_size = size
        entry.text_sha1 = sha1
        if entry.kind == 'symlink':
            lines = self._get_blob_caching(git_id)
            entry.symlink_target = ''.join(lines)

    def _get_file_revision(self, revision_id, path):
        lines = self._git.rev_list(
            [ids.convert_revision_id_bzr_to_git(revision_id)],
            max_count=1, topo_order=True, paths=[path])
        [line] = lines
        result = ids.convert_revision_id_git_to_bzr(line[:-1])
        # print "fetched file revision", line[:-1], path
        return result

    def _get_entry_revision_from_db(self, revid, path, git_id, executable):
        result = self.cachedb.execute(
            "select revision from entry_revision where"
            " inventory=? and path=? and gitid=? and executable=?",
            (revid, path, git_id, executable)).fetchone()
        if result is None:
            return None
        [revision] = result
        return revision

    def _set_entry_revision_in_db(self, revid, path, git_id, executable, revision):
        self.cachedb.execute(
            "insert into entry_revision"
            " (inventory, path, gitid, executable, revision)"
            " values (?, ?, ?, ?, ?)",
            (revid, path, git_id, executable, revision))

    def _all_inventories_in_db(self, revids):
        for revid in revids:
            result = self.cachedb.execute(
                "select count(*) from inventory where revid = ?",
                (revid,)).fetchone()
            if result is None:
                return False
        return True

    def _set_entry_revision(self, entry, revid, path, git_id):
        # If a revision is in the cache, we assume it contains entries for the
        # whole inventory. So if all parent revisions are in the cache, but no
        # parent entry is present, then the entry revision is the current
        # revision. That amortizes the number of _get_file_revision calls for
        # large pulls to a "small number".
        entry_rev = self._get_entry_revision_from_db(
            revid, path, git_id, entry.executable)
        if entry_rev is not None:
            entry.revision = entry_rev
            return

        revision = self.get_revision(revid)
        for parent_id in revision.parent_ids:
            entry_rev = self._get_entry_revision_from_db(
                parent_id, path, git_id, entry.executable)
            if entry_rev is not None:
                break
        else:
            if self._all_inventories_in_db(revision.parent_ids):
                entry_rev = revid
            else:
                entry_rev = self._get_file_revision(revid, path)
        self._set_entry_revision_in_db(
            revid, path, git_id, entry.executable, entry_rev)
        #self.cachedb.commit()
        entry.revision = entry_rev


def escape_file_id(file_id):
    return file_id.replace('_', '__').replace(' ', '_s')


class GitRevisionTree(revisiontree.RevisionTree):

    def __init__(self, repository, revision_id):
        self._repository = repository
        self.revision_id = revision_id
        git_id = ids.convert_revision_id_bzr_to_git(revision_id)
        self.tree = repository._git.commit(git_id).tree
        self._inventory = inventory.Inventory(revision_id=revision_id)
        self._inventory.root.revision = revision_id
        self._build_inventory(self.tree, self._inventory.root, "")

    def get_file_lines(self, file_id):
        entry = self._inventory[file_id]
        if entry.kind == 'directory': return []
        git_id = self._inventory.git_ids[file_id]
        if git_id in self._inventory.git_file_data:
            return self._inventory.git_file_data[git_id]
        return self._repository._get_blob(git_id)

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
                child_ie.text_size = b.size
            else:
                raise AssertionError(
                    "Unknown blob kind, perms=%r." % (b.mode,))
            child_ie.executable = bool(int(b.mode[3:], 8) & 0111)
            child_ie.revision = self.revision_id
            assert not basename in ie.children
            ie.children[basename] = child_ie
            if b.mode[0] == '0':
                self._build_inventory(b, child_ie, child_path)


class GitFormat(object):

    supports_tree_reference = False
