# Copyright (C) 2007-2011 Canonical Ltd
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

"""Tag strategies.

These are contained within a branch and normally constructed
when the branch is opened.  Clients should typically do

  Branch.tags.add('name', 'value')
"""

import contextlib
import itertools
import re
import sys
from collections import defaultdict
from typing import Callable, Optional

from . import branch as _mod_branch
from . import errors
from .inter import InterObject
from .registry import Registry
from .revision import RevisionID

# NOTE: I was going to call this tags.py, but vim seems to think all files
# called tags* are ctags files... mbp 20070220.

TagSelector = Callable[[str], bool]
TagUpdates = dict[str, RevisionID]
TagConflict = tuple[str, bytes, bytes]


def _reconcile_tags(
    source_dict: dict[str, bytes],
    dest_dict: dict[str, bytes],
    overwrite: bool,
    selector: Optional[TagSelector],
) -> tuple[dict[str, RevisionID], TagUpdates, list[TagConflict]]:
    """Do a two-way merge of two tag dictionaries.

    * only in source => source value
    * only in destination => destination value
    * same definitions => that
    * different definitions => if overwrite is False, keep destination
      value and add to conflict list, otherwise use the source value

    :returns: (result_dict, updates,
        [(conflicting_tag, source_target, dest_target)])
    """
    conflicts = []
    updates = {}
    result = dict(dest_dict)  # copy
    for name, target in source_dict.items():
        if selector and not selector(name):
            continue
        if result.get(name) == target:
            pass
        elif name not in result or overwrite:
            updates[name] = target
            result[name] = target
        else:
            conflicts.append((name, target, result[name]))
    return result, updates, conflicts


class Tags:
    """Interface for managing tags in a branch."""

    def __init__(self, branch):
        """Initialize the Tags object.

        Args:
            branch: The branch this tags object is associated with.
        """
        self.branch = branch

    def get_tag_dict(self) -> dict[str, RevisionID]:
        """Return a dictionary mapping tags to revision ids."""
        raise NotImplementedError(self.get_tag_dict)

    def get_reverse_tag_dict(self) -> dict[RevisionID, set[str]]:
        """Returns a dict with revisions as keys
        and a list of tags for that revision as value.
        """
        d = self.get_tag_dict()
        rev = defaultdict(set)
        for key in d:
            rev[d[key]].add(key)
        return rev

    def merge_to(
        self,
        to_tags: "Tags",
        overwrite: bool = False,
        ignore_master: bool = False,
        selector: Optional[TagSelector] = None,
    ) -> tuple[TagUpdates, set[TagConflict]]:
        """Copy tags between repositories if necessary and possible.

        This method has common command-line behaviour about handling
        error cases.

        All new definitions are copied across, except that tags that already
        exist keep their existing definitions.

        :param to_tags: Branch to receive these tags
        :param overwrite: Overwrite conflicting tags in the target branch
        :param ignore_master: Do not modify the tags in the target's master
            branch (if any).  Default is false (so the master will be updated).

        :returns: Tuple with tag_updates and tag_conflicts.
            tag_updates is a dictionary with new tags, None is used for
            removed tags
            tag_conflicts is a set of tags that conflicted, each of which is
            (tagname, source_target, dest_target), or None if no copying was
            done.
        """
        intertags: InterTags = InterTags.get(self, to_tags)
        return intertags.merge(
            overwrite=overwrite, ignore_master=ignore_master, selector=selector
        )

    def set_tag(self, tag_name: str, revision: RevisionID) -> None:
        """Set a tag.

        :param tag_name: Tag name
        :param revision: Revision id
        :raise GhostTagsNotSupported: if revision is not present in
            the branch repository
        """
        raise NotImplementedError(self.set_tag)

    def lookup_tag(self, tag_name: str) -> RevisionID:
        """Look up a tag.

        :param tag_name: Tag to look up
        :raise NoSuchTag: Raised when tag does not exist
        :return: Matching revision id
        """
        raise NotImplementedError(self.lookup_tag)

    def delete_tag(self, tag_name: str) -> None:
        """Delete a tag.

        :param tag_name: Tag to delete
        :raise NoSuchTag: Raised when tag does not exist
        """
        raise NotImplementedError(self.delete_tag)

    def rename_revisions(self, rename_map: dict[RevisionID, RevisionID]) -> None:
        """Rename revisions in this tags dictionary.

        :param rename_map: Dictionary mapping old revids to new revids
        """
        reverse_tags = self.get_reverse_tag_dict()
        for revid, names in reverse_tags.items():
            if revid in rename_map:
                for name in names:
                    self.set_tag(name, rename_map[revid])

    def has_tag(self, tag_name: str) -> bool:
        """Check if a tag exists.

        Args:
            tag_name: Name of the tag to check.

        Returns:
            True if the tag exists, False otherwise.
        """
        return tag_name in self.get_tag_dict()


