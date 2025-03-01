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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Routines for extracting all version information from a bzr branch."""

import time
from contextlib import ExitStack
from typing import Type

from breezy import registry
from breezy import revision as _mod_revision
from breezy.osutils import format_date, local_time_offset


def create_date_str(timestamp=None, offset=None):
    """Just a wrapper around format_date to provide the right format.

    We don't want to use '%a' in the time string, because it is locale
    dependant. We also want to force timezone original, and show_offset

    Without parameters this function yields the current date in the local
    time zone.
    """
    if timestamp is None and offset is None:
        timestamp = time.time()
        offset = local_time_offset()
    return format_date(
        timestamp,
        offset,
        date_fmt="%Y-%m-%d %H:%M:%S",
        timezone="original",
        show_offset=True,
    )


class VersionInfoBuilder:
    """A class which lets you build up information about a revision."""

    def __init__(
        self,
        branch,
        working_tree=None,
        check_for_clean=False,
        include_revision_history=False,
        include_file_revisions=False,
        template=None,
        revision_id=None,
    ):
        """Build up information about the given branch.
        If working_tree is given, it can be checked for changes.

        :param branch: The branch to work on
        :param working_tree: If supplied, preferentially check
            the working tree for changes.
        :param check_for_clean: If False, we will skip the expense
            of looking for changes.
        :param include_revision_history: If True, the output
            will include the full mainline revision history, including
            date and message
        :param include_file_revisions: The output should
            include the explicit last-changed revision for each file.
        :param template: Template for the output formatting, not used by
            all builders.
        :param revision_id: Revision id to print version for (optional)
        """
        self._branch = branch
        self._check = check_for_clean
        self._include_history = include_revision_history
        self._include_file_revs = include_file_revisions
        self._template = template

        self._clean = None
        self._file_revisions = {}
        self._revision_id = revision_id

        if self._revision_id is None:
            self._tree = working_tree
            self._working_tree = working_tree
        else:
            self._tree = self._branch.repository.revision_tree(self._revision_id)
            # the working tree is not relevant if an explicit revision was specified
            self._working_tree = None

    def _extract_file_revisions(self):
        """Extract the working revisions for all files."""
        if self._tree is None:
            return

        # Things seem clean if we never look :)
        self._clean = True

        with ExitStack() as es:
            if self._working_tree is self._tree:
                basis_tree = self._working_tree.basis_tree()
                # TODO: jam 20070215 The working tree should actually be locked at
                #       a higher level, but this will do for now.
                es.enter_context(self._working_tree.lock_read())
            else:
                basis_tree = self._branch.repository.revision_tree(self._revision_id)

            es.enter_context(basis_tree.lock_read())
            # Build up the list from the basis inventory
            for info in basis_tree.list_files(include_root=True):
                self._file_revisions[info[0]] = info[-1].revision

            if not self._check or self._working_tree is not self._tree:
                return

            delta = self._working_tree.changes_from(
                basis_tree, include_root=True, want_unversioned=True
            )

            # Using a 2-pass algorithm for renames. This is because you might have
            # renamed something out of the way, and then created a new file
            # in which case we would rather see the new marker
            # Or you might have removed the target, and then renamed
            # in which case we would rather see the renamed marker
            for change in delta.renamed:
                self._clean = False
                self._file_revisions[change.path[0]] = "renamed to {}".format(
                    change.path[1]
                )
            for change in delta.removed:
                self._clean = False
                self._file_revisions[change.path[0]] = "removed"
            for change in delta.added:
                self._clean = False
                self._file_revisions[change.path[1]] = "new"
            for change in delta.renamed:
                self._clean = False
                self._file_revisions[change.path[1]] = "renamed from {}".format(
                    change.path[0]
                )
            for change in delta.copied:
                self._clean = False
                self._file_revisions[change.path[1]] = "copied from {}".format(
                    change.path[0]
                )
            for change in delta.modified:
                self._clean = False
                self._file_revisions[change.path[1]] = "modified"
            for change in delta.unversioned:
                self._clean = False
                self._file_revisions[change.path[1]] = "unversioned"

    def _iter_revision_history(self):
        """Find the messages for all revisions in history."""
        last_rev = self._get_revision_id()

        repository = self._branch.repository
        with repository.lock_read():
            graph = repository.get_graph()
            revhistory = list(
                graph.iter_lefthand_ancestry(last_rev, [_mod_revision.NULL_REVISION])
            )
            for revision_id in reversed(revhistory):
                rev = repository.get_revision(revision_id)
                yield (rev.revision_id, rev.message, rev.timestamp, rev.timezone)

    def _get_revision_id(self):
        """Get the revision id we are working on."""
        if self._revision_id is not None:
            return self._revision_id
        if self._working_tree is not None:
            return self._working_tree.last_revision()
        return self._branch.last_revision()

    def _get_revno_str(self, revision_id):
        numbers = self._branch.revision_id_to_dotted_revno(revision_id)
        revno_str = ".".join([str(num) for num in numbers])
        return revno_str

    def generate(self, to_file):
        """Output the version information to the supplied file.

        :param to_file: The file to write the stream to. The output
                will already be encoded, so to_file should not try
                to change encodings.
        :return: None
        """
        raise NotImplementedError(VersionInfoBuilder.generate)


format_registry = registry.Registry[str, Type[VersionInfoBuilder]]()


format_registry.register_lazy(
    "rio",
    "breezy.version_info_formats.format_rio",
    "RioVersionInfoBuilder",
    "Version info in RIO (simple text) format (default).",
)
format_registry.register_lazy(
    "yaml",
    "breezy.version_info_formats.format_yaml",
    "YamlVersionInfoBuilder",
    "Version info in YAML format.",
)
format_registry.register_lazy(
    "python",
    "breezy.version_info_formats.format_python",
    "PythonVersionInfoBuilder",
    "Version info in Python format.",
)
format_registry.register_lazy(
    "custom",
    "breezy.version_info_formats.format_custom",
    "CustomVersionInfoBuilder",
    "Version info in Custom template-based format.",
)
format_registry.default_key = "rio"
