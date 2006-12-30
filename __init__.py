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
import bzrlib

__version__ = '0.2.0'
required_bzr_version = (0,14)

def check_bzrlib_version(desired):
    """Check that bzrlib is compatible.

    If version is < desired version, assume incompatible.
    If version == desired version, assume completely compatible
    If version == desired version + 1, assume compatible, with deprecations
    Otherwise, assume incompatible.
    """
    desired_plus = (desired[0], desired[1]+1)
    bzrlib_version = bzrlib.version_info[:2]
    if bzrlib_version == desired:
        return
    try:
        from bzrlib.trace import warning
    except ImportError:
        # get the message out any way we can
        from warnings import warn as warning
    if bzrlib_version < desired:
        warning('Installed bzr version %s is too old to be used with bzr-svn'
                ' %s.' % (bzrlib.__version__, __version__))
        # Not using BzrNewError, because it may not exist.
        raise Exception, ('Version mismatch', desired)
    else:
        warning('bzr-svn is not up to date with installed bzr version %s.'
                ' \nThere should be a newer version of bzr-svn available.' 
                % (bzrlib.__version__))
        if bzrlib_version != desired_plus:
            raise Exception, 'Version mismatch'

check_bzrlib_version(required_bzr_version)

import branch
import convert
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
register_transport('svn://', transport.SvnRaTransport)
register_transport('svn+', transport.SvnRaTransport)

from bzrlib.bzrdir import BzrDirFormat

from bzrlib.repository import InterRepository

from fetch import InterSvnRepository

BzrDirFormat.register_control_format(format.SvnFormat)

BzrDirFormat.register_control_format(checkout.SvnWorkingTreeDirFormat)

InterRepository.register_optimiser(InterSvnRepository)

from bzrlib.commands import Command, register_command, display_command, Option


def get_scheme(schemename):
    """Parse scheme identifier and return a branching scheme."""
    from scheme import BranchingScheme
    from bzrlib.errors import BzrCommandError
    
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
                     Option('scheme', type=get_scheme,
                         help='Branching scheme (none, trunk, or trunk-INT)')]

    @display_command
    def run(self, from_location, to_location=None, trees=False, 
            shared=False, scheme=None):
        from convert import convert_repository
        from scheme import TrunkBranchingScheme

        if scheme is None:
            scheme = TrunkBranchingScheme()

        if to_location is None:
            to_location = os.path.basename(from_location.rstrip("/\\"))

        convert_repository(from_location, to_location, scheme, shared, trees)


register_command(cmd_svn_import)

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

