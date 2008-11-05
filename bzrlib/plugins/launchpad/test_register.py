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

import base64
import os
from StringIO import StringIO
import urlparse
import xmlrpclib

from bzrlib import (
    config,
    osutils,
    tests,
    ui,
    )
from bzrlib.tests import TestCaseWithTransport, TestSkipped

# local import
from bzrlib.plugins.launchpad.lp_registration import (
        BaseRequest,
        BranchBugLinkRequest,
        BranchRegistrationRequest,
        ResolveLaunchpadPathRequest,
        LaunchpadService,
        )


# TODO: Test that the command-line client, making sure that it'll pass the
# request through to a dummy transport, and that the transport will validate
# the results passed in.  Not sure how to get the transport object back out to
# validate that its OK - may not be necessary.

# TODO: Add test for (and implement) other command-line options to set
# project, author_email, description.

# TODO: project_id is not properly handled -- must be passed in rpc or path.

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

    # Python 2.5's xmlrpclib looks for this.
    _use_datetime = False

    def __init__(self, testcase, expect_auth):
        self.testcase = testcase
        self.expect_auth = expect_auth

    def make_connection(self, host):
        host, http_headers, x509 = self.get_host_info(host)
        test = self.testcase
        self.connected_host = host
        if self.expect_auth:
            auth_hdrs = [v for k,v in http_headers if k == 'Authorization']
            if len(auth_hdrs) != 1:
                raise AssertionError("multiple auth headers: %r"
                    % (auth_hdrs,))
            authinfo = auth_hdrs[0]
            expected_auth = 'testuser@launchpad.net:testpassword'
            test.assertEquals(authinfo,
                    'Basic ' + base64.encodestring(expected_auth).strip())
        elif http_headers:
            raise AssertionError()
        return InstrumentedXMLRPCConnection(test)

    def send_request(self, connection, handler_path, request_body):
        test = self.testcase
        self.got_request = True

    def send_host(self, conn, host):
        pass

    def send_user_agent(self, conn):
        # TODO: send special user agent string, including bzrlib version
        # number
        pass

    def send_content(self, conn, request_body):
        unpacked, method = xmlrpclib.loads(request_body)
        if None in unpacked:
            raise AssertionError(
                "xmlrpc result %r shouldn't contain None" % (unpacked,))
        self.sent_params = unpacked


class MockLaunchpadService(LaunchpadService):

    def send_request(self, method_name, method_params, authenticated):
        """Stash away the method details rather than sending them to a real server"""
        self.called_method_name = method_name
        self.called_method_params = method_params
        self.called_authenticated = authenticated


