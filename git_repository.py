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

import os

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
    )
from bzrlib.transport import get_transport

from bzrlib.plugins.git import (
    cache,
    ids,
    model,
    )


cachedbs = {}


class GitRepository(repository.Repository):
    """An adapter to git repositories for bzr."""

    _serializer = None

    def __init__(self, gitdir, lockfiles):
        self.bzrdir = gitdir
        self.control_files = lockfiles
        self._git = self._make_model(gitdir.transport)
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
        self._format = GitFormat()

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


    @classmethod
    def _make_model(klass, transport):
        gitdirectory = transport.local_abspath('.')
        return model.GitModel(gitdirectory)


    def _ancestor_revisions(self, revision_ids):
        if revision_ids is not None:
            git_revisions = [gitrevid_from_bzr(r) for r in revision_ids]
        else:
            git_revisions = None
        for lines in self._git.ancestor_lines(git_revisions):
            yield self._parse_rev(lines)
        # print "fetched ancestors:", git_revisions

    def is_shared(self):
        return True

    def supports_rich_root(self):
        return False

    def get_revision_graph(self, revision_id=None):
        result = {}
        if revision_id is not None:
            param = [ids.convert_revision_id_bzr_to_git(revision_id)]
        else:
            param = None
        git_graph = self._git.get_revision_graph(param)
        # print "fetched revision graph:", param
        for node, parents in git_graph.iteritems():
            bzr_node = ids.convert_revision_id_git_to_bzr(node)
            bzr_parents = [ids.convert_revision_id_git_to_bzr(n)
                           for n in parents]
            result[bzr_node] = bzr_parents
        return result

    def get_revision_graph_with_ghosts(self, revision_ids=None):
        graph = deprecated_graph.Graph()
        if revision_ids is not None:
            revision_ids = [ids.convert_revision_id_bzr_to_git(r)
                            for r in revision_ids]
        git_graph = self._git.get_revision_graph(revision_ids)
        # print "fetched revision graph (ghosts):", revision_ids
        for node, parents in git_graph.iteritems():
            bzr_node = ids.convert_revision_id_git_to_bzr(node)
            bzr_parents = [ids.convert_revision_id_git_to_bzr(n)
                           for n in parents]

            graph.add_node(bzr_node, bzr_parents)
        return graph

    def get_ancestry(self, revision_id):
        param = [ids.convert_revision_id_bzr_to_git(revision_id)]
        git_ancestry = self._git.get_ancestry(param)
        # print "fetched ancestry:", param
        return [None] + [
            ids.convert_revision_id_git_to_bzr(git_id)
            for git_id in git_ancestry]

    def get_signature_text(self, revision_id):
        raise errors.NoSuchRevision(self, revision_id)


    def get_revision(self, revision_id):
        if revision_id in self._revision_cache:
            return self._revision_cache[revision_id]
        git_commit_id = ids.convert_revision_id_bzr_to_git(revision_id)
        raw = self._git.rev_list([git_commit_id], max_count=1, header=True)
        # print "fetched revision:", git_commit_id
        revision = self._parse_rev(raw)
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
    def _parse_rev(klass, raw):
        """Parse a single git revision.

        * The first line is the git commit id.
        * Following lines conform to the 'name value' structure, until the
          first blank line.
        * All lines after the first blank line and until the NULL line have 4
          leading spaces and constitute the commit message.

        :param raw: sequence of newline-terminated strings, its last item is a
            single NULL character.
        :return: a `bzrlib.revision.Revision` object.
        """
        parents = []
        message_lines = []
        in_message = False
        committer_was_set = False
        revision_id = ids.convert_revision_id_git_to_bzr(raw[0][:-1])
        rev = revision.Revision(revision_id)
        rev.inventory_sha1 = ""
        assert raw[-1] == '\x00', (
            "Last item of raw was not a single NULL character.")
        for line in raw[1:-1]:
            if in_message:
                assert line[:4] == '    ', (
                    "Unexpected line format in commit message: %r" % line)
                message_lines.append(line[4:])
                continue
            if line == '\n':
                in_message = True
                continue
            name, value = line[:-1].split(' ', 1)
            if name == 'parent':
                rev.parent_ids.append(
                    ids.convert_revision_id_git_to_bzr(value))
                continue
            if name == 'author':
                author, timestamp, timezone = value.rsplit(' ', 2)
                rev.properties['author'] = author
                rev.properties['git-author-timestamp'] = timestamp
                rev.properties['git-author-timezone'] = timezone
                if not committer_was_set:
                    rev.committer = author
                    rev.timestamp = float(timestamp)
                    rev.timezone = klass._parse_tz(timezone)
                continue
            if name == 'committer':
                committer_was_set = True
                committer, timestamp, timezone = value.rsplit(' ', 2)
                rev.committer = committer
                rev.timestamp = float(timestamp)
                rev.timezone = klass._parse_tz(timezone)
                continue
            if name == 'tree':
                rev.properties['git-tree-id'] = value
                continue

        rev.message = ''.join(message_lines)

        # XXX: That should not be needed, but current revision serializers do
        # not know how how to handle text that is illegal in xml. Note: when
        # this is fixed, we will need to rev up the revision namespace when
        # removing the escaping code. -- David Allouche 2007-12-30
        rev.message = escape_for_xml(rev.message)
        rev.committer = escape_for_xml(rev.committer)
        rev.properties['author'] = escape_for_xml(rev.properties['author'])

        return rev

    @classmethod
    def _parse_tz(klass, tz):
        """Parse a timezone specification in the [+|-]HHMM format.

        :return: the timezone offset in seconds.
        """
        assert len(tz) == 5
        sign = {'+': +1, '-': -1}[tz[0]]
        hours = int(tz[1:3])
        minutes = int(tz[3:])
        return sign * 60 * (60 * hours + minutes)

    def revision_trees(self, revids):
        for revid in revids:
            yield self.revision_tree(revid)

    def revision_tree(self, revision_id):
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
        if revision_id is None:
            revision_id = revision.NULL_REVISION
        if revision_id == revision.NULL_REVISION:
            return inventory.Inventory(
                revision_id=revision_id, root_id=None)

        # First pass at building the inventory. We need this one to get the
        # git ids, so we do not have to cache the entire tree text. Ideally,
        # this should be all we need to do.
        git_commit = ids.convert_revision_id_bzr_to_git(revision_id)
        git_inventory = self._git.get_inventory(git_commit)
        # print "fetched inventory:", git_commit
        inv = self._parse_inventory(revision_id, git_inventory)

        # Second pass at building the inventory. There we retrieve additional
        # data that bzrlib requires: text sizes, sha1s, symlink targets and
        # revisions that introduced inventory entries
        self._building_inventory = inv
        self._building_inventory.git_file_data = {}
        for file_id in sorted(inv.git_ids.iterkeys()):
            git_id = inv.git_ids[file_id]
            entry = inv[file_id]
            self._set_entry_text_info(inv, entry, git_id)
        for file_id in sorted(inv.git_ids.iterkeys()):
            git_id = inv.git_ids[file_id]
            entry = inv[file_id]
            path = inv.id2path(file_id)
            self._set_entry_revision(entry, revision_id, path, git_id)

        # At this point the entry_revision table is fully populated for this
        # revision. So record that we have inventory data for this revision.
        self.cachedb.execute(
            "insert or ignore into inventory (revid) values (?)",
            (revision_id,))
        self.cachedb.commit()
        self._building_inventory = None
        return inv

    @classmethod
    def _parse_inventory(klass, revid, git_inv):
        # For now, git inventory do not have root ids. It is not clear that we
        # can reliably support root ids. -- David Allouche 2007-12-28
        inv = inventory.Inventory(revision_id=revid)
        inv.git_ids = {}
        for perms, git_kind, git_id, path in git_inv:
            text_sha1 = None
            executable = False
            if git_kind == 'blob':
                if perms[1] == '0':
                    kind = 'file'
                    executable = bool(int(perms[-3:], 8) & 0111)
                elif perms[1] == '2':
                    kind = 'symlink'
                else:
                    raise AssertionError(
                        "Unknown blob kind, perms=%r." % (perms,))
            elif git_kind == 'tree':
                kind = 'directory'
            else:
                raise AssertionError(
                    "Unknown git entry kind: %r" % (git_kind,))
            # XXX: Maybe the file id should be prefixed by file kind, so when
            # the kind of path changes, the id changes too.
            # -- David Allouche 2007-12-28.
            file_id = escape_file_id(path.encode('utf-8'))
            entry = inv.add_path(path, kind, file_id=file_id)
            entry.executable = executable
            inv.git_ids[file_id] = git_id
        inv.root.revision = revid
        return inv

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


