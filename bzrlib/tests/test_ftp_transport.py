# Copyright (C) 2006 Canonical Ltd
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

from bzrlib import tests
import bzrlib.transport


class TestCaseAFTP(tests.TestCaseWithTransport):
    """Test aftp transport."""

    def test_aftp_degrade(self):
        t = bzrlib.transport.get_transport('aftp://host/path')
        self.failUnless(t.is_active)
        parent = t.clone('..')
        self.failUnless(parent.is_active)

        self.assertEqual('aftp://host/path', t.abspath(''))


class _MedusaFeature(tests.Feature):
    """Some tests want an FTP Server, check if one is available.

    Right now, the only way this is available is if 'medusa' is installed.
    """

    def _probe(self):
        try:
            import medusa
            import medusa.filesys
            import medusa.ftp_server
            return True
        except ImportError:
            return False

    def feature_name(self):
        return 'medusa'

MedusaFeature = _MedusaFeature()


class TestCaseWithFTPServer(tests.TestCaseWithTransport):

    _test_needs_features = [MedusaFeature]

    def setUp(self):
        from bzrlib.transport.ftp import FtpServer
        self.transport_server = FtpServer
        super(TestCaseWithFTPServer, self).setUp()



class TestFTPServer(TestCaseWithFTPServer):

    def test_basic_exists(self):
        url = self.get_url()
        self.assertStartsWith(url, 'ftp://')

        t = self.get_transport()
        t.put_bytes('foo', 'test bytes\n')
        self.assertEqual('test bytes\n', t.get_bytes('foo'))
