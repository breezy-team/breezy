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

"""Plugin for generating snapshot information about a bzr tree."""

import sys
import codecs

from bzrlib.branch import Branch
from bzrlib.commands import Command, register_command
from bzrlib.errors import BzrCommandError
from bzrlib.option import Option
from bzrlib.workingtree import WorkingTree

import version_info_formats


def _parse_version_info_format(format):
    try:
        return version_info_formats.get_builder(format)
    except KeyError:
        formats = version_info_formats.get_builder_formats()
        raise BzrCommandError('No known version info format %s.'
                              ' Supported types are: %s'
                              % (format, formats))


class cmd_version_info(Command):
    """Generate version information about this tree."""

    takes_options = [Option('format', type=_parse_version_info_format,
                            help='Select the output format'),
                     Option('all', help='include all possible information'),
                     Option('check-clean', help='check if tree is clean'),
                     Option('include-history',
                            help='Include the revision-history'),
                     Option('include-file-revisions',
                            help='Include the last revision for each file')
                     ]
    takes_args = ['location?']

    encoding_type = 'exact'

    def run(self, location=None, format=None,
            all=False, check_clean=False, include_history=False,
            include_file_revisions=False):

        if location is None:
            location = u'.'

        if format is None:
            format = version_info_formats.get_builder(None)

        wt = None
        try:
            wt = WorkingTree.open_containing(location)[0]
        except NoWorkingTree:
            b = Branch.open(location)
        else:
            b = wt.branch

        if all:
            include_history = True
            check_clean = True
            include_file_revisions=True

        builder = format(b, working_tree=wt,
                check_for_clean=check_clean,
                include_revision_history=include_history,
                include_file_revisions=include_file_revisions)
        builder.generate(self.outf)


register_command(cmd_version_info)


def test_suite():
    from bzrlib.tests.TestUtil import TestLoader, TestSuite
    import test_version_info
    import test_bb_version_info

    suite = TestSuite()
    loader = TestLoader()
    suite.addTest(loader.loadTestsFromModule(test_version_info))
    suite.addTest(loader.loadTestsFromModule(test_bb_version_info))

    return suite
