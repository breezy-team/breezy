# Copyright (C) 2005-2006 Jelmer Vernooij <jelmer@samba.org>

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

"""
Support for foreign branches (Subversion)
"""
import os
import sys
import unittest

import branch
import convert
import dumpfile
import format
import transport
import checkout

def convert_svn_exception(unbound):
    """Decorator that catches particular Subversion exceptions and 
    converts them to Bazaar exceptions.
    """
    def convert(self, *args, **kwargs):
        try:
            unbound(self, *args, **kwargs)
        except SubversionException, (msg, num):
            if num == svn.core.SVN_ERR_RA_SVN_CONNECTION_CLOSED:
                raise ConnectionReset(msg=msg)
            else:
                raise

    convert.__doc__ = unbound.__doc__
    convert.__name__ = unbound.__name__
    return convert

from bzrlib.transport import register_transport
register_transport('svn:', transport.SvnRaTransport)
register_transport('svn+', transport.SvnRaTransport)

from bzrlib.bzrdir import BzrDirFormat

from bzrlib.repository import InterRepository

from fetch import InterSvnRepository

BzrDirFormat.register_control_format(format.SvnFormat)

BzrDirFormat.register_control_format(checkout.SvnWorkingTreeDirFormat)

BzrDirFormat.register_control_format(dumpfile.SvnDumpFileFormat)

InterRepository.register_optimiser(InterSvnRepository)

from bzrlib.commands import Command, register_command, display_command, Option

class cmd_import_svn(Command):
    """Convert a Subversion repository to a Bazaar repository.
    
    """
    takes_args = ['url', 'output_dir']
    takes_options = [Option('trees', help='Create working trees'),
                     Option('shared', help='Create shared repository')]

    @display_command
    def run(self, url, output_dir, trees=False, shared=False):
        from convert import convert_repository
        from scheme import TrunkBranchingScheme
        # TODO: support non-trunk branching schemes
        convert_repository(url, output_dir, TrunkBranchingScheme(), shared, 
                           trees)


register_command(cmd_import_svn)

def test_suite():
    from unittest import TestSuite, TestLoader
    import tests

    suite = TestSuite()

    suite.addTest(tests.test_suite())

    return suite

if __name__ == '__main__':
    print ("This is a Bazaar plugin. Copy this directory to ~/.bazaar/plugins "
          "to use it.\n")
else:
    sys.path.append(os.path.dirname(__file__))

