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


from . import errors, osutils

RevisionID = bytes

NULL_REVISION = b"null:"
CURRENT_REVISION = b"current:"


class Revision:
    """Single revision on a branch.

    Revisions may know their revision_hash, but only once they've been
    written out.  This is not stored because you cannot write the hash
    into the file it describes.

    Attributes:
      parent_ids: List of parent revision_ids

      properties:
        Dictionary of revision properties.  These are attached to the
        revision as extra metadata.  The name must be a single
        word; the value can be an arbitrary string.
    """

    parent_ids: list[RevisionID]
    revision_id: RevisionID
    parent_sha1s: list[str]
    committer: str | None
    message: str
    properties: dict[str, bytes]
    inventory_sha1: str
    timestamp: float
    timezone: int

    def __init__(self, revision_id: RevisionID, properties=None, **args) -> None:
        self.revision_id = revision_id
        if properties is None:
            self.properties = {}
        else:
            self.properties = properties
            self._check_properties()
        self.committer = None
        self.parent_ids = []
        self.parent_sha1s = []
        # Not used anymore - legacy from for 4.
        self.__dict__.update(args)

    def __repr__(self):
        return "<Revision id {}>".format(self.revision_id)

    def datetime(self):
        import datetime

        # TODO: Handle timezone.
        return datetime.datetime.fromtimestamp(self.timestamp)

    def __eq__(self, other):
        if not isinstance(other, Revision):
            return False
        return (
            self.inventory_sha1 == other.inventory_sha1
            and self.revision_id == other.revision_id
            and self.timestamp == other.timestamp
            and self.message == other.message
            and self.timezone == other.timezone
            and self.committer == other.committer
            and self.properties == other.properties
            and self.parent_ids == other.parent_ids
        )

    def __ne__(self, other):
        return not self.__eq__(other)

    def _check_properties(self):
        """Verify that all revision properties are OK."""
        for name, value in self.properties.items():
            # GZ 2017-06-10: What sort of string are properties exactly?
            not_text = not isinstance(name, str)
            if not_text or osutils.contains_whitespace(name):
                raise ValueError("invalid property name {!r}".format(name))
            if not isinstance(value, (str, bytes)):
                raise ValueError(
                    "invalid property value {!r} for {!r}".format(value, name)
                )

    def get_history(self, repository):
        """Return the canonical line-of-history for this revision.

        If ghosts are present this may differ in result from a ghost-free
        repository.
        """
        current_revision = self
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

    def get_summary(self):
        """Get the first line of the log message for this revision.

        Return an empty string if message is None.
        """
        if self.message:
            return self.message.lstrip().split("\n", 1)[0]
        else:
            return ""

    def get_apparent_authors(self):
        """Return the apparent authors of this revision.

        If the revision properties contain the names of the authors,
        return them. Otherwise return the committer name.

        The return value will be a list containing at least one element.
        """
        authors = self.properties.get("authors", None)
        if authors is None:
            author = self.properties.get("author", self.committer)
            if author is None:
                return []
            return [author]
        else:
            return authors.split("\n")

    def iter_bugs(self):
        """Iterate over the bugs associated with this revision."""
        bug_property = self.properties.get("bugs", None)
        if bug_property is None:
            return iter([])
        from . import bugtracker

        return bugtracker.decode_bug_urls(bug_property)


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


def __get_closest(intersection):
    intersection.sort()
    matches = []
    for entry in intersection:
        if entry[0] == intersection[0][0]:
            matches.append(entry[2])
    return matches


def is_reserved_id(revision_id: RevisionID) -> bool:
    """Determine whether a revision id is reserved.

    Returns:
      True if the revision is reserved, False otherwise
    """
    return isinstance(revision_id, bytes) and revision_id.endswith(b":")


def check_not_reserved_id(revision_id: RevisionID) -> None:
    """Raise ReservedId if the supplied revision_id is reserved."""
    if is_reserved_id(revision_id):
        raise errors.ReservedId(revision_id)


def is_null(revision_id: RevisionID) -> bool:
    if revision_id is None:
        raise ValueError(
            "NULL_REVISION should be used for the null revision instead of None."
        )
    return revision_id == NULL_REVISION
