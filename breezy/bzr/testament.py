# Copyright (C) 2005 Canonical Ltd
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

r"""Testament - a summary of a revision for signing.

A testament can be defined as "something that serves as tangible
proof or evidence."  In bzr we use them to allow people to certify
particular revisions as authentic.

The goal is that if two revisions are semantically equal, then they will
have a byte-for-byte equal testament.  We can define different versions of
"semantically equal" by using different testament classes; e.g. one that
includes or ignores file-ids.

We sign a testament rather than the revision XML itself for several reasons.
The most important is that the form in which the revision is stored
internally is designed for that purpose, and contains information which need
not be attested to by the signer.  For example the inventory contains the
last-changed revision for a file, but this is not necessarily something the
user cares to sign.

Having unnecessary fields signed makes the signatures brittle when the same
revision is stored in different branches or when the format is upgraded.

Handling upgrades is another motivation for using testaments separate from
the stored revision.  We would like to be able to compare a signature
generated from an old-format tree to newer tree, or vice versa.  This could
be done by comparing the revisions but that makes it unclear about exactly
what is being compared or not.

Different signing keys might indicate different levels of trust; we can in
the future extend this to allow signatures indicating not just that a
particular version is authentic but that it has other properties.

The signature can be applied to either the full testament or to just a
hash of it.

The canonical text rendering is implemented in Rust
(``bzrformats._bzr_rs.testament``); this module gathers the per-revision
inventory entries from a tree and delegates serialization to it.
"""

from bzrformats._bzr_rs.testament import Testament as _RsTestament

from ..tree import Tree


class Testament:
    """Reduced summary of a revision.

    Testaments can be

      - produced from a revision
      - written to a stream
      - loaded from a stream
      - compared to a revision
    """

    # Format selector passed to the Rust core.
    _format = "1"
    include_root = False

    @classmethod
    def from_revision(cls, repository, revision_id):
        """Produce a new testament from a historical revision."""
        rev = repository.get_revision(revision_id)
        tree = repository.revision_tree(revision_id)
        return cls(rev, tree)

    @classmethod
    def from_revision_tree(cls, tree):
        """Produce a new testament from a revision tree."""
        rev = tree._repository.get_revision(tree.get_revision_id())
        return cls(rev, tree)

    def __init__(self, rev, tree):
        """Create a new testament for rev using tree."""
        self.revision_id = rev.revision_id
        self.committer = rev.committer
        self.timezone = rev.timezone or 0
        self.timestamp = rev.timestamp
        self.message = rev.message
        self.parent_ids = rev.parent_ids[:]
        if not isinstance(tree, Tree):
            raise TypeError(
                "As of bzr 2.4 Testament.__init__() takes a Revision and a Tree."
            )
        self.tree = tree
        self.revprops = dict(rev.properties)

    def _entries(self):
        """Yield the per-entry tuples the Rust core consumes."""
        for path, _, _, ie in self.tree.list_files(include_root=self.include_root):
            if ie.kind == "file":
                content = ie.text_sha1 or b""
            elif ie.kind == "symlink":
                if not ie.symlink_target:
                    raise AssertionError()
                content = ie.symlink_target.encode("utf-8")
            else:
                content = b""
            yield (
                path,
                ie.kind,
                ie.file_id,
                content,
                ie.revision or b"",
                bool(ie.executable),
            )

    def _rs(self):
        return _RsTestament(
            self.revision_id,
            self.committer,
            int(self.timestamp),
            self.timezone,
            self.message,
            self.parent_ids,
            self.revprops,
            list(self._entries()),
        )

    def as_text_lines(self):
        """Return the testament as a list of UTF-8 encoded byte lines."""
        return self._rs().as_text(self._format).splitlines(keepends=True)

    def as_text(self):
        """Return the testament as a single UTF-8 encoded byte string."""
        return self._rs().as_text(self._format)

    def as_short_text(self):
        """Return short digest-based testament."""
        return self._rs().as_short_text(self._format)

    def as_sha1(self):
        """Return the SHA-1 hash of the testament."""
        return self._rs().as_sha1(self._format)


class StrictTestament(Testament):
    """This testament format is for use as a checksum in bundle format 0.8."""

    _format = "strict"
    include_root = False


class StrictTestament3(StrictTestament):
    """This testament format is for use as a checksum in bundle format 0.9+.

    It differs from StrictTestament by including data about the tree root.
    """

    _format = "strict3"
    include_root = True
