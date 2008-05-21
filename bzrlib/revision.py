# Copyright (C) 2005, 2006 Canonical Ltd
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

# TODO: Some kind of command-line display of revision properties: 
# perhaps show them in log -v and allow them as options to the commit command.


from bzrlib import (
    errors,
    symbol_versioning,
    )
from bzrlib.osutils import contains_whitespace
from bzrlib.progress import DummyProgress

NULL_REVISION="null:"
CURRENT_REVISION="current:"


class Revision(object):
    """Single revision on a branch.

    Revisions may know their revision_hash, but only once they've been
    written out.  This is not stored because you cannot write the hash
    into the file it describes.

    After bzr 0.0.5 revisions are allowed to have multiple parents.

    parent_ids
        List of parent revision_ids

    properties
        Dictionary of revision properties.  These are attached to the
        revision as extra metadata.  The name must be a single 
        word; the value can be an arbitrary string.
    """
    
    def __init__(self, revision_id, properties=None, **args):
        self.revision_id = revision_id
        self.properties = properties or {}
        self._check_properties()
        self.parent_ids = []
        self.parent_sha1s = []
        """Not used anymore - legacy from for 4."""
        self.__dict__.update(args)

    def __repr__(self):
        return "<Revision id %s>" % self.revision_id

    def __eq__(self, other):
        if not isinstance(other, Revision):
            return False
        # FIXME: rbc 20050930 parent_ids are not being compared
        return (
                self.inventory_sha1 == other.inventory_sha1
                and self.revision_id == other.revision_id
                and self.timestamp == other.timestamp
                and self.message == other.message
                and self.timezone == other.timezone
                and self.committer == other.committer
                and self.properties == other.properties)

    def __ne__(self, other):
        return not self.__eq__(other)

    def _check_properties(self):
        """Verify that all revision properties are OK."""
        for name, value in self.properties.iteritems():
            if not isinstance(name, basestring) or contains_whitespace(name):
                raise ValueError("invalid property name %r" % name)
            if not isinstance(value, basestring):
                raise ValueError("invalid property value %r for %r" % 
                                 (name, value))

    def get_history(self, repository):
        """Return the canonical line-of-history for this revision.

        If ghosts are present this may differ in result from a ghost-free
        repository.
        """
        current_revision = self
        reversed_result = []
        while current_revision is not None:
            reversed_result.append(current_revision.revision_id)
            if not len (current_revision.parent_ids):
                reversed_result.append(None)
                current_revision = None
            else:
                next_revision_id = current_revision.parent_ids[0]
                current_revision = repository.get_revision(next_revision_id)
        reversed_result.reverse()
        return reversed_result

    def get_summary(self):
        """Get the first line of the log message for this revision.
        """
        return self.message.lstrip().split('\n', 1)[0]

    def get_apparent_author(self):
        """Return the apparent author of this revision.

        If the revision properties contain the author name,
        return it. Otherwise return the committer name.
        """
        return self.properties.get('author', self.committer)


def iter_ancestors(revision_id, revision_source, only_present=False):
    ancestors = (revision_id,)
    distance = 0
    while len(ancestors) > 0:
        new_ancestors = []
        for ancestor in ancestors:
            if not only_present:
                yield ancestor, distance
            try:
                revision = revision_source.get_revision(ancestor)
            except errors.NoSuchRevision, e:
                if e.revision == revision_id:
                    raise 
                else:
                    continue
            if only_present:
                yield ancestor, distance
            new_ancestors.extend(revision.parent_ids)
        ancestors = new_ancestors
        distance += 1


def find_present_ancestors(revision_id, revision_source):
    """Return the ancestors of a revision present in a branch.

    It's possible that a branch won't have the complete ancestry of
    one of its revisions.  

    """
    found_ancestors = {}
    anc_iter = enumerate(iter_ancestors(revision_id, revision_source,
                         only_present=True))
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


def is_reserved_id(revision_id):
    """Determine whether a revision id is reserved

    :return: True if the revision is is reserved, False otherwise
    """
    return isinstance(revision_id, basestring) and revision_id.endswith(':')


def check_not_reserved_id(revision_id):
    """Raise ReservedId if the supplied revision_id is reserved"""
    if is_reserved_id(revision_id):
        raise errors.ReservedId(revision_id)


def ensure_null(revision_id):
    """Ensure only NULL_REVISION is used to represent the null revision"""
    if revision_id is None:
        symbol_versioning.warn('NULL_REVISION should be used for the null'
            ' revision instead of None, as of bzr 0.91.',
            DeprecationWarning, stacklevel=2)
        return NULL_REVISION
    else:
        return revision_id


def is_null(revision_id):
    if revision_id is None:
        symbol_versioning.warn('NULL_REVISION should be used for the null'
            ' revision instead of None, as of bzr 0.90.',
            DeprecationWarning, stacklevel=2)
    return revision_id in (None, NULL_REVISION)
