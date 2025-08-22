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

"""Bazaar repository implementation.

This module provides the repository classes and formats for Bazaar's
native storage format, including support for shared repositories and
the meta-directory layout.
"""

import contextlib
import itertools

from .. import errors, lockdir
from .. import revision as _mod_revision
from .. import transport as _mod_transport
from ..repository import Repository, RepositoryFormat, format_registry
from . import bzrdir, lockable_files


class MetaDirRepository(Repository):
    """Repositories in the new meta-dir layout.

    :ivar _transport: Transport for access to repository control files,
        typically pointing to .bzr/repository.
    """

    _format: "RepositoryFormatMetaDir"

    def __init__(self, _format, a_bzrdir, control_files):
        """Initialize a MetaDirRepository.

        Args:
            _format: The repository format.
            a_bzrdir: The bzrdir containing this repository.
            control_files: The control files for this repository.
        """
        super().__init__(_format, a_bzrdir, control_files)
        self._transport = control_files._transport

    def is_shared(self):
        """Return True if this repository is flagged as a shared repository."""
        return self._transport.has("shared-storage")

    def set_make_working_trees(self, new_value):
        """Set the policy flag for making working trees when creating branches.

        This only applies to branches that use this repository.

        The default is 'True'.
        :param new_value: True to restore the default, False to disable making
                          working trees.
        """
        with self.lock_write():
            if new_value:
                with contextlib.suppress(_mod_transport.NoSuchFile):
                    self._transport.delete("no-working-trees")
            else:
                self._transport.put_bytes(
                    "no-working-trees", b"", mode=self.controldir._get_file_mode()
                )

    def make_working_trees(self):
        """Returns the policy for making working trees on new branches."""
        return not self._transport.has("no-working-trees")

    def update_feature_flags(self, updated_flags):
        """Update the feature flags for this branch.

        :param updated_flags: Dictionary mapping feature names to necessities
            A necessity can be None to indicate the feature should be removed
        """
        with self.lock_write():
            self._format._update_feature_flags(updated_flags)
            self.control_transport.put_bytes("format", self._format.as_string())

    def _find_parent_ids_of_revisions(self, revision_ids):
        """Find all parent ids that are mentioned in the revision graph.

        :return: set of revisions that are parents of revision_ids which are
            not part of revision_ids themselves
        """
        parent_ids = set(
            itertools.chain.from_iterable(self.get_parent_map(revision_ids).values())
        )
        parent_ids.difference_update(revision_ids)
        parent_ids.discard(_mod_revision.NULL_REVISION)
        return parent_ids


class RepositoryFormatMetaDir(bzrdir.BzrFormat, RepositoryFormat):
    """Common base class for the new repositories using the metadir layout."""

    rich_root_data = False
    supports_tree_reference = False
    supports_external_lookups = False
    supports_leaving_lock = True
    supports_nesting_repositories = True

    @property
    def _matchingcontroldir(self):
        matching = bzrdir.BzrDirMetaFormat1()
        matching.repository_format = self
        return matching

    def __init__(self):
        """Initialize a RepositoryFormatMetaDir."""
        RepositoryFormat.__init__(self)
        bzrdir.BzrFormat.__init__(self)

    def _create_control_files(self, a_bzrdir):
        """Create the required files and the initial control_files object."""
        # FIXME: RBC 20060125 don't peek under the covers
        # NB: no need to escape relative paths that are url safe.
        repository_transport = a_bzrdir.get_repository_transport(self)
        control_files = lockable_files.LockableFiles(
            repository_transport, "lock", lockdir.LockDir
        )
        control_files.create_lock()
        return control_files

    def _upload_blank_content(self, a_bzrdir, dirs, files, utf8_files, shared):
        """Upload the initial blank content."""
        control_files = self._create_control_files(a_bzrdir)
        control_files.lock_write()
        transport = control_files._transport
        if shared is True:
            utf8_files += [("shared-storage", b"")]
        try:
            for dir in dirs:
                transport.mkdir(dir, mode=a_bzrdir._get_dir_mode())
            for filename, content_stream in files:
                transport.put_file(
                    filename, content_stream, mode=a_bzrdir._get_file_mode()
                )
            for filename, content_bytes in utf8_files:
                transport.put_bytes_non_atomic(
                    filename, content_bytes, mode=a_bzrdir._get_file_mode()
                )
        finally:
            control_files.unlock()

    @classmethod
    def find_format(klass, a_bzrdir):
        """Return the format for the repository object in a_bzrdir.

        This is used by brz native formats that have a "format" file in
        the repository.  Other methods may be used by different types of
        control directory.
        """
        try:
            transport = a_bzrdir.get_repository_transport(None)
            format_string = transport.get_bytes("format")
        except _mod_transport.NoSuchFile as e:
            raise errors.NoRepositoryPresent(a_bzrdir) from e
        return klass._find_format(format_registry, "repository", format_string)

    def check_support_status(
        self, allow_unsupported, recommend_upgrade=True, basedir=None
    ):
        """Check the support status of this format.

        Args:
            allow_unsupported: Whether to allow unsupported formats.
            recommend_upgrade: Whether to recommend upgrading.
            basedir: The base directory for upgrade recommendations.
        """
        RepositoryFormat.check_support_status(
            self,
            allow_unsupported=allow_unsupported,
            recommend_upgrade=recommend_upgrade,
            basedir=basedir,
        )
        bzrdir.BzrFormat.check_support_status(
            self,
            allow_unsupported=allow_unsupported,
            recommend_upgrade=recommend_upgrade,
            basedir=basedir,
        )