def escape_for_xml(message):
    """Replace xml-incompatible control characters."""
    # Copied from _escape_commit_message from bzr-svn.
    # -- David Allouche 2007-12-29.
    if message is None:
        return None
    import re
    # FIXME: RBC 20060419 this should be done by the revision
    # serialiser not by commit. Then we can also add an unescaper
    # in the deserializer and start roundtripping revision messages
    # precisely. See repository_implementations/test_repository.py
    
    # Python strings can include characters that can't be
    # represented in well-formed XML; escape characters that
    # aren't listed in the XML specification
    # (http://www.w3.org/TR/REC-xml/#NT-Char).
    message, _ = re.subn(
        u'[^\x09\x0A\x0D\u0020-\uD7FF\uE000-\uFFFD]+',
        lambda match: match.group(0).encode('unicode_escape'),
        message)
    return message


class GitRevisionTree(revisiontree.RevisionTree):

    def __init__(self, repository, revision_id):
        if revision_id is None:
            revision_id = revision.NULL_REVISION
        self._inventory = repository.get_inventory(revision_id)
        self._repository = repository
        self._revision_id = revision_id

    def get_file_lines(self, file_id):
        entry = self._inventory[file_id]
        if entry.kind == 'directory': return []
        git_id = self._inventory.git_ids[file_id]
        if git_id in self._inventory.git_file_data:
            return self._inventory.git_file_data[git_id]
        return self._repository._get_blob(git_id)


class GitFormat(object):

    supports_tree_reference = False
