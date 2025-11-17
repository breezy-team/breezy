# Copyright (C) 2009 Canonical Ltd
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

from io import BytesIO

from . import osutils, progress, trace
from .i18n import gettext
from .ui import ui_factory


class RenameMap:
    """Determine a mapping of renames."""

    def __init__(self, tree):
        self.tree = tree
        self.edge_hashes = {}

    @staticmethod
    def iter_edge_hashes(lines):
        """Iterate through the hashes of line pairs (which make up an edge).

        The hash is truncated using a modulus to avoid excessive memory
        consumption by the hitscount dict.  A modulus of 10Mi means that the
        maximum number of keys is 10Mi.  (Keys are normally 32 bits, e.g.
        4 Gi)
        """
        modulus = 1024 * 1024 * 10
        for n in range(len(lines)):
            yield hash(tuple(lines[n : n + 2])) % modulus

    def add_edge_hashes(self, lines, tag):
        """Update edge_hashes to include the given lines.

        :param lines: The lines to update the hashes for.
        :param tag: A tag uniquely associated with these lines (i.e. file-id)
        """
        for my_hash in self.iter_edge_hashes(lines):
            self.edge_hashes.setdefault(my_hash, set()).add(tag)

    def add_file_edge_hashes(self, tree, file_ids):
        """Update to reflect the hashes for files in the tree.

        :param tree: The tree containing the files.
        :param file_ids: A list of file_ids to perform the updates for.
        """
        desired_files = [(tree.id2path(f), f) for f in file_ids]
        with ui_factory.nested_progress_bar() as task:
            for num, (file_id, contents) in enumerate(
                tree.iter_files_bytes(desired_files)
            ):
                task.update(gettext("Calculating hashes"), num, len(file_ids))
                s = BytesIO()
                s.writelines(contents)
                s.seek(0)
                self.add_edge_hashes(s.readlines(), file_id)

    def hitcounts(self, lines):
        """Count the number of hash hits for each tag, for the given lines.

        Hits are weighted according to the number of tags the hash is
        associated with; more tags means that the hash is less rare and should
        tend to be ignored.
        :param lines: The lines to calculate hashes of.
        :return: a dict of {tag: hitcount}
        """
        hits = {}
        for my_hash in self.iter_edge_hashes(lines):
            tags = self.edge_hashes.get(my_hash)
            if tags is None:
                continue
            taglen = len(tags)
            for tag in tags:
                if tag not in hits:
                    hits[tag] = 0
                hits[tag] += 1.0 / taglen
        return hits

    def get_all_hits(self, paths):
        """Find all the hit counts for the listed paths in the tree.

        :return: A list of tuples of count, path, file_id.
        """
        all_hits = []
        with ui_factory.nested_progress_bar() as task:
            for num, path in enumerate(paths):
                task.update(gettext("Determining hash hits"), num, len(paths))
                hits = self.hitcounts(self.tree.get_file_lines(path))
                all_hits.extend((v, path, k) for k, v in hits.items())
        return all_hits

    def file_match(self, paths):
        """Return a mapping from file_ids to the supplied paths."""
        return self._match_hits(self.get_all_hits(paths))

    @staticmethod
    def _match_hits(hit_list):
        """Using a hit list, determine a path-to-fileid map.

        The hit list is a list of (count, path, file_id), where count is a
        (possibly float) number, with higher numbers indicating stronger
        matches.
        """
        seen_file_ids = set()
        path_map = {}
        for _count, path, file_id in sorted(hit_list, reverse=True):
            if path in path_map or file_id in seen_file_ids:
                continue
            path_map[path] = file_id
            seen_file_ids.add(file_id)
        return path_map

    def get_required_parents(self, matches):
        """Return a dict of all file parents that must be versioned.

        The keys are the required parents and the values are sets of their
        children.
        """
        required_parents = {}
        for path in matches:
            while True:
                child = path
                path = osutils.dirname(path)
                if self.tree.is_versioned(path):
                    break
                required_parents.setdefault(path, []).append(child)
        require_ids = {}
        for parent, children in required_parents.items():
            child_file_ids = set()
            for child in children:
                file_id = matches.get(child)
                if file_id is not None:
                    child_file_ids.add(file_id)
            require_ids[parent] = child_file_ids
        return require_ids

    def match_parents(self, required_parents, missing_parents):
        """Map parent directories to file-ids.

        This is done by finding similarity between the file-ids of children of
        required parent directories and the file-ids of children of missing
        parent directories.
        """
        all_hits = []
        for file_id, file_id_children in missing_parents.items():
            for path, path_children in required_parents.items():
                hits = len(path_children.intersection(file_id_children))
                if hits > 0:
                    all_hits.append((hits, path, file_id))
        return self._match_hits(all_hits)

    def _find_missing_files(self, basis):
        missing_files = set()
        missing_parents = {}
        candidate_files = set()
        with ui_factory.nested_progress_bar() as task:
            iterator = self.tree.iter_changes(basis, want_unversioned=True, pb=task)
            for change in iterator:
                if change.kind[1] is None and change.versioned[1]:
                    if not self.tree.has_filename(
                        self.tree.id2path(change.parent_id[0])
                    ):
                        missing_parents.setdefault(change.parent_id[0], set()).add(
                            change.file_id
                        )
                    if change.kind[0] == "file":
                        missing_files.add(change.file_id)
                    else:
                        # other kinds are not handled
                        pass
                if change.versioned == (False, False):
                    if self.tree.is_ignored(change.path[1]):
                        continue
                    if change.kind[1] == "file":
                        candidate_files.add(change.path[1])
                    if change.kind[1] == "directory":
                        for _dir, children in self.tree.walkdirs(change.path[1]):
                            for child in children:
                                if child[2] == "file":
                                    candidate_files.add(child[0])
        return missing_files, missing_parents, candidate_files

    @classmethod
    def guess_renames(klass, from_tree, to_tree, dry_run=False):
        """Guess which files to rename, and perform the rename.

        We assume that unversioned files and missing files indicate that
        versioned files have been renamed outside of Bazaar.

        :param from_tree: A tree to compare from
        :param to_tree: A write-locked working tree.
        """
        required_parents = {}
        with ui_factory.nested_progress_bar() as task:
            pp = progress.ProgressPhase("Guessing renames", 4, task)
            with from_tree.lock_read():
                rn = klass(to_tree)
                pp.next_phase()
                missing_files, missing_parents, candidate_files = (
                    rn._find_missing_files(from_tree)
                )
                pp.next_phase()
                rn.add_file_edge_hashes(from_tree, missing_files)
            pp.next_phase()
            matches = rn.file_match(candidate_files)
            parents_matches = matches
            while len(parents_matches) > 0:
                required_parents = rn.get_required_parents(parents_matches)
                parents_matches = rn.match_parents(required_parents, missing_parents)
                matches.update(parents_matches)
            pp.next_phase()
            delta = rn._make_inventory_delta(matches)
            for old, new, _file_id, _entry in delta:
                trace.note(gettext("{0} => {1}").format(old, new))
            if not dry_run:
                to_tree.add(required_parents)
                to_tree.apply_inventory_delta(delta)

    def _make_inventory_delta(self, matches):
        delta = []
        file_id_matches = {f: p for p, f in matches.items()}
        file_id_query = []
        for f in matches.values():
            try:
                file_id_query.append(self.tree.id2path(f))
            except errors.NoSuchId:
                pass
        for old_path, entry in self.tree.iter_entries_by_dir(
            specific_files=file_id_query
        ):
            new_path = file_id_matches[entry.file_id]
            parent_path, new_name = osutils.split(new_path)
            parent_id = matches.get(parent_path)
            if parent_id is None:
                parent_id = self.tree.path2id(parent_path)
                if parent_id is None:
                    _added, ignored = self.tree.smart_add([parent_path], recurse=False)
                    if len(ignored) > 0 and ignored[0] == parent_path:
                        continue
                    else:
                        parent_id = self.tree.path2id(parent_path)
            if entry.name == new_name and entry.parent_id == parent_id:
                continue
            new_entry = entry.copy()
            new_entry.parent_id = parent_id
            new_entry.name = new_name
            delta.append((old_path, new_path, new_entry.file_id, new_entry))
        return delta
