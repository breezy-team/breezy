# Copyright (C) 2006 Canonical Ltd
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

"""Revision stores.

Revision stores are responsible for storing a group of revisions
and returning some interesting data about them such as ancestors
and ghosts information.
"""

from cStringIO import StringIO

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    errors,
    osutils,
    xml5,
    )
from bzrlib.trace import mutter
""")


class RevisionStore(object):
    """A revision store stores revisions."""

    def __init__(self, serializer=None):
        if serializer is None:
            serializer = xml5.serializer_v5
        self._serializer = serializer

    def add_revision(self, revision, transaction):
        """Add revision to the revision store.

        :param rev: The revision object.
        """
        # serialisation : common to all at the moment.
        rev_tmp = StringIO()
        self._serializer.write_revision(revision, rev_tmp)
        rev_tmp.seek(0)
        self._add_revision(revision, rev_tmp, transaction)
        mutter('added revision_id {%s}', revision.revision_id)

    def _add_revision(self, revision, revision_as_file, transaction):
        """Template method helper to store revision in this store."""
        raise NotImplementedError(self._add_revision)

    def add_revision_signature_text(self, revision_id, signature_text, transaction):
        """Add signature_text as a signature for revision_id."""
        raise NotImplementedError(self.add_revision_signature_text)

    def all_revision_ids(self, transaction):
        """Returns a list of all the revision ids in the revision store. 

        :return: list of revision_ids in topological order.
        """
        raise NotImplementedError(self.all_revision_ids)

    def get_revision(self, revision_id, transaction):
        """Return the Revision object for a named revision."""
        return self.get_revisions([revision_id], transaction)[0]

    def get_revisions(self, revision_ids, transaction):
        """Return the Revision objects for a list of named revisions."""
        raise NotImplementedError(self.get_revision)

    def get_signature_text(self, revision_id, transaction):
        """Get the signature text for the digital signature of revision_id.
        
        :return: a signature text.
        """
        revision_id = osutils.safe_revision_id(revision_id)
        self._guard_revision(revision_id, transaction)
        return self._get_signature_text(revision_id, transaction)

    def _get_signature_text(self, revision_id, transaction):
        """Helper method for get_signature_text to return the text itself."""
        raise NotImplementedError(self.get_signature_text)

    def _guard_revision(self, revision_id, transaction):
        """Guard method for testing the presence of a revision."""
        if not self.has_revision_id(revision_id, transaction):
            raise errors.NoSuchRevision(self, revision_id)

    def has_revision_id(self, revision_id, transaction):
        """True if the store contains revision_id."""
        raise NotImplementedError(self.has_revision_id)

    def has_signature(self, revision_id, transaction):
        """True if the store has a signature for revision_id."""
        revision_id = osutils.safe_revision_id(revision_id)
        self._guard_revision(revision_id, transaction)
        return self._has_signature(revision_id, transaction)

    def _has_signature(self, revision_id, transaction):
        """Return the presence of a signature for revision_id.

        A worker memrthod for has_signature, this can assume the
        revision is present.
        """
        return NotImplementedError(self._has_signature)
        
    def total_size(self, transaction):
        """How big is the store?

        :return: (count, bytes) tuple.
        """
        raise NotImplementedError(self.total_size)
