# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

from bzrlib import (
    errors,
    lockable_files,
    lockdir,
    xml6,
    )

from bzrlib.repository import (
    KnitRepository,
    RepositoryFormat,
    RepositoryFormatKnit,
    RootCommitBuilder,
    )


class KnitRepository2(KnitRepository):
    """"""
    def __init__(self, _format, a_bzrdir, control_files, _revision_store,
                 control_store, text_store):
        KnitRepository.__init__(self, _format, a_bzrdir, control_files,
                              _revision_store, control_store, text_store)
        self._serializer = xml6.serializer_v6

    def deserialise_inventory(self, revision_id, xml):
        """Transform the xml into an inventory object. 

        :param revision_id: The expected revision id of the inventory.
        :param xml: A serialised inventory.
        """
        result = self._serializer.read_inventory_from_string(xml)
        assert result.root.revision is not None
        return result

    def serialise_inventory(self, inv):
        """Transform the inventory object into XML text.

        :param revision_id: The expected revision id of the inventory.
        :param xml: A serialised inventory.
        """
        assert inv.revision_id is not None
        assert inv.root.revision is not None
        return KnitRepository.serialise_inventory(self, inv)

    def get_commit_builder(self, branch, parents, config, timestamp=None,
                           timezone=None, committer=None, revprops=None,
                           revision_id=None):
        """Obtain a CommitBuilder for this repository.
        
        :param branch: Branch to commit to.
        :param parents: Revision ids of the parents of the new revision.
        :param config: Configuration to use.
        :param timestamp: Optional timestamp recorded for commit.
        :param timezone: Optional timezone for timestamp.
        :param committer: Optional committer to set for commit.
        :param revprops: Optional dictionary of revision properties.
        :param revision_id: Optional revision id.
        """
        return RootCommitBuilder(self, parents, config, timestamp, timezone,
                                 committer, revprops, revision_id)


class RepositoryFormatKnit2(RepositoryFormatKnit):
    """Bzr repository knit format 2.

    THIS FORMAT IS EXPERIMENTAL
    This repository format has:
     - knits for file texts and inventory
     - hash subdirectory based stores.
     - knits for revisions and signatures
     - TextStores for revisions and signatures.
     - a format marker of its own
     - an optional 'shared-storage' flag
     - an optional 'no-working-trees' flag
     - a LockDir lock
     - Support for recording full info about the tree root

    """
    
    rich_root_data = True

    def get_format_string(self):
        """See RepositoryFormat.get_format_string()."""
        return "Bazaar Knit Repository Format 2\n"

    def get_format_description(self):
        """See RepositoryFormat.get_format_description()."""
        return "Knit repository format 2"

    def check_conversion_target(self, target_format):
        if not target_format.rich_root_data:
            raise errors.BadConversionTarget(
                'Does not support rich root data.', target_format)

    def open(self, a_bzrdir, _found=False, _override_transport=None):
        """See RepositoryFormat.open().
        
        :param _override_transport: INTERNAL USE ONLY. Allows opening the
                                    repository at a slightly different url
                                    than normal. I.e. during 'upgrade'.
        """
        if not _found:
            format = RepositoryFormat.find_format(a_bzrdir)
            assert format.__class__ ==  self.__class__
        if _override_transport is not None:
            repo_transport = _override_transport
        else:
            repo_transport = a_bzrdir.get_repository_transport(None)
        control_files = lockable_files.LockableFiles(repo_transport, 'lock',
                                                     lockdir.LockDir)
        text_store = self._get_text_store(repo_transport, control_files)
        control_store = self._get_control_store(repo_transport, control_files)
        _revision_store = self._get_revision_store(repo_transport, control_files)
        return KnitRepository2(_format=self,
                               a_bzrdir=a_bzrdir,
                               control_files=control_files,
                               _revision_store=_revision_store,
                               control_store=control_store,
                               text_store=text_store)


RepositoryFormatKnit2_instance = RepositoryFormatKnit2()