class DisabledTags(Tags):
    """Tag storage that refuses to store anything.

    This is used by older formats that can't store tags.
    """

    def _not_supported(self, *a, **k):
        raise errors.TagsNotSupported(self.branch)

    set_tag = _not_supported
    get_tag_dict = _not_supported
    _set_tag_dict = _not_supported
    lookup_tag = _not_supported
    delete_tag = _not_supported

    def merge_to(self, to_tags, overwrite=False, ignore_master=False, selector=None):
        """Merge tags to another tags object.

        For disabled tags, there are never any tags to copy.

        Args:
            to_tags: Target tags object.
            overwrite: Whether to overwrite existing tags.
            ignore_master: Whether to ignore master branch tags.
            selector: Optional tag selector function.

        Returns:
            Tuple of (updates, conflicts) - both empty for disabled tags.
        """
        # we never have anything to copy
        return {}, []

    def rename_revisions(self, rename_map):
        """Rename revisions in tags dictionary.

        For disabled tags, there are no tags to rename.

        Args:
            rename_map: Dictionary mapping old revids to new revids.
        """
        # No tags, so nothing to rename
        pass

    def get_reverse_tag_dict(self):
        """Get a reverse mapping from revision ids to tag names.

        For disabled tags, there are no tags so the mapping is empty.

        Returns:
            Empty dictionary.
        """
        # There aren't any tags, so the reverse mapping is empty.
        return {}


class InterTags(InterObject[Tags]):
    """Operations between sets of tags."""

    _optimisers = []
    """The available optimised InterTags types."""

    @classmethod
    def is_compatible(klass, source: Tags, target: Tags) -> bool:
        """Check if two Tags objects are compatible for operations.

        This is the default implementation that always returns True.

        Args:
            source: Source tags object.
            target: Target tags object.

        Returns:
            True if compatible, False otherwise.
        """
        # This is the default implementation
        return True

    def merge(
        self,
        overwrite: bool = False,
        ignore_master: bool = False,
        selector: Optional[TagSelector] = None,
    ) -> tuple[TagUpdates, set[TagConflict]]:
        """Copy tags between repositories if necessary and possible.

        This method has common command-line behaviour about handling
        error cases.

        All new definitions are copied across, except that tags that already
        exist keep their existing definitions.

        :param to_tags: Branch to receive these tags
        :param overwrite: Overwrite conflicting tags in the target branch
        :param ignore_master: Do not modify the tags in the target's master
            branch (if any).  Default is false (so the master will be updated).
        :param selector: Callback that determines whether a tag should be
            copied. It should take a tag name and as argument and return a
            boolean.

        :returns: Tuple with tag_updates and tag_conflicts.
            tag_updates is a dictionary with new tags, None is used for
            removed tags
            tag_conflicts is a set of tags that conflicted, each of which is
            (tagname, source_target, dest_target), or None if no copying was
            done.
        """
        with contextlib.ExitStack() as stack:
            if self.source.branch == self.target.branch:
                return {}, set()
            if not self.source.branch.supports_tags():
                # obviously nothing to copy
                return {}, set()
            source_dict = self.source.get_tag_dict()
            if not source_dict:
                # no tags in the source, and we don't want to clobber anything
                # that's in the destination
                return {}, set()
            # We merge_to both master and child individually.
            #
            # It's possible for master and child to have differing sets of
            # tags, in which case it's possible to have different sets of
            # conflicts.  We report the union of both conflict sets.  In
            # that case it's likely the child and master have accepted
            # different tags from the source, which may be a surprising result, but
            # the best we can do in the circumstances.
            #
            # Ideally we'd improve this API to report the different conflicts
            # more clearly to the caller, but we don't want to break plugins
            # such as bzr-builddeb that use this API.
            stack.enter_context(self.target.branch.lock_write())
            master = None if ignore_master else self.target.branch.get_master_branch()
            if master is not None:
                stack.enter_context(master.lock_write())
            updates, conflicts = self._merge_to(
                self.target, source_dict, overwrite, selector=selector
            )
            if master is not None:
                extra_updates, extra_conflicts = self._merge_to(
                    master.tags, source_dict, overwrite, selector=selector
                )
                updates.update(extra_updates)
                conflicts += extra_conflicts
        # We use set() to remove any duplicate conflicts from the master
        # branch.
        return updates, set(conflicts)

    @classmethod
    def _merge_to(cls, to_tags, source_dict, overwrite, selector):
        dest_dict = to_tags.get_tag_dict()
        result, updates, conflicts = _reconcile_tags(
            source_dict, dest_dict, overwrite, selector
        )
        if result != dest_dict:
            to_tags._set_tag_dict(result)
        return updates, conflicts


