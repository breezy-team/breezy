# Copyright (C) 2008 Canonical Ltd
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


"""Foreign branch utilities."""


from bzrlib.branch import Branch
from bzrlib.commands import Command, Option
from bzrlib.repository import Repository
from bzrlib.revision import Revision
from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    errors,
    osutils,
    registry,
    )
""")

class VcsMapping(object):
    """Describes the mapping between the semantics of Bazaar and a foreign vcs.

    """
    # Whether this is an experimental mapping that is still open to changes.
    experimental = False

    # Whether this mapping supports exporting and importing all bzr semantics.
    roundtripping = False

    # Prefix used when importing native foreign revisions (not roundtripped) 
    # using this mapping.
    revid_prefix = None

    def revision_id_bzr_to_foreign(self, bzr_revid):
        """Parse a bzr revision id and convert it to a foreign revid.

        :param bzr_revid: The bzr revision id (a string).
        :return: A foreign revision id, can be any sort of object.
        """
        raise NotImplementedError(self.revision_id_bzr_to_foreign)

    def revision_id_foreign_to_bzr(self, foreign_revid):
        """Parse a foreign revision id and convert it to a bzr revid.

        :param foreign_revid: Foreign revision id, can be any sort of object.
        :return: A bzr revision id.
        """
        raise NotImplementedError(self.revision_id_foreign_to_bzr)

    def show_foreign_revid(self, foreign_revid):
        """Prepare a foreign revision id for formatting using bzr log.
        
        :param foreign_revid: Foreign revision id.
        :return: Dictionary mapping string keys to string values.
        """
        # TODO: This could be on ForeignVcs instead
        return { }


class VcsMappingRegistry(registry.Registry):
    """Registry for Bazaar<->foreign VCS mappings.
    
    There should be one instance of this registry for every foreign VCS.
    """

    def register(self, key, factory, help):
        """Register a mapping between Bazaar and foreign VCS semantics.

        The factory must be a callable that takes one parameter: the key.
        It must produce an instance of VcsMapping when called.
        """
        if ":" in key:
            raise ValueError("mapping name can not contain colon (:)")
        registry.Registry.register(self, key, factory, help)

    def set_default(self, key):
        """Set the 'default' key to be a clone of the supplied key.

        This method must be called once and only once.
        """
        self._set_default_key(key)

    def get_default(self):
        """Convenience function for obtaining the default mapping to use."""
        return self.get(self._get_default_key())

    def revision_id_bzr_to_foreign(self, revid):
        """Convert a bzr revision id to a foreign revid."""
        raise NotImplementedError(self.revision_id_bzr_to_foreign)


class ForeignRevision(Revision):
    """A Revision from a Foreign repository. Remembers 
    information about foreign revision id and mapping.

    """

    def __init__(self, foreign_revid, mapping, *args, **kwargs):
        if not "inventory_sha1" in kwargs:
            kwargs["inventory_sha1"] = ""
        super(ForeignRevision, self).__init__(*args, **kwargs)
        self.foreign_revid = foreign_revid
        self.mapping = mapping


def show_foreign_properties(rev):
    """Custom log displayer for foreign revision identifiers.

    :param rev: Revision object.
    """
    # Revision comes directly from a foreign repository
    if isinstance(rev, ForeignRevision):
        return rev.mapping.show_foreign_revid(rev.foreign_revid)

    # Revision was once imported from a foreign repository
    try:
        foreign_revid, mapping = \
            foreign_vcs_registry.parse_revision_id(rev.revision_id)
    except errors.InvalidRevisionId:
        return {}

    return mapping.show_foreign_revid(foreign_revid)


class ForeignVcs(object):
    """A foreign version control system."""

    def __init__(self, mapping_registry):
        self.mapping_registry = mapping_registry


class ForeignVcsRegistry(registry.Registry):
    """Registry for Foreign VCSes.

    There should be one entry per foreign VCS. Example entries would be 
    "git", "svn", "hg", "darcs", etc.
    
    """

    def register(self, key, foreign_vcs, help):
        """Register a foreign VCS.

        :param key: Prefix of the foreign VCS in revision ids
        :param foreign_vcs: ForeignVCS instance
        :param help: Description of the foreign VCS
        """
        if ":" in key or "-" in key:
            raise ValueError("vcs name can not contain : or -")
        registry.Registry.register(self, key, foreign_vcs, help)

    def parse_revision_id(self, revid):
        """Parse a bzr revision and return the matching mapping and foreign 
        revid.
        
        :param revid: The bzr revision id
        :return: tuple with foreign revid and vcs mapping
        """
        if not "-" in revid:
            raise errors.InvalidRevisionId(revid, None)
        try:
            foreign_vcs = self.get(revid.split("-")[0])
        except KeyError:
            raise errors.InvalidRevisionId(revid, None)
        return foreign_vcs.mapping_registry.revision_id_bzr_to_foreign(revid)


foreign_vcs_registry = ForeignVcsRegistry()


class ForeignRepository(Repository):
    """A Repository that exists in a foreign version control system.

    The data in this repository can not be represented natively using 
    Bazaars internal datastructures, but have to converted using a VcsMapping.
    """

    # This repository's native version control system
    vcs = None

    def has_foreign_revision(self, foreign_revid):
        """Check whether the specified foreign revision is present.

        :param foreign_revid: A foreign revision id, in the format used 
                              by this Repository's VCS.
        """
        raise NotImplementedError(self.has_foreign_revision)

    def lookup_bzr_revision_id(self, revid):
        """Lookup a mapped or roundtripped revision by revision id.

        :param revid: Bazaar revision id
        :return: Tuple with foreign revision id and mapping.
        """
        raise NotImplementedError(self.lookup_revision_id)

    def all_revision_ids(self, mapping=None):
        """See Repository.all_revision_ids()."""
        raise NotImplementedError(self.all_revision_ids)

    def get_default_mapping(self):
        """Get the default mapping for this repository."""
        raise NotImplementedError(self.get_default_mapping)

    def get_inventory_xml(self, revision_id):
        """See Repository.get_inventory_xml()."""
        return self.serialise_inventory(self.get_inventory(revision_id))

    def get_inventory_sha1(self, revision_id):
        """Get the sha1 for the XML representation of an inventory.

        :param revision_id: Revision id of the inventory for which to return 
         the SHA1.
        :return: XML string
        """

        return osutils.sha_string(self.get_inventory_xml(revision_id))

    def get_revision_xml(self, revision_id):
        """Return the XML representation of a revision.

        :param revision_id: Revision for which to return the XML.
        :return: XML string
        """
        return self._serializer.write_revision_to_string(
            self.get_revision(revision_id))


