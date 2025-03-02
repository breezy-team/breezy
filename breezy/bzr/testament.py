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

Testament format 1
~~~~~~~~~~~~~~~~~~

* timestamps are given as integers to avoid rounding errors
* parents given in lexicographical order
* indented-text form similar to log; intended to be human readable
* paths are given with forward slashes
* files are named using paths for ease of comparison/debugging
* the testament uses unix line-endings (\n)
"""

# XXX: At the moment, clients trust that the graph described in a weave
# is accurate, but that's not covered by the testament.  Perhaps the best
# fix is when verifying a revision to make sure that every file mentioned
# in the revision has compatible ancestry links.

# TODO: perhaps write timestamp in a more readable form

# TODO: Perhaps these should just be different formats in which inventories/
# revisions can be serialized.

from copy import copy

from ..osutils import contains_linebreaks, contains_whitespace, sha_strings
from ..tree import Tree


class Testament:
    """Reduced summary of a revision.

    Testaments can be

      - produced from a revision
      - written to a stream
      - loaded from a stream
      - compared to a revision
    """

    long_header = "bazaar-ng testament version 1\n"
    short_header = "bazaar-ng testament short form 1\n"
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
        self.revprops = copy(rev.properties)
        if contains_whitespace(self.revision_id):
            raise ValueError(self.revision_id)
        if contains_linebreaks(self.committer):
            raise ValueError(self.committer)

    def as_text_lines(self):
        """Yield text form as a sequence of lines.

        The result is returned in utf-8, because it should be signed or
        hashed in that encoding.
        """
        r = []
        a = r.append
        a(self.long_header)
        a(f"revision-id: {self.revision_id.decode('utf-8')}\n")
        a(f"committer: {self.committer}\n")
        a(f"timestamp: {int(self.timestamp)}\n")
        a(f"timezone: {int(self.timezone)}\n")
        # inventory length contains the root, which is not shown here
        a("parents:\n")
        for parent_id in sorted(self.parent_ids):
            if contains_whitespace(parent_id):
                raise ValueError(parent_id)
            a("  {}\n".format(parent_id.decode("utf-8")))
        a("message:\n")
        for l in self.message.splitlines():
            a("  {}\n".format(l))
        a("inventory:\n")
        for path, ie in self._get_entries():
            a(self._entry_to_line(path, ie))
        r.extend(self._revprops_to_lines())
        return [line.encode("utf-8") for line in r]

    def _get_entries(self):
        return (
            (path, ie)
            for (path, file_class, kind, ie) in self.tree.list_files(
                include_root=self.include_root
            )
        )

    def _escape_path(self, path):
        if contains_linebreaks(path):
            raise ValueError(path)
        if not isinstance(path, str):
            # TODO(jelmer): Clean this up for pad.lv/1696545
            path = path.decode("ascii")
        return path.replace("\\", "/").replace(" ", "\\ ")

    def _entry_to_line(self, path, ie):
        """Turn an inventory entry into a testament line."""
        if contains_whitespace(ie.file_id):
            raise ValueError(ie.file_id)
        content = ""
        content_spacer = ""
        if ie.kind == "file":
            # TODO: avoid switching on kind
            if not ie.text_sha1:
                raise AssertionError()
            content = ie.text_sha1.decode("ascii")
            content_spacer = " "
        elif ie.kind == "symlink":
            if not ie.symlink_target:
                raise AssertionError()
            content = self._escape_path(ie.symlink_target)
            content_spacer = " "

        l = "  {} {} {}{}{}\n".format(
            ie.kind,
            self._escape_path(path),
            ie.file_id.decode("utf8"),
            content_spacer,
            content,
        )
        return l

    def as_text(self):
        return b"".join(self.as_text_lines())

    def as_short_text(self):
        """Return short digest-based testament."""
        return self.short_header.encode("ascii") + b"revision-id: %s\nsha1: %s\n" % (
            self.revision_id,
            self.as_sha1(),
        )

    def _revprops_to_lines(self):
        """Pack up revision properties."""
        if not self.revprops:
            return []
        r = ["properties:\n"]
        for name, value in sorted(self.revprops.items()):
            if contains_whitespace(name):
                raise ValueError(name)
            r.append("  {}:\n".format(name))
            for line in value.splitlines():
                r.append("    {}\n".format(line))
        return r

    def as_sha1(self):
        return sha_strings(self.as_text_lines())


class StrictTestament(Testament):
    """This testament format is for use as a checksum in bundle format 0.8."""

    long_header = "bazaar-ng testament version 2.1\n"
    short_header = "bazaar-ng testament short form 2.1\n"
    include_root = False

    def _entry_to_line(self, path, ie):
        l = Testament._entry_to_line(self, path, ie)[:-1]
        l += " " + ie.revision.decode("utf-8")
        l += {True: " yes\n", False: " no\n"}[ie.executable]
        return l


class StrictTestament3(StrictTestament):
    """This testament format is for use as a checksum in bundle format 0.9+.

    It differs from StrictTestament by including data about the tree root.
    """

    long_header = "bazaar testament version 3 strict\n"
    short_header = "bazaar testament short form 3 strict\n"
    include_root = True

    def _escape_path(self, path):
        if contains_linebreaks(path):
            raise ValueError(path)
        if not isinstance(path, str):
            # TODO(jelmer): Clean this up for pad.lv/1696545
            path = path.decode("ascii")
        if path == "":
            path = "."
        return path.replace("\\", "/").replace(" ", "\\ ")
