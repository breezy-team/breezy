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

# TODO: Some kind of command-line display of revision properties:
# perhaps show them in log -v and allow them as options to the commit command.

__docformat__ = "google"

from bzrformats._bzr_rs import (  # noqa: F401
    CURRENT_REVISION,
    NULL_REVISION,
    Revision,
    check_not_reserved_id,
    is_null,
    is_reserved_id,
)

from . import errors

RevisionID = bytes


def iter_bugs(rev):
    """Iterate over the bugs associated with this revision."""
    from . import bugtracker

    return bugtracker.decode_bug_urls(rev.bug_urls())


def get_history(repository, current_revision):
    """Return the canonical line-of-history for this revision.

    If ghosts are present this may differ in result from a ghost-free
    repository.
    """
    reversed_result = []
    while current_revision is not None:
        reversed_result.append(current_revision.revision_id)
        if not len(current_revision.parent_ids):
            reversed_result.append(None)
            current_revision = None
        else:
            next_revision_id = current_revision.parent_ids[0]
            current_revision = repository.get_revision(next_revision_id)
    reversed_result.reverse()
    return reversed_result


def iter_ancestors(
    revision_id: RevisionID, revision_source, only_present: bool = False
):
    ancestors = [revision_id]
    distance = 0
    while len(ancestors) > 0:
        new_ancestors: list[bytes] = []
        for ancestor in ancestors:
            if not only_present:
                yield ancestor, distance
            try:
                revision = revision_source.get_revision(ancestor)
            except errors.NoSuchRevision as e:
                if e.revision == revision_id:
                    raise
                else:
                    continue
            if only_present:
                yield ancestor, distance
            new_ancestors.extend(revision.parent_ids)
        ancestors = new_ancestors
        distance += 1


def find_present_ancestors(
    revision_id: RevisionID, revision_source
) -> dict[RevisionID, tuple[int, int]]:
    """Return the ancestors of a revision present in a branch.

    It's possible that a branch won't have the complete ancestry of
    one of its revisions.
    """
    found_ancestors: dict[RevisionID, tuple[int, int]] = {}
    anc_iter = enumerate(
        iter_ancestors(revision_id, revision_source, only_present=True)
    )
    for anc_order, (anc_id, anc_distance) in anc_iter:
        if anc_id not in found_ancestors:
            found_ancestors[anc_id] = (anc_order, anc_distance)
    return found_ancestors
