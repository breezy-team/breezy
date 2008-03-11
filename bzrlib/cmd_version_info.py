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

"""Commands for generating snapshot information about a bzr tree."""

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    branch,
    errors,
    workingtree,
    )
""")
from bzrlib import (
    version_info_formats,
    )
from bzrlib.commands import Command
from bzrlib.option import Option, RegistryOption


def _parse_version_info_format(format):
    """Convert a string passed by the user into a VersionInfoFormat.

    This looks in the version info format registry, and if the format
    cannot be found, generates a useful error exception.
    """
    try:
        return version_info_formats.get_builder(format)
    except KeyError:
        formats = version_info_formats.get_builder_formats()
        raise errors.BzrCommandError('No known version info format %s.'
                                     ' Supported types are: %s'
                                     % (format, formats))


class cmd_version_info(Command):
    """Show version information about this tree.

    You can use this command to add information about version into
    source code of an application. The output can be in one of the
    supported formats or in a custom format based on a template.

    For example::

      bzr version-info --custom \\
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

    takes_options = [RegistryOption('format',
                            'Select the output format.',
                            version_info_formats.format_registry,
                            value_switches=True),
                     Option('all', help='Include all possible information.'),
                     Option('check-clean', help='Check if tree is clean.'),
                     Option('include-history',
                            help='Include the revision-history.'),
                     Option('include-file-revisions',
                            help='Include the last revision for each file.'),
                     Option('template', type=str, help='Template for the output.'),
                     ]
    takes_args = ['location?']

    encoding_type = 'exact'

    def run(self, location=None, format=None,
            all=False, check_clean=False, include_history=False,
            include_file_revisions=False, template=None):

        if location is None:
            location = '.'

        if format is None:
            format = version_info_formats.format_registry.get()

        wt = None
        try:
            wt = workingtree.WorkingTree.open_containing(location)[0]
        except errors.NoWorkingTree:
            b = branch.Branch.open(location)
        else:
            b = wt.branch

        if all or template:
            include_history = True
            check_clean = True
            include_file_revisions=True

        builder = format(b, working_tree=wt,
                check_for_clean=check_clean,
                include_revision_history=include_history,
                include_file_revisions=include_file_revisions,
                template=template)
        builder.generate(self.outf)
