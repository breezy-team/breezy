# Copyright (C) 2007 Jelmer Vernooij <jelmer@samba.org>

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

from bzrlib.errors import ConnectionReset
from bzrlib.tests import TestCase

from errors import convert_svn_error, convert_error

import svn.core
from svn.core import SubversionException

class TestConvertError(TestCase):
    def test_decorator_unknown(self):
        @convert_svn_error
        def test_throws_svn():
            raise SubversionException(100, "foo")

        self.assertRaises(SubversionException, test_throws_svn)

    def test_decorator_known(self):
        @convert_svn_error
        def test_throws_svn():
            raise SubversionException(svn.core.SVN_ERR_RA_SVN_CONNECTION_CLOSED, "Connection closed")

        self.assertRaises(ConnectionReset, test_throws_svn)

    def test_convert_error_unknown(self):
        self.assertIsInstance(convert_error(SubversionException(100, "foo")),
                SubversionException)

    def test_convert_error_reset(self):
        self.assertIsInstance(convert_error(SubversionException(svn.core.SVN_ERR_RA_SVN_CONNECTION_CLOSED, "Connection closed")), ConnectionReset)


