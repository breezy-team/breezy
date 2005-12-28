# Copyright (C) 2005 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""\
Plugin for generating snapshot information about a bzr tree.
"""

import sys
import codecs

from bzrlib.branch import Branch
from bzrlib.commands import Command, register_command
from bzrlib.errors import BzrCommandError
from bzrlib.option import Option

from generate_version_info import version_formats


def _parse_version_info_format(format):
    try:
        return version_formats[format]
    except KeyError:
        formats = version_formats.keys()
        formats.remove(None)
        raise BzrCommandError('No known version info format %s.'
                ' Supported types are: %s' 
                % (format, formats))


class cmd_version_info(Command):
    """Generate version information about this tree.
    """

    takes_options = [Option('format', type=_parse_version_info_format,
                            help='Select the '),
                     Option('all', help='include all possible information'),
                     Option('check-clean', help='check if tree is clean'),
                     Option('include-history', 
                             help='Include the revision-history')
                     ]
    takes_args = ['location?']

    def run(self, location=None, format=None,
            all=False, check_clean=False, include_history=False):

        if location is None:
            location = u'.'

        if format is None:
            format = version_formats[None]

        # TODO: jam 20051228 This could be open_containing
        b = Branch.open(location)

        outf = codecs.getwriter('utf-8')(sys.stdout)

        include_log_info = False
        include_log_deltas = False
        if all:
            include_history = True
            check_clean = True
            include_log_info = True
            include_log_deltas = True

        format(b, to_file=outf,
                check_for_clean=check_clean,
                include_revision_history=include_history,
                include_log_info=include_log_info,
                include_log_deltas=include_log_deltas)


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