class TestBranchRegistration(TestCaseWithTransport):
    SAMPLE_URL = 'http://bazaar-vcs.org/bzr/bzr.dev/'
    SAMPLE_OWNER = 'jhacker@foo.com'
    SAMPLE_BRANCH_ID = 'bzr.dev'

    def setUp(self):
        super(TestBranchRegistration, self).setUp()
        # make sure we have a reproducible standard environment
        self._captureVar('BZR_LP_XMLRPC_URL', None)

    def test_register_help(self):
        """register-branch accepts --help"""
        out, err = self.run_bzr(['register-branch', '--help'])
        self.assertContainsRe(out, r'Register a branch')

    def test_register_no_url_no_branch(self):
        """register-branch command requires parameters"""
        self.make_repository('.')
        self.run_bzr_error(
            ['register-branch requires a public branch url - '
             'see bzr help register-branch'],
            'register-branch')

    def test_register_no_url_in_published_branch_no_error(self):
        b = self.make_branch('.')
        b.set_public_branch('http://test-server.com/bzr/branch')
        out, err = self.run_bzr(['register-branch', '--dry-run'])
        self.assertEqual('Branch registered.\n', out)
        self.assertEqual('', err)

    def test_register_no_url_in_unpublished_branch_errors(self):
        b = self.make_branch('.')
        out, err = self.run_bzr_error(['no public branch'],
            ['register-branch', '--dry-run'])
        self.assertEqual('', out)

    def test_register_dry_run(self):
        out, err = self.run_bzr(['register-branch',
                                'http://test-server.com/bzr/branch',
                                '--dry-run'])
        self.assertEquals(out, 'Branch registered.\n')

    def test_onto_transport(self):
        """Test how the request is sent by transmitting across a mock Transport"""
        # use a real transport, but intercept at the http/xml layer
        transport = InstrumentedXMLRPCTransport(self, expect_auth=True)
        service = LaunchpadService(transport)
        service.registrant_email = 'testuser@launchpad.net'
        service.registrant_password = 'testpassword'
        rego = BranchRegistrationRequest('http://test-server.com/bzr/branch',
                'branch-id',
                'my test branch',
                'description',
                'author@launchpad.net',
                'product')
        rego.submit(service)
        self.assertEquals(transport.connected_host, 'xmlrpc.edge.launchpad.net')
        self.assertEquals(len(transport.sent_params), 6)
        self.assertEquals(transport.sent_params,
                ('http://test-server.com/bzr/branch',  # branch_url
                 'branch-id',                          # branch_name
                 'my test branch',                     # branch_title
                 'description',
                 'author@launchpad.net',
                 'product'))
        self.assertTrue(transport.got_request)

    def test_onto_transport_unauthenticated(self):
        """Test how an unauthenticated request is transmitted across a mock Transport"""
        transport = InstrumentedXMLRPCTransport(self, expect_auth=False)
        service = LaunchpadService(transport)
        resolve = ResolveLaunchpadPathRequest('bzr')
        resolve.submit(service)
        self.assertEquals(transport.connected_host, 'xmlrpc.edge.launchpad.net')
        self.assertEquals(len(transport.sent_params), 1)
        self.assertEquals(transport.sent_params, ('bzr', ))
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
        self.assertEquals(service.called_method_name, 'dummy_request')
        self.assertEquals(service.called_method_params, (42,))

    def test_mock_server_registration(self):
        """Send registration to mock server"""
        test_case = self
        class MockRegistrationService(MockLaunchpadService):
            def send_request(self, method_name, method_params, authenticated):
                test_case.assertEquals(method_name, "register_branch")
                test_case.assertEquals(list(method_params),
                        ['url', 'name', 'title', 'description', 'email', 'name'])
                test_case.assertEquals(authenticated, True)
                return 'result'
        service = MockRegistrationService()
        rego = BranchRegistrationRequest('url', 'name', 'title',
                        'description', 'email', 'name')
        result = rego.submit(service)
        self.assertEquals(result, 'result')

    def test_mock_server_registration_with_defaults(self):
        """Send registration to mock server"""
        test_case = self
        class MockRegistrationService(MockLaunchpadService):
            def send_request(self, method_name, method_params, authenticated):
                test_case.assertEquals(method_name, "register_branch")
                test_case.assertEquals(list(method_params),
                        ['http://server/branch', 'branch', '', '', '', ''])
                test_case.assertEquals(authenticated, True)
                return 'result'
        service = MockRegistrationService()
        rego = BranchRegistrationRequest('http://server/branch')
        result = rego.submit(service)
        self.assertEquals(result, 'result')

    def test_mock_bug_branch_link(self):
        """Send bug-branch link to mock server"""
        test_case = self
        class MockService(MockLaunchpadService):
            def send_request(self, method_name, method_params, authenticated):
                test_case.assertEquals(method_name, "link_branch_to_bug")
                test_case.assertEquals(list(method_params),
                        ['http://server/branch', 1234, ''])
                test_case.assertEquals(authenticated, True)
                return 'http://launchpad.net/bug/1234'
        service = MockService()
        rego = BranchBugLinkRequest('http://server/branch', 1234)
        result = rego.submit(service)
        self.assertEquals(result, 'http://launchpad.net/bug/1234')

    def test_mock_resolve_lp_url(self):
        test_case = self
        class MockService(MockLaunchpadService):
            def send_request(self, method_name, method_params, authenticated):
                test_case.assertEquals(method_name, "resolve_lp_path")
                test_case.assertEquals(list(method_params), ['bzr'])
                test_case.assertEquals(authenticated, False)
                return dict(urls=[
                        'bzr+ssh://bazaar.launchpad.net~bzr/bzr/trunk',
                        'sftp://bazaar.launchpad.net~bzr/bzr/trunk',
                        'bzr+http://bazaar.launchpad.net~bzr/bzr/trunk',
                        'http://bazaar.launchpad.net~bzr/bzr/trunk'])
        service = MockService()
        resolve = ResolveLaunchpadPathRequest('bzr')
        result = resolve.submit(service)
        self.assertTrue('urls' in result)
        self.assertEquals(result['urls'], [
                'bzr+ssh://bazaar.launchpad.net~bzr/bzr/trunk',
                'sftp://bazaar.launchpad.net~bzr/bzr/trunk',
                'bzr+http://bazaar.launchpad.net~bzr/bzr/trunk',
                'http://bazaar.launchpad.net~bzr/bzr/trunk'])


class TestGatherUserCredentials(tests.TestCaseInTempDir):

    def setUp(self):
        super(TestGatherUserCredentials, self).setUp()
        # make sure we have a reproducible standard environment
        self._captureVar('BZR_LP_XMLRPC_URL', None)

    def test_gather_user_credentials_has_password(self):
        service = LaunchpadService()
        service.registrant_password = 'mypassword'
        # This should be a basic no-op, since we already have the password
        service.gather_user_credentials()
        self.assertEqual('mypassword', service.registrant_password)

    def test_gather_user_credentials_from_auth_conf(self):
        auth_path = config.authentication_config_filename()
        service = LaunchpadService()
        g_conf = config.GlobalConfig()
        g_conf.set_user_option('email', 'Test User <test@user.com>')
        f = open(auth_path, 'wb')
        try:
            scheme, hostinfo = urlparse.urlsplit(service.service_url)[:2]
            f.write('[section]\n'
                    'scheme=%s\n'
                    'host=%s\n'
                    'user=test@user.com\n'
                    'password=testpass\n'
                    % (scheme, hostinfo))
        finally:
            f.close()
        self.assertIs(None, service.registrant_password)
        service.gather_user_credentials()
        self.assertEqual('test@user.com', service.registrant_email)
        self.assertEqual('testpass', service.registrant_password)

    def test_gather_user_credentials_prompts(self):
        service = LaunchpadService()
        self.assertIs(None, service.registrant_password)
        g_conf = config.GlobalConfig()
        g_conf.set_user_option('email', 'Test User <test@user.com>')
        stdout = tests.StringIOWrapper()
        ui.ui_factory = tests.TestUIFactory(stdin='userpass\n',
                                            stdout=stdout)
        self.assertIs(None, service.registrant_password)
        service.gather_user_credentials()
        self.assertEqual('test@user.com', service.registrant_email)
        self.assertEqual('userpass', service.registrant_password)
        self.assertContainsRe(stdout.getvalue(),
                             'launchpad.net password for test@user\\.com')

