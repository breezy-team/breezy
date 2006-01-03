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

# TODO: perhaps write timestamp in a more readable form

# TODO: Perhaps these should just be different formats in which inventories/
# revisions can be serialized.

from copy import copy
from cStringIO import StringIO
import string
from sha import sha

from bzrlib.osutils import contains_whitespace, contains_linebreaks

class Testament(object):
    """Reduced summary of a revision.

    Testaments can be 

      - produced from a revision
      - written to a stream
      - loaded from a stream
      - compared to a revision
    """

    @classmethod
    def from_revision(cls, repository, revision_id):
        """Produce a new testament from a historical revision"""
        rev = repository.get_revision(revision_id)
        inventory = repository.get_inventory(revision_id)
        return cls(rev, inventory)

    def __init__(self, rev, inventory):
        """Create a new testament for rev using inventory."""
        self.revision_id = str(rev.revision_id)
        self.committer = rev.committer
        self.timezone = rev.timezone or 0
        self.timestamp = rev.timestamp
        self.message = rev.message
        self.parent_ids = rev.parent_ids[:]
        self.inventory = inventory
        self.revprops = copy(rev.properties)
        assert not contains_whitespace(self.revision_id)
        assert not contains_linebreaks(self.committer)

    def as_text_lines(self):
        """Yield text form as a sequence of lines.

        The result is returned in utf-8, because it should be signed or
        hashed in that encoding.
        """
        r = []
        def a(s):
            r.append(s)
        a('bazaar-ng testament version 1\n')
        a('revision-id: %s\n' % self.revision_id)
        a('committer: %s\n' % self.committer)
        a('timestamp: %d\n' % self.timestamp)
        a('timezone: %d\n' % self.timezone)
        # inventory length contains the root, which is not shown here
        a('parents:\n')
        for parent_id in sorted(self.parent_ids):
            assert not contains_whitespace(parent_id)
            a('  %s\n' % parent_id)
        a('message:\n')
        for l in self.message.splitlines():
            a('  %s\n' % l)
        a('inventory:\n')
        for path, ie in self.inventory.iter_entries():
            a(self._entry_to_line(path, ie))
        r.extend(self._revprops_to_lines())
        if __debug__:
            for l in r:
                assert isinstance(l, basestring), \
                    '%r of type %s is not a plain string' % (l, type(l))
        return r

    def _escape_path(self, path):
        assert not contains_linebreaks(path)
        return unicode(path.replace('\\', '/').replace(' ', '\ ')).encode('utf-8')

    def _entry_to_line(self, path, ie):
        """Turn an inventory entry into a testament line"""
        l = '  ' + str(ie.kind)
        l += ' ' + self._escape_path(path)
        assert not contains_whitespace(ie.file_id)
        l += ' ' + unicode(ie.file_id).encode('utf-8')
        if ie.kind == 'file':
            # TODO: avoid switching on kind
            assert ie.text_sha1
            l += ' ' + ie.text_sha1
        elif ie.kind == 'symlink':
            assert ie.symlink_target
            l += ' ' + self._escape_path(ie.symlink_target)
        l += '\n'
        return l

    def as_text(self):
        return ''.join(self.as_text_lines())

    def as_short_text(self):
        """Return short digest-based testament."""
        s = sha()
        map(s.update, self.as_text_lines())
        return ('bazaar-ng testament short form 1\n'
                'revision-id: %s\n'
                'sha1: %s\n'
                % (self.revision_id, s.hexdigest()))

    def _revprops_to_lines(self):
        """Pack up revision properties."""
        if not self.revprops:
            return []
        r = ['properties:\n']
        for name, value in sorted(self.revprops.items()):
            assert isinstance(name, str)
            assert not contains_whitespace(name)
            r.append('  %s:\n' % name)
            for line in value.splitlines():
                if not isinstance(line, str):
                    line = line.encode('utf-8')
                r.append('    %s\n' % line)
        return r
