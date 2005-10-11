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
"""

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
        return t
