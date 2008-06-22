# Copyright (C) 2007 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib.errors import (ConnectionError, ConnectionReset, LockError, 
                           PermissionDenied, TransportError,
                           UnexpectedEndOfContainerError)
from bzrlib.tests import TestCase

from bzrlib.plugins.svn.core import SubversionException
from bzrlib.plugins.svn.errors import *

class TestConvertError(TestCase):
    def test_decorator_unknown(self):
        @convert_svn_error
        def test_throws_svn():
            raise SubversionException("foo", 2000)

        self.assertRaises(SubversionException, test_throws_svn)

    def test_decorator_known(self):
        @convert_svn_error
        def test_throws_svn():
            raise SubversionException("Connection closed", ERR_RA_SVN_CONNECTION_CLOSED)

        self.assertRaises(ConnectionReset, test_throws_svn)

    def test_convert_error_oserror(self):
        self.assertIsInstance(convert_error(SubversionException("foo", 13)),
                OSError)

    def test_convert_error_unknown(self):
        self.assertIsInstance(convert_error(SubversionException("foo", -4)),
                SubversionException)

    def test_convert_malformed(self):
        self.assertIsInstance(convert_error(SubversionException("foo", ERR_RA_SVN_MALFORMED_DATA)), TransportError)

    def test_convert_error_reset(self):
        self.assertIsInstance(convert_error(SubversionException("Connection closed", ERR_RA_SVN_CONNECTION_CLOSED)), ConnectionReset)

    def test_convert_error_lock(self):
        self.assertIsInstance(convert_error(SubversionException("Working copy locked", ERR_WC_LOCKED)), LockError)

    def test_convert_perm_denied(self):
        self.assertIsInstance(convert_error(SubversionException("Permission Denied", ERR_RA_NOT_AUTHORIZED)), PermissionDenied)

    def test_convert_unexpected_end(self):
        self.assertIsInstance(convert_error(SubversionException("Unexpected end of stream", ERR_INCOMPLETE_DATA)), UnexpectedEndOfContainerError)

    def test_convert_unknown_hostname(self):
        self.assertIsInstance(convert_error(SubversionException("Unknown hostname 'bla'", ERR_UNKNOWN_HOSTNAME)), ConnectionError)

    def test_not_implemented(self):
        self.assertIsInstance(convert_error(SubversionException("Remote server doesn't support ...", ERR_RA_NOT_IMPLEMENTED)), NotImplementedError)

    def test_decorator_nothrow(self):
        @convert_svn_error
        def test_nothrow(foo):
            return foo+1
        self.assertEqual(2, test_nothrow(1))

    def test_invalid_property_value(self):
        error = InvalidPropertyValue("svn:foobar", "corrupt")

        self.assertEqual(
          "Invalid property value for Subversion property svn:foobar: corrupt", 
          str(error))

    def test_notsvnbranchpath_nonascii(self):
        NotSvnBranchPath('\xc3\xb6', None)

    def test_invalidsvnbranchpath_nonascii(self):
        InvalidSvnBranchPath('\xc3\xb6', None)

