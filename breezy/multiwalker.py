# Copyright (C) 2005-2011 Canonical Ltd
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

"""Walk multiple trees simultaneously."""

from . import errors, osutils


class MultiWalker:
    """Walk multiple trees simultaneously, getting combined results."""

    # Note: This could be written to not assume you can do out-of-order
    #       lookups. Instead any nodes that don't match in all trees could be
    #       marked as 'deferred', and then returned in the final cleanup loop.
    #       For now, I think it is "nicer" to return things as close to the
    #       "master_tree" order as we can.

    def __init__(self, master_tree, other_trees):
        """Create a new MultiWalker.

        All trees being walked must implement "iter_entries_by_dir()", such
        that they yield (path, object) tuples, where that object will have a
        '.file_id' member, that can be used to check equality.

        :param master_tree: All trees will be 'slaved' to the master_tree such
            that nodes in master_tree will be used as 'first-pass' sync points.
            Any nodes that aren't in master_tree will be merged in a second
            pass.
        :param other_trees: A list of other trees to walk simultaneously.
        """
        self._master_tree = master_tree
        self._other_trees = other_trees

        # Keep track of any nodes that were properly processed just out of
        # order, that way we don't return them at the end, we don't have to
        # track *all* processed file_ids, just the out-of-order ones
        self._out_of_order_processed = set()

    @staticmethod
    def _step_one(iterator):
        """Step an iter_entries_by_dir iterator.

        :return: (has_more, path, ie)
            If has_more is False, path and ie will be None.
        """
        try:
            path, ie = next(iterator)
        except StopIteration:
            return False, None, None
        else:
            return True, path, ie

    @staticmethod
    def _lt_path_by_dirblock(path1, path2):
        """Compare two paths based on what directory they are in.

        This generates a sort order, such that all children of a directory are
        sorted together, and grandchildren are in the same order as the
        children appear. But all grandchildren come after all children.

        :param path1: first path
        :param path2: the second path
        :return: negative number if ``path1`` comes first,
            0 if paths are equal
            and a positive number if ``path2`` sorts first
        """
        # Shortcut this special case
        if path1 == path2:
            return False
        # This is stolen from _dirstate_helpers_py.py, only switching it to
        # Unicode objects. Consider using encode_utf8() and then using the
        # optimized versions, or maybe writing optimized unicode versions.
        if not isinstance(path1, str):
            raise TypeError(
                f"'path1' must be a unicode string, not {type(path1)}: {path1!r}"
            )
        if not isinstance(path2, str):
            raise TypeError(
                f"'path2' must be a unicode string, not {type(path2)}: {path2!r}"
            )
        return MultiWalker._path_to_key(path1) < MultiWalker._path_to_key(path2)

    @staticmethod
    def _path_to_key(path):
        dirname, basename = osutils.split(path)
        return (dirname.split("/"), basename)

    def _lookup_by_master_path(self, extra_entries, other_tree, master_path):
        return self._lookup_by_file_id(
            extra_entries, other_tree, self._master_tree.path2id(master_path)
        )

    def _lookup_by_file_id(self, extra_entries, other_tree, file_id):
        """Lookup an inventory entry by file_id.

        This is called when an entry is missing in the normal order.
        Generally this is because a file was either renamed, or it was
        deleted/added. If the entry was found in the inventory and not in
        extra_entries, it will be added to self._out_of_order_processed

        :param extra_entries: A dictionary of {file_id: (path, ie)}.  This
            should be filled with entries that were found before they were
            used. If file_id is present, it will be removed from the
            dictionary.
        :param other_tree: The Tree to search, in case we didn't find the entry
            yet.
        :param file_id: The file_id to look for
        :return: (path, ie) if found or (None, None) if not present.
        """
        if file_id in extra_entries:
            return extra_entries.pop(file_id)
        try:
            cur_path = other_tree.id2path(file_id)
        except errors.NoSuchId:
            cur_path = None
        if cur_path is None:
            return (None, None)
        else:
            self._out_of_order_processed.add(file_id)
            cur_ie = next(other_tree.iter_entries_by_dir(specific_files=[cur_path]))[1]
            return (cur_path, cur_ie)

    def iter_all(self):
        """Match up the values in the different trees."""
        yield from self._walk_master_tree()
        self._finish_others()
        yield from self._walk_others()

    def _walk_master_tree(self):
        """First pass, walk all trees in lock-step.

        When we are done, all nodes in the master_tree will have been
        processed. _other_walkers, _other_entries, and _others_extra will be
        set on 'self' for future processing.
        """
        # This iterator has the most "inlining" done, because it tends to touch
        # every file in the tree, while the others only hit nodes that don't
        # match.
        master_iterator = self._master_tree.iter_entries_by_dir()

        other_walkers = [other.iter_entries_by_dir() for other in self._other_trees]
        other_entries = [self._step_one(walker) for walker in other_walkers]
        # Track extra nodes in the other trees
        others_extra = [{} for _ in range(len(self._other_trees))]

        master_has_more = True
        step_one = self._step_one
        out_of_order_processed = self._out_of_order_processed

        while master_has_more:
            (master_has_more, path, master_ie) = step_one(master_iterator)
            if not master_has_more:
                break

            other_values = []
            other_values_append = other_values.append
            next_other_entries = []
            next_other_entries_append = next_other_entries.append
            for idx, (other_has_more, other_path, other_ie) in enumerate(other_entries):
                if not other_has_more:
                    other_values_append(
                        self._lookup_by_master_path(
                            others_extra[idx], self._other_trees[idx], path
                        )
                    )
                    next_other_entries_append((False, None, None))
                elif master_ie.file_id == other_ie.file_id:
                    # This is the critical code path, as most of the entries
                    # should match between most trees.
                    other_values_append((other_path, other_ie))
                    next_other_entries_append(step_one(other_walkers[idx]))
                else:
                    # This walker did not match, step it until it either
                    # matches, or we know we are past the current walker.
                    other_walker = other_walkers[idx]
                    other_extra = others_extra[idx]
                    while other_has_more and self._lt_path_by_dirblock(
                        other_path, path
                    ):
                        other_file_id = other_ie.file_id
                        if other_file_id not in out_of_order_processed:
                            other_extra[other_file_id] = (other_path, other_ie)
                        other_has_more, other_path, other_ie = step_one(other_walker)
                    if other_has_more and other_ie.file_id == master_ie.file_id:
                        # We ended up walking to this point, match and step
                        # again
                        other_values_append((other_path, other_ie))
                        other_has_more, other_path, other_ie = step_one(other_walker)
                    else:
                        # This record isn't in the normal order, see if it
                        # exists at all.
                        other_values_append(
                            self._lookup_by_master_path(
                                other_extra, self._other_trees[idx], path
                            )
                        )
                    next_other_entries_append((other_has_more, other_path, other_ie))
            other_entries = next_other_entries

            # We've matched all the walkers, yield this datapoint
            yield path, master_ie.file_id, master_ie, other_values
        self._other_walkers = other_walkers
        self._other_entries = other_entries
        self._others_extra = others_extra

    def _finish_others(self):
        """Finish walking the other iterators, so we get all entries."""
        for idx, info in enumerate(self._other_entries):
            other_extra = self._others_extra[idx]
            (other_has_more, other_path, other_ie) = info
            while other_has_more:
                other_file_id = other_ie.file_id
                if other_file_id not in self._out_of_order_processed:
                    other_extra[other_file_id] = (other_path, other_ie)
                other_has_more, other_path, other_ie = self._step_one(
                    self._other_walkers[idx]
                )
        del self._other_entries

    def _walk_others(self):
        """Finish up by walking all the 'deferred' nodes."""
        # TODO: One alternative would be to grab all possible unprocessed
        #       file_ids, and then sort by path, and then yield them. That
        #       might ensure better ordering, in case a caller strictly
        #       requires parents before children.
        for idx, other_extra in enumerate(self._others_extra):
            others = sorted(other_extra.values(), key=lambda x: self._path_to_key(x[0]))
            for other_path, other_ie in others:
                file_id = other_ie.file_id
                # We don't need to check out_of_order_processed here, because
                # the lookup_by_file_id will be removing anything processed
                # from the extras cache
                other_extra.pop(file_id)
                other_values = [(None, None)] * idx
                other_values.append((other_path, other_ie))
                for alt_idx, alt_extra in enumerate(self._others_extra[idx + 1 :]):
                    alt_idx = alt_idx + idx + 1
                    alt_extra = self._others_extra[alt_idx]
                    alt_tree = self._other_trees[alt_idx]
                    other_values.append(
                        self._lookup_by_file_id(alt_extra, alt_tree, file_id)
                    )
                yield other_path, file_id, None, other_values
