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
import tempfile
import unittest
import bzrlib

from bzrlib.trace import warning, mutter

__version__ = '0.4.0'
COMPATIBLE_BZR_VERSIONS = [(0, 15), (0, 16), (0, 17), (0, 18)]

def check_bzrlib_version(desired):
    """Check that bzrlib is compatible.

    If version is < all compatible version, assume incompatible.
    If version is compatible version + 1, assume compatible, with deprecations
    Otherwise, assume incompatible.
    """
    bzrlib_version = bzrlib.version_info[:2]
    if bzrlib_version in desired:
        return
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
    import svn.delta
    if not hasattr(svn.delta, 'svn_delta_invoke_txdelta_window_handler'):
        warning('Installed Subversion version does not have updated Python '
                'bindings. See the bzr-svn README for details.')
        raise bzrlib.errors.BzrError("incompatible python subversion bindings")

check_bzrlib_version(COMPATIBLE_BZR_VERSIONS)
check_subversion_version()

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

from fetch import InterFromSvnRepository
from commit import InterToSvnRepository

BzrDirFormat.register_control_format(format.SvnFormat)

import svn.core
_subr_version = svn.core.svn_subr_version()

BzrDirFormat.register_control_format(checkout.SvnWorkingTreeDirFormat)

InterRepository.register_optimiser(InterFromSvnRepository)
InterRepository.register_optimiser(InterToSvnRepository)

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
                     Option('standalone', help='Create standalone branches'),
                     Option('all', 
                         help='Convert all revisions, even those not in '
                              'current branch history (forbids --standalone)'),
                     Option('scheme', type=get_scheme,
                         help='Branching scheme (none, trunk, or trunk-INT)')]

    @display_command
    def run(self, from_location, to_location=None, trees=False, 
            standalone=False, scheme=None, all=False):
        from convert import convert_repository
        from scheme import TrunkBranchingScheme

        if scheme is None:
            scheme = TrunkBranchingScheme()

        if to_location is None:
            to_location = os.path.basename(from_location.rstrip("/\\"))

        if all:
            standalone = False

        if os.path.isfile(from_location):
            from convert import load_dumpfile
            tmp_repos = tempfile.mkdtemp(prefix='bzr-svn-dump-')
            mutter('loading dumpfile %r to %r' % (from_location, tmp_repos))
            load_dumpfile(from_location, tmp_repos)
            from_location = tmp_repos
        else:
            tmp_repos = None

        from_repos = Repository.open(from_location)

        convert_repository(from_repos, to_location, scheme, not standalone, 
                trees, all)

        if tmp_repos is not None:
            from bzrlib import osutils
            osutils.rmtree(tmp_repos)


register_command(cmd_svn_import)

class cmd_svn_upgrade(Command):
    """Upgrade revisions mapped from Subversion in a Bazaar branch.
    
    This will change the revision ids of revisions whose parents 
    were mapped from svn revisions.
    """
    takes_args = ['svn_repository?']
    takes_options = []

    @display_command
    def run(self, svn_repository=None):
        from upgrade import upgrade_branch
        from bzrlib.errors import NoWorkingTree
        from bzrlib.workingtree import WorkingTree
        try:
            wt_to = WorkingTree.open(".")
            branch_to = wt_to.branch
        except NoWorkingTree:
            wt_to = None
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
                svn_repository = Branch.open(stored_loc).repository
        else:
            svn_repository = Repository.open(svn_repository)

        upgrade_branch(branch_to, svn_repository, allow_changes=True)

        if wt_to is not None:
            wt_to.set_last_revision(branch_to.last_revision())

register_command(cmd_svn_upgrade)


def test_suite():
    from unittest import TestSuite
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