class MemoryTags(Tags):
    """A tags implementation that stores tags in memory."""

    def __init__(self, tag_dict):
        """Initialize MemoryTags with a tag dictionary.

        Args:
            tag_dict: Dictionary mapping tag names to revision ids.
        """
        self._tag_dict = tag_dict

    def get_tag_dict(self):
        """Return the dictionary of tags.

        Returns:
            Dictionary mapping tag names to revision ids.
        """
        return self._tag_dict

    def lookup_tag(self, tag_name):
        """Return the referent string of a tag."""
        td = self.get_tag_dict()
        try:
            return td[tag_name]
        except KeyError as e:
            raise errors.NoSuchTag(tag_name) from e

    def set_tag(self, name, revid):
        """Set a tag to point to a revision.

        Args:
            name: Name of the tag.
            revid: Revision id to point to.
        """
        self._tag_dict[name] = revid

    def delete_tag(self, name):
        """Delete a tag.

        Args:
            name: Name of the tag to delete.

        Raises:
            NoSuchTag: If the tag doesn't exist.
        """
        try:
            del self._tag_dict[name]
        except KeyError as err:
            raise errors.NoSuchTag(name) from err

    def rename_revisions(self, revid_map):
        """Rename revisions in the tag dictionary.

        Args:
            revid_map: Dictionary mapping old revids to new revids.
        """
        self._tag_dict = {
            name: revid_map.get(revid, revid) for name, revid in self._tag_dict.items()
        }

    def _set_tag_dict(self, result):
        self._tag_dict = dict(result.items())

    def merge_to(self, to_tags, overwrite=False, ignore_master=False, selector=None):
        """Merge tags to another tags object.

        Args:
            to_tags: Target tags object.
            overwrite: Whether to overwrite existing tags.
            ignore_master: Whether to ignore master branch tags.
            selector: Optional tag selector function.

        Returns:
            Tuple of (updates, conflicts).
        """
        source_dict = self.get_tag_dict()
        dest_dict = to_tags.get_tag_dict()
        result, updates, conflicts = _reconcile_tags(
            source_dict, dest_dict, overwrite, selector
        )
        if result != dest_dict:
            to_tags._set_tag_dict(result)
        return updates, conflicts


def sort_natural(branch, tags):
    """Sort tags, with numeric substrings as numbers.

    :param branch: Branch
    :param tags: List of tuples with tag name and revision id.
    """

    def natural_sort_key(tag):
        return [
            f(s)
            for f, s in zip(
                itertools.cycle((str.lower, int)), re.split("([0-9]+)", tag[0])
            )
        ]

    tags.sort(key=natural_sort_key)


def sort_alpha(branch, tags):
    """Sort tags lexicographically, in place.

    :param branch: Branch
    :param tags: List of tuples with tag name and revision id.
    """
    tags.sort()


def sort_time(branch, tags):
    """Sort tags by time inline.

    :param branch: Branch
    :param tags: List of tuples with tag name and revision id.
    """
    timestamps = {}
    for _tag, revid in tags:
        try:
            revobj = branch.repository.get_revision(revid)
        except errors.NoSuchRevision:
            timestamp = sys.maxsize  # place them at the end
        else:
            timestamp = revobj.timestamp
        timestamps[revid] = timestamp
    tags.sort(key=lambda x: timestamps[x[1]])


tag_sort_methods = Registry[
    str, Callable[[_mod_branch.Branch, list[str]], list[str]], None
]()
tag_sort_methods.register(
    "natural", sort_natural, "Sort numeric substrings as numbers. (default)"
)
tag_sort_methods.register("alpha", sort_alpha, "Sort tags lexicographically.")
tag_sort_methods.register("time", sort_time, "Sort tags chronologically.")
tag_sort_methods.default_key = "natural"


InterTags.register_optimiser(InterTags)
