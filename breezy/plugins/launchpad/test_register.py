# Copyright (C) 2006-2012, 2016-2017 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

from io import BytesIO

from xmlrpc.client import (
    loads as xmlrpc_loads,
    Transport,
    )

from ...tests import TestCaseWithTransport

# local import
from .lp_registration import (
    BaseRequest,
    ResolveLaunchpadPathRequest,
    LaunchpadService,
    )


# TODO: Test that the command-line client, making sure that it'll pass the
# request through to a dummy transport, and that the transport will validate
# the results passed in.  Not sure how to get the transport object back out to
# validate that its OK - may not be necessary.

class InstrumentedXMLRPCConnection(object):
    """Stands in place of an http connection for the purposes of testing"""

    def __init__(self, testcase):
        self.testcase = testcase

    def getreply(self):
        """Fake the http reply.

        :returns: (errcode, errmsg, headers)
        """
        return (200, 'OK', [])

    def getresponse(self, buffering=True):
        """Fake the http reply.

        This is used when running on Python 2.7, where xmlrpclib uses
        httplib.HTTPConnection in a different way than before.
        """
        class FakeHttpResponse(object):

            def __init__(self, status, reason, body):
                self.status = status
                self.reason = reason
                self.body = body

            def read(self, size=-1):
                return self.body.read(size)

            def getheader(self, name, default):
                # We don't have headers
                return default

        return FakeHttpResponse(200, 'OK', self.getfile())

    def getfile(self):
        """Return a fake file containing the response content."""
        return BytesIO(b'''\
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


class InstrumentedXMLRPCTransport(Transport):

    # Python 2.5's xmlrpclib looks for this.
    _use_datetime = False
    _use_builtin_types = False

    def __init__(self, testcase):
        self.testcase = testcase
        self._connection = (None, None)

    def make_connection(self, host):
        host, http_headers, x509 = self.get_host_info(host)
        test = self.testcase
        self.connected_host = host
        if http_headers:
            raise AssertionError()
        return InstrumentedXMLRPCConnection(test)

    def send_request(self, host, handler_path, request_body,
                     verbose=None):
        self.connected_host = host
        test = self.testcase
        self.got_request = True
        unpacked, method = xmlrpc_loads(request_body)
        if None in unpacked:
            raise AssertionError(
                "xmlrpc result %r shouldn't contain None" % (unpacked,))
        self.sent_params = unpacked
        return InstrumentedXMLRPCConnection(test)

    def send_host(self, conn, host):
        pass

    def send_user_agent(self, conn):
        # TODO: send special user agent string, including breezy version
        # number
        pass

    def send_content(self, conn, request_body):
        unpacked, method = xmlrpc_loads(request_body)
        if None in unpacked:
            raise AssertionError(
                "xmlrpc result %r shouldn't contain None" % (unpacked,))
        self.sent_params = unpacked


class MockLaunchpadService(LaunchpadService):

    def send_request(self, method_name, method_params, verbose=None):
        """Stash away the method details rather than sending them to a real server"""
        self.called_method_name = method_name
        self.called_method_params = method_params


class TestResolveLaunchpadPathRequest(TestCaseWithTransport):

    def setUp(self):
        super(TestResolveLaunchpadPathRequest, self).setUp()
        # make sure we have a reproducible standard environment
        self.overrideEnv('BRZ_LP_XMLRPC_URL', None)

    def test_onto_transport(self):
        """A request is transmitted across a mock Transport"""
        transport = InstrumentedXMLRPCTransport(self)
        service = LaunchpadService(transport)
        resolve = ResolveLaunchpadPathRequest('bzr')
        resolve.submit(service)
        self.assertEqual(transport.connected_host, 'xmlrpc.launchpad.net')
        self.assertEqual(len(transport.sent_params), 1)
        self.assertEqual(transport.sent_params, ('bzr', ))
        self.assertTrue(transport.got_request)

    def test_subclass_request(self):
        """Define a new type of xmlrpc request"""
        class DummyRequest(BaseRequest):
            _methodname = 'dummy_request'

            def _request_params(self):
                return (42,)

        service = MockLaunchpadService()
        service.registrant_email = 'test@launchpad.net'
        service.registrant_password = ''
        request = DummyRequest()
        request.submit(service)
        self.assertEqual(service.called_method_name, 'dummy_request')
        self.assertEqual(service.called_method_params, (42,))

    def test_mock_resolve_lp_url(self):
        test_case = self

        class MockService(MockLaunchpadService):
            def send_request(self, method_name, method_params,
                             verbose=None):
                test_case.assertEqual(method_name, "resolve_lp_path")
                test_case.assertEqual(list(method_params), ['bzr'])
                return dict(urls=[
                    'bzr+ssh://bazaar.launchpad.net~bzr/bzr/trunk',
                    'sftp://bazaar.launchpad.net~bzr/bzr/trunk',
                    'bzr+http://bazaar.launchpad.net~bzr/bzr/trunk',
                    'http://bazaar.launchpad.net~bzr/bzr/trunk'])
        service = MockService()
        resolve = ResolveLaunchpadPathRequest('bzr')
        result = resolve.submit(service)
        self.assertTrue('urls' in result)
        self.assertEqual(result['urls'], [
            'bzr+ssh://bazaar.launchpad.net~bzr/bzr/trunk',
            'sftp://bazaar.launchpad.net~bzr/bzr/trunk',
            'bzr+http://bazaar.launchpad.net~bzr/bzr/trunk',
            'http://bazaar.launchpad.net~bzr/bzr/trunk'])
