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

from bzrlib.plugins.git import (
    ids,
    model,
    )


class GitRepository(repository.Repository):
    """An adapter to git repositories for bzr."""

    # To make bzrlib happy
    _serializer = None

    def __init__(self, gitdir, lockfiles):
        self.bzrdir = gitdir
        self.control_files = lockfiles
        gitdirectory = gitdir.transport.local_abspath('.')
        self._git = model.GitModel(gitdirectory)
        self._revision_cache = {}
        self._blob_cache = {}
        self._entry_revision_cache = {}
        self._inventory_cache = {}

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

    def get_inventory_xml(self, revision_id):
        """See Repository.get_inventory_xml()."""
        return bzrlib.xml5.serializer_v5.write_inventory_to_string(
            self.get_inventory(revision_id))

    def get_inventory_sha1(self, revision_id):
        """Get the sha1 for the XML representation of an inventory.

        :param revision_id: Revision id of the inventory for which to return 
         the SHA1.
        :return: XML string
        """

        return osutils.sha_string(self.get_inventory_xml(revision_id))

    def get_revision_xml(self, revision_id):
        """Return the XML representation of a revision.

        :param revision_id: Revision for which to return the XML.
        :return: XML string
        """
        return bzrlib.xml5.serializer_v5.write_revision_to_string(
            self.get_revision(revision_id))

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

    def _get_blob(self, git_id):
        try:
            return self._blob_cache[git_id]
        except KeyError:
            blob = self._git.cat_file('blob', git_id)
            # print "fetched blob:", git_id
            self._blob_cache[git_id] = blob
            return blob

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
        inv.git_file_data = {}
        for file_id in sorted(inv.git_ids.iterkeys()):
            git_id = inv.git_ids[file_id]
            entry = inv[file_id]
            self._set_entry_text_info(inv, entry, git_id)
        for file_id in sorted(inv.git_ids.iterkeys()):
            git_id = inv.git_ids[file_id]
            entry = inv[file_id]
            path = inv.id2path(file_id)
            self._set_entry_revision(entry, revision_id, path, git_id)
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
        lines = self._get_blob(git_id)
        entry.text_size = sum(len(line) for line in lines)
        entry.text_sha1 = osutils.sha_strings(lines)
        if entry.kind == 'symlink':
            entry.symlink_target = ''.join(lines)
        inv.git_file_data[entry.file_id] = lines

    def _get_file_revision(self, revision_id, path):
        lines = self._git.rev_list(
            [ids.convert_revision_id_bzr_to_git(revision_id)],
            max_count=1, topo_order=True, paths=[path])
        [line] = lines
        result = ids.convert_revision_id_git_to_bzr(line[:-1])
        # print "fetched file revision", line[:-1], path
        return result

    # The various version of _get_entry_revision can be tested by pulling from
    # the git repo of git itself. First pull up to r700, then r702 to
    # reproduce the RevisionNotPresent errors.

    def _set_entry_revision_unoptimized(self, entry, revid, path, git_id):
        # This is unusably slow and will lead to recording a few unnecessary
        # duplicated file texts. But it seems to be consistent enough to let
        # pulls resume without causing RevisionNotPresent errors.
        entry.revision = self._get_file_revision(revid, path)

    def _set_entry_revision_optimized1(self, entry, revid, path, git_id):
        # This is much faster, produces fewer unique file texts, but will
        # cause RevisionNotPresent errors when resuming pull.
        #
        # Oops, this does not account for changes in executable bit. That is
        # probably why it produces fewer unique texts.
        cached = self._entry_revision_cache.get((revid, path, git_id))
        if cached is not None:
            entry.revision = cached
            return
        revision = self.get_revision(revid)
        for parent_id in revision.parent_ids:
            entry_rev = self._entry_revision_cache.get((parent_id, path, git_id))
            if entry_rev is not None:
                break
        else:
            entry_rev = self._get_file_revision(revid, path)
        self._entry_revision_cache[(revid, path, git_id)] = entry_rev
        entry.revision = entry_rev

    def _set_entry_revision_optimized2(self, entry, revid, path, git_id):
        # This is slower than the previous one, and does not appear to have a
        # subtantially different effect. Same number of unique texts, same
        # RevisionNotPresent error.
        #
        # Oops, this does not account for changes in executable bit. That is
        # probably why it produces fewer unique texts.
        cached = self._entry_revision_cache.get((revid, path, git_id))
        if cached is not None:
            entry.revision = cached
            return
        revision = self.get_revision(revid)
        parent_hits = []
        for parent_id in revision.parent_ids:
            entry_rev = self._entry_revision_cache.get((parent_id, path, git_id))
            if entry_rev is not None:
                parent_hits.append(entry_rev)
        if len(parent_hits) == len(revision.parent_ids) and len(set(parent_hits)) == 1:
            entry_rev = parent_hits[0]
        else:
            entry_rev = self._get_file_revision(revid, path)
        self._entry_revision_cache[(revid, path, git_id)] = entry_rev
        entry.revision = entry_rev

    _original_get_inventory = get_inventory
    def _get_inventory_caching(self, revid):
        if revid in self._inventory_cache:
            return self._inventory_cache[revid]
        inv = self._original_get_inventory(revid)
        self._inventory_cache[revid] = inv
        return inv

    def _set_entry_revision_optimized3(self, entry, revid, path, git_id):
        # Depends on _get_inventory_caching.

        # Set the revision of directories to the current revision. It's not
        # accurate, but we cannot compare directory contents from here.
        if entry.kind == 'directory':
            entry.revision = revid
            return
        # Build ancestral inventories by walking parents depth first. Ideally
        # this should be done in an inter-repository, where already imported
        # data can be used as reference.
        current_revid = revid
        revision = self.get_revision(revid)
        pending_revids = list(reversed(revision.parent_ids))
        while pending_revids:
            revid = pending_revids.pop()
            if revid in self._inventory_cache:
                continue
            # Not in cache, ensure parents are in cache first.
            pending_revids.append(revid)
            revision = self.get_revision(revid)
            for parent_id in reversed(revision.parent_ids):
                if parent_id not in self._inventory_cache:
                    pending_revids.extend(reversed(revision.parent_ids))
                    break
            else:
                # All parents are in cache, we can now build this inventory.
                revid = pending_revids.pop()
                self.get_inventory(revid) # populate cache
        # We now have all ancestral inventories in the cache. Get entries by
        # the same file_id in parent inventories, and use the revision of the
        # first one that has the same text_sha1 and executable bit.
        revision = self.get_revision(current_revid)
        for revid in revision.parent_ids:
            inventory = self.get_inventory(revid)
            if entry.file_id in inventory:
                parent_entry = inventory[entry.file_id]
                if (parent_entry.text_sha1 == entry.text_sha1
                        and parent_entry.executable == entry.executable):
                    entry.revision = parent_entry.revision
                    return
        # If we get here, that means we found no matching parent entry, use
        # the current revision.
        entry.revision = current_revid

    def _set_entry_revision_optimized4(self, entry, revid, path, git_id):
        # Same as optimized1, but uses the executable bit in the cache index.
        # That appears to have the same behaviour as the unoptimized version.
        cached = self._entry_revision_cache.get(
            (revid, path, git_id, entry.executable))
        if cached is not None:
            entry.revision = cached
            return
        revision = self.get_revision(revid)
        for parent_id in revision.parent_ids:
            entry_rev = self._entry_revision_cache.get(
                (parent_id, path, git_id, entry.executable))
            if entry_rev is not None:
                break
        else:
            entry_rev = self._get_file_revision(revid, path)
        self._entry_revision_cache[
            (revid, path, git_id, entry.executable)] = entry_rev
        entry.revision = entry_rev

    def _set_entry_revision_optimized5(self, entry, revid, path, git_id):
        # Same as optimized4, but makes get_inventory non-reentrant, and uses
        # a more structured cache.
        #
        # cache[revision][path, git_id, executable] -> revision
        #
        # If a revision is in the cache, we assume it contains entries for the
        # whole inventory. So if all parent revisions are in the cache, but no
        # parent entry is present, then the entry revision is the current
        # revision. That amortizes the number of git calls for large pulls to
        # zero.
        cached = self._entry_revision_cache.get(revid, {}).get(
            (path, git_id, entry.executable))
        if cached is not None:
            entry.revision = cached
            return
        revision = self.get_revision(revid)
        all_parents_in_cache = True
        for parent_id in revision.parent_ids:
            if parent_id not in self._entry_revision_cache:
                all_parents_in_cache = False
                continue
            entry_rev = self._entry_revision_cache[parent_id].get(
                (path, git_id, entry.executable))
            if entry_rev is not None:
                break
        else:
            if all_parents_in_cache:
                entry_rev = revid
            else:
                entry_rev = self._get_file_revision(revid, path)
        self._entry_revision_cache.setdefault(
            revid, {})[(path, git_id, entry.executable)] = entry_rev
        entry.revision = entry_rev

    _set_entry_revision = _set_entry_revision_optimized5
    #get_inventory = _get_inventory_caching


def escape_file_id(file_id):
    return file_id.replace('_', '__').replace(' ', '_s')

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
        return self._inventory.git_file_data[file_id]
        
        obj_id = self._inventory.git_ids[file_id]
        assert obj_id is not None, (
            "git_id must not be None: %r" % (self._inventory[file_id],))
        return self._repository._git.cat_file('blob', obj_id)
