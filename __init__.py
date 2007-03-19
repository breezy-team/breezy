# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>

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
import bzrlib

try:
    from bzrlib.trace import warning
except ImportError:
    # get the message out any way we can
    from warnings import warn as warning

__version__ = '0.4.0'
compatible_bzr_versions = [(0,15),(0,16)]

def check_bzrlib_version(desired):
    """Check that bzrlib is compatible.

    If version is < all compatible version, assume incompatible.
    If version is compatible version + 1, assume compatible, with deprecations
    Otherwise, assume incompatible.
    """
    bzrlib_version = bzrlib.version_info[:2]
    if bzrlib_version in desired:
        return
    try:
        from bzrlib.trace import warning
    except ImportError:
        # get the message out any way we can
        from warnings import warn as warning
    if bzrlib_version < desired[0]:
        warning('Installed bzr version %s is too old to be used with bzr-svn'
                ' %s.' % (bzrlib.__version__, __version__))
        # Not using BzrNewError, because it may not exist.
        raise Exception, ('Version mismatch', desired)
    else:
        warning('bzr-svn is not up to date with installed bzr version %s.'
                ' \nThere should be a newer version of bzr-svn available.' 
                % (bzrlib.__version__))
        if not (bzrlib_version[0], bzrlib_version[1]-1) in desired:
            raise Exception, 'Version mismatch'

def check_subversion_version():
    """Check that Subversion is compatible.

    """
    try:
        from svn.delta import svn_delta_invoke_txdelta_window_handler
    except:
        warning('Installed Subversion version does not have updated Python bindings. See the bzr-svn README for details.')
        raise bzrlib.errors.BzrError("incompatible python subversion bindings")

def check_pysqlite_version():
    """Check that sqlite library is compatible.

    """
    try:
        try:
            import sqlite3
        except ImportError:
            from pysqlite2 import dbapi2 as sqlite3
    except:
        warning('Needs at least Python2.5 or Python2.4 with the pysqlite2 module')
        raise bzrlib.errors.BzrError("missing sqlite library")

    if (sqlite3.sqlite_version_info[0] < 3 or 
            (sqlite3.sqlite_version_info[0] == 3 and 
             sqlite3.sqlite_version_info[1] < 3)):
        warning('Needs at least sqlite 3.3.x')
        raise bzrlib.errors.BzrError("incompatible sqlite library")

check_bzrlib_version(compatible_bzr_versions)
check_subversion_version()
check_pysqlite_version()

import branch
import convert
import format
import transport
import checkout

from bzrlib.transport import register_transport
register_transport('svn://', transport.SvnRaTransport)
register_transport('svn+', transport.SvnRaTransport)

from bzrlib.bzrdir import BzrDirFormat

from bzrlib.repository import InterRepository

from fetch import InterSvnRepository

BzrDirFormat.register_control_format(format.SvnFormat)

import svn.core
subr_version = svn.core.svn_subr_version()

BzrDirFormat.register_control_format(checkout.SvnWorkingTreeDirFormat)

InterRepository.register_optimiser(InterSvnRepository)

from bzrlib.branch import Branch
from bzrlib.commands import Command, register_command, display_command, Option
from bzrlib.errors import BzrCommandError
from bzrlib.repository import Repository
import bzrlib.urlutils as urlutils


def get_scheme(schemename):
    """Parse scheme identifier and return a branching scheme."""
    from scheme import BranchingScheme
    
    ret = BranchingScheme.find_scheme(schemename)
    if ret is None:
        raise BzrCommandError('No such branching scheme %r' % schemename)
    return ret


class cmd_svn_import(Command):
    """Convert a Subversion repository to a Bazaar repository.
    
    """
    takes_args = ['from_location', 'to_location?']
    takes_options = [Option('trees', help='Create working trees'),
                     Option('shared', help='Create shared repository'),
                     Option('all', help='Convert all revisions, even those not in current branch history (implies --shared)'),
                     Option('scheme', type=get_scheme,
                         help='Branching scheme (none, trunk, or trunk-INT)')]

    @display_command
    def run(self, from_location, to_location=None, trees=False, 
            shared=False, scheme=None, all=False):
        from convert import convert_repository
        from scheme import TrunkBranchingScheme

        if scheme is None:
            scheme = TrunkBranchingScheme()

        if to_location is None:
            to_location = os.path.basename(from_location.rstrip("/\\"))

        if all:
            shared = True
        convert_repository(from_location, to_location, scheme, shared, trees,
                           all)


register_command(cmd_svn_import)

class cmd_svn_upgrade(Command):
    """Upgrade the revisions mapped from Subversion in a Bazaar branch.
    
    This will change the revision ids of revisions whose parents 
    were mapped from svn revisions.
    """
    takes_args = ['svn_repository?']
    takes_options = [Option('allow-changes', help='Allow content changes')]

    @display_command
    def run(self, svn_repository=None, allow_changes=False):
        from upgrade import upgrade_branch
        
        branch_to = Branch.open(".")

        stored_loc = branch_to.get_parent()
        if svn_repository is None:
            if stored_loc is None:
                raise BzrCommandError("No pull location known or"
                                             " specified.")
            else:
                display_url = urlutils.unescape_for_display(stored_loc,
                        self.outf.encoding)
                self.outf.write("Using saved location: %s\n" % display_url)
                svn_repository = stored_loc

        upgrade_branch(branch_to, Repository.open(svn_repository), 
                       allow_changes)

register_command(cmd_svn_upgrade)


def test_suite():
    from unittest import TestSuite, TestLoader
    import tests
    suite = TestSuite()
    suite.addTest(tests.test_suite())
    return suite

if __name__ == '__main__':
    print ("This is a Bazaar plugin. Copy this directory to ~/.bazaar/plugins "
          "to use it.\n")
    runner = unittest.TextTestRunner()
    runner.run(test_suite())
else:
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
