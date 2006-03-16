# Copyright (C) 2006 by Canonical Ltd
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

import base64
from StringIO import StringIO
import xmlrpclib

from bzrlib.tests import TestCase

# local import
from lp_registration import BranchRegistrationRequest


class InstrumentedXMLRPCConnection(object):
    """Stands in place of an http connection for the purposes of testing"""

    def __init__(self, testcase):
        self.testcase = testcase

    def getreply(self):
        """Fake the http reply.

        :returns: (errcode, errmsg, headers)
        """
        return (200, 'OK', [])

    def getfile(self):
        """Return a fake file containing the response content."""
        return StringIO('''\
<?xml version="1.0" ?>
<methodResponse>
<params>
<param>
<value>
<string>victoria dock</string>
</value>
</param>
</params>
</methodResponse>''')



class InstrumentedXMLRPCTransport(xmlrpclib.Transport):

    def __init__(self, testcase):
        self.testcase = testcase

    def make_connection(self, host):
        host, http_headers, x509 = self.get_host_info(host)
        test = self.testcase
        self.connected_host = host
        auth_hdrs = [v for k,v in http_headers if k == 'Authorization']
        assert len(auth_hdrs) == 1
        authinfo = auth_hdrs[0]
        expected_auth = 'testuser@launchpad.net:testpassword'
        test.assertEquals(authinfo,
                'Basic ' + base64.encodestring(expected_auth).strip())
        return InstrumentedXMLRPCConnection(test)

    def send_request(self, connection, handler_path, request_body):
        test = self.testcase
        test.assertEquals(handler_path, '/branch/')
        self.got_request = True

    def send_host(self, conn, host):
        pass

    def send_user_agent(self, conn):
        # TODO: send special user agent string, including bzrlib version
        # number
        pass

    def send_content(self, conn, request_body):
        unpacked, method = xmlrpclib.loads(request_body)
        assert None not in unpacked, \
                "xmlrpc result %r shouldn't contain None" % (unpacked,)
        self.sent_params = unpacked


class TestBranchRegistration(TestCase):
    SAMPLE_URL = 'http://bazaar-vcs.org/bzr/bzr.dev/'
    SAMPLE_OWNER = 'jhacker@foo.com'
    SAMPLE_BRANCH_ID = 'bzr.dev'

    def test_10_register_help(self):
        out, err = self.run_bzr('register-branch', '--help')
        self.assertContainsRe(out, r'Register a branch')

    def test_20_register_no_url(self):
        self.run_bzr('register-branch', retcode=3)

    def test_21_register_cmd_simple_branch(self):
        """Register a well-known branch to fake server"""
        # disabled until we can set a different transport within the command
        # command
        ## self.run_bzr('register-branch', self.SAMPLE_URL)

    def test_40_onto_transport(self):
        """Test how the request is sent by transmitting across a mock Transport"""
        transport = InstrumentedXMLRPCTransport(self)
        rego = BranchRegistrationRequest('http://test-server.com/bzr/branch',
                'branch-id')
        rego.submit(transport=transport)
        self.assertEquals(transport.connected_host, 'xmlrpc.launchpad.net')
        self.assertEquals(len(transport.sent_params), 4)
        self.assertTrue(transport.got_request)
