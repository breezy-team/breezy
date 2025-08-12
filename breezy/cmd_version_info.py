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

"""Commands for generating snapshot information about a brz tree."""

from .lazy_import import lazy_import

lazy_import(
    globals(),
    """
from breezy import (
    branch,
    workingtree,
    )
from breezy.i18n import gettext
""",
)

from . import errors
from .commands import Command
from .option import Option, RegistryOption


def _parse_version_info_format(format):
    """Convert a string passed by the user into a VersionInfoFormat.

    This looks in the version info format registry, and if the format
    cannot be found, generates a useful error exception.
    """
    from . import version_info_formats

    try:
        return version_info_formats.get_builder(format)
    except KeyError as err:
        formats = version_info_formats.get_builder_formats()
        raise errors.CommandError(
            gettext(
                "No known version info format {0}. Supported types are: {1}"
            ).format(format, formats)
        ) from err


class cmd_version_info(Command):
    r"""Show version information about this tree.

    You can use this command to add information about version into
    source code of an application. The output can be in one of the
    supported formats or in a custom format based on a template.

    For example::

      brz version-info --custom \\
        --template="#define VERSION_INFO \\"Project 1.2.3 (r{revno})\\"\\n"

    will produce a C header file with formatted string containing the
    current revision number. Other supported variables in templates are:

      * {date} - date of the last revision
      * {build_date} - current date
      * {revno} - revision number
      * {revision_id} - revision id
      * {branch_nick} - branch nickname
      * {clean} - 0 if the source tree contains uncommitted changes,
                  otherwise 1
    """

    takes_options = [
        RegistryOption(
            "format",
            "Select the output format.",
            value_switches=True,
            lazy_registry=("breezy.version_info_formats", "format_registry"),
        ),
        Option("all", help="Include all possible information."),
        Option("check-clean", help="Check if tree is clean."),
        Option("include-history", help="Include the revision-history."),
        Option(
            "include-file-revisions", help="Include the last revision for each file."
        ),
        Option("template", type=str, help="Template for the output."),
        "revision",
    ]
    takes_args = ["location?"]

    encoding_type = "replace"

    def run(
        self,
        location=None,
        format=None,
        all=False,
        check_clean=False,
        include_history=False,
        include_file_revisions=False,
        template=None,
        revision=None,
    ):
        """Run the version-info command.

        Args:
            location: Path to the branch or working tree to examine. Defaults to current directory.
            format: Output format for version information. If None, uses default format.
            all: If True, include all possible information (history, clean status, file revisions).
            check_clean: If True, check if the tree has uncommitted changes.
            include_history: If True, include the revision history.
            include_file_revisions: If True, include the last revision for each file.
            template: Custom template string for output formatting.
            revision: Specific revision to examine. Must be a single revision specifier.

        Raises:
            CommandError: If more than one revision specifier is provided.
        """
        if revision and len(revision) > 1:
            raise errors.CommandError(
                gettext(
                    "brz version-info --revision takes exactly one revision specifier"
                )
            )

        if location is None:
            location = "."

        if format is None:
            from . import version_info_formats

            format = version_info_formats.format_registry.get()

        try:
            wt = workingtree.WorkingTree.open_containing(location)[0]
        except errors.NoWorkingTree:
            b = branch.Branch.open(location)
            wt = None
        else:
            b = wt.branch

        if all:
            include_history = True
            check_clean = True
            include_file_revisions = True
        if template:
            include_history = True
            include_file_revisions = True
            if "{clean}" in template:
                check_clean = True

        revision_id = revision[0].as_revision_id(b) if revision is not None else None

        builder = format(
            b,
            working_tree=wt,
            check_for_clean=check_clean,
            include_revision_history=include_history,
            include_file_revisions=include_file_revisions,
            template=template,
            revision_id=revision_id,
        )
        builder.generate(self.outf)
