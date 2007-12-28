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
    repository,
    revision,
    urlutils,
    )

from bzrlib.plugins.git import (
    ids,
    model,
    )


class GitRepository(repository.Repository):
    """An adapter to git repositories for bzr."""

    def __init__(self, gitdir, lockfiles):
        self.bzrdir = gitdir
        self.control_files = lockfiles
        gitdirectory = gitdir.transport.local_abspath('.')
        self._git = model.GitModel(gitdirectory)
        self._revision_cache = {}

    def _ancestor_revisions(self, revision_ids):
        if revision_ids is not None:
            git_revisions = [gitrevid_from_bzr(r) for r in revision_ids]
        else:
            git_revisions = None
        for lines in self._git.ancestor_lines(git_revisions):
            yield self._parse_rev(lines)

    def is_shared(self):
        return True

    def get_revision_graph(self, revision_id=None):
        result = {}
        if revision_id is not None:
            param = [ids.convert_revision_id_bzr_to_git(revision_id)]
        else:
            param = None
        for node, parents in self._git.ancestry(param).iteritems():
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
        for node, parents in self._git.ancestry(revision_ids).iteritems():
            bzr_node = ids.convert_revision_id_git_to_bzr(node)
            bzr_parents = [ids.convert_revision_id_git_to_bzr(n)
                           for n in parents]

            graph.add_node(bzr_node, bzr_parents)
        return graph

    def get_revision(self, revision_id):
        if revision_id in self._revision_cache:
            return self._revision_cache[revision_id]
        raw = self._git.rev_list(
            [ids.convert_revision_id_bzr_to_git(revision_id)],
            max_count=1, header=True)
        return self._parse_rev(raw)

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
        return float(sign * 60 * (60 * hours + minutes))

    def revision_trees(self, revids):
        for revid in revids:
            yield self.revision_tree(revid)

    def revision_tree(self, revision_id):
        return GitRevisionTree(self, revision_id)

    def get_inventory(self, revision_id):
        revision = self.get_revision(revision_id)
        inventory = GitInventory(revision_id)
        tree_id = revision.properties['git-tree-id']
        type_map = {'blob': 'file', 'tree': 'directory' }
        def get_inventory(tree_id, prefix):
            for perms, type, obj_id, name in self._git.get_inventory(tree_id):
                full_path = prefix + name
                if type == 'blob':
                    text_sha1 = obj_id
                else:
                    text_sha1 = None
                executable = (perms[-3] in ('1', '3', '5', '7'))
                entry = GitEntry(full_path, type_map[type], revision_id,
                                 text_sha1, executable)
                inventory.entries[full_path] = entry
                if type == 'tree':
                    get_inventory(obj_id, full_path+'/')
        get_inventory(tree_id, '')
        return inventory


class GitRevisionTree(object):

    def __init__(self, repository, revision_id):
        self.repository = repository
        self.revision_id = revision_id
        self.inventory = repository.get_inventory(revision_id)

    def get_file(self, file_id):
        return iterablefile.IterableFile(self.get_file_lines(file_id))

    def get_file_lines(self, file_id):
        obj_id = self.inventory[file_id].text_sha1
        return self.repository._git.cat_file('blob', obj_id)

    def is_executable(self, file_id):
        return self.inventory[file_id].executable


class GitInventory(object):

    def __init__(self, revision_id):
        self.entries = {}
        self.root = GitEntry('', 'directory', revision_id)
        self.entries[''] = self.root

    def __getitem__(self, key):
        return self.entries[key]

    def iter_entries(self):
        return iter(sorted(self.entries.items()))

    def iter_entries_by_dir(self):
        return self.iter_entries()

    def __len__(self):
        return len(self.entries)


class GitEntry(object):

    def __init__(self, path, kind, revision, text_sha1=None, executable=False,
                 text_size=None):
        self.path = path
        self.file_id = path
        self.kind = kind
        self.executable = executable
        self.name = osutils.basename(path)
        if path == '':
            self.parent_id = None
        else:
            self.parent_id = osutils.dirname(path)
        self.revision = revision
        self.symlink_target = None
        self.text_sha1 = text_sha1
        self.text_size = None

    def __repr__(self):
        return "GitEntry(%r, %r, %r, %r)" % (self.path, self.kind,
                                             self.revision, self.parent_id)


