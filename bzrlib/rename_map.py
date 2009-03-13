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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


from cStringIO import StringIO
from bzrlib.ui import ui_factory
from bzrlib import osutils


class RenameMap(object):
    """Determine a mapping of renames."""

    def __init__(self):
        self.edge_hashes = {}

    @staticmethod
    def iter_edge_hashes(lines):
        """Iterate through the hashes of line pairs (which make up an edge)."""
        modulus = 1024 * 1024 * 10
        for n in range(len(lines)):
            yield hash(tuple(lines[n:n+2])) % modulus

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
        desired_files = [(f, f) for f in file_ids]
        task = ui_factory.nested_progress_bar()
        try:
            for num, (file_id, contents) in enumerate(
                tree.iter_files_bytes(desired_files)):
                task.update('Calculating hashes', num, len(file_ids))
                s = StringIO()
                s.writelines(contents)
                s.seek(0)
                self.add_edge_hashes(s.readlines(), file_id)
        finally:
            task.finished()

    def hitcounts(self, lines):
        """Count the number of hash hits for each tag, for the given lines.

        Hits are weighted according to the number of tags the hash is
        associated with; more tags means that the lines are not unique and
        should tend to be ignored.
        :param lines: The lines to calculate hashes of.
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

    def get_all_hits(self, tree, paths):
        """Find all the hit counts for the listed paths in a tree.

        :return: A list of tuples of count, path, file_id.
        """
        ordered_hits = []
        task = ui_factory.nested_progress_bar()
        try:
            for num, path in enumerate(paths):
                task.update('Determining hash hits', num, len(paths))
                my_file = tree.get_file(None, path=path)
                try:
                    hits = self.hitcounts(my_file.readlines())
                finally:
                    my_file.close()
                ordered_hits.extend((v, path, k) for k, v in hits.items())
        finally:
            task.finished()
        return ordered_hits

    def file_match(self, tree, paths):
        """Return a mapping from file_ids to the supplied paths."""
        seen_file_ids = set()
        seen_paths = set()
        path_map = {}
        ordered_hits = self.get_all_hits(tree, paths)
        ordered_hits.sort(reverse=True)
        for count, path, file_id in ordered_hits:
            if path in seen_paths or file_id in seen_file_ids:
                continue
            path_map[path] = file_id
            seen_paths.add(path)
            seen_file_ids.add(file_id)
        return path_map

    def get_required_parents(self, matches, tree):
        required_parents = {}
        for path in matches:
            while True:
                child = path
                path = osutils.dirname(path)
                if tree.path2id(path) is not None:
                    break
                required_parents.setdefault(path, []).append(child)
        return required_parents
