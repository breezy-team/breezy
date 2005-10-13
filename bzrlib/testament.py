# Copyright (C) 2005 by Canonical Ltd
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

"""Testament - a summary of a revision for signing.

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

from cStringIO import StringIO
import string
import sha


def contains_whitespace(s):
    """True if there are any whitespace characters in s."""
    for ch in string.whitespace:
        if ch in s:
            return True
    else:
        return False


def contains_linebreaks(s):
    """True if there is any vertical whitespace in s."""
    for ch in '\f\n\r':
        if ch in s:
            return True
    else:
        return False

    
class Testament(object):
    """Reduced summary of a revision.

    Testaments can be 

      - produced from a revision
      - writen to a stream
      - loaded from a stream
      - compared to a revision
    """

    @classmethod
    def from_revision(cls, branch, revision_id):
        """Produce a new testament from a historical revision"""
        t = cls()
        rev = branch.get_revision(revision_id)
        t.revision_id = revision_id
        t.committer = rev.committer
        t.timezone = rev.timezone or 0
        t.timestamp = rev.timestamp
        t.message = rev.message
        t.parent_ids = rev.parent_ids[:]
        t.inventory = branch.get_inventory(revision_id)
        return t

    def text_form_1_to_file(self, f):
        """Convert to externalizable text form.

        The result is returned in utf-8, because it should be signed or
        hashed in that encoding.
        """
        # TODO: Set right encoding
        print >>f, 'bazaar-ng testament version 1'
        assert not contains_whitespace(self.revision_id)
        print >>f, 'revision-id:', self.revision_id
        assert not contains_linebreaks(self.committer)
        print >>f, 'committer:', self.committer
        # TODO: perhaps write timestamp in a more readable form
        print >>f, 'timestamp:', self.timestamp
        print >>f, 'timezone:', self.timezone
        # inventory length contains the root, which is not shown here
        print >>f, 'entries:', len(self.inventory) - 1
        print >>f, 'parents:'
        for parent_id in sorted(self.parent_ids):
            assert not contains_whitespace(parent_id)
            print >>f, '  ' + parent_id
        print >>f, 'message:'
        for l in self.message.splitlines():
            print >>f, '  ' + l
        print >>f, 'inventory:'
        for path, ie in self.inventory.iter_entries():
            print >>f, ' ', ie.kind, path

    def to_text_form_1(self):
        s = StringIO()
        self.text_form_1_to_file(s)
        return s.getvalue()

    def as_short_text(self):
        """Return short digest-based testament."""
        s = sha.sha(self.to_text_form_1())
        return ('bazaar-ng testament short form 1\n'
                'revision %s\n'
                'sha1 %s\n'
                % (self.revision_id, s.hexdigest()))

