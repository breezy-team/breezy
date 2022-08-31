# Copyright (C) 2007-2012, 2016 Canonical Ltd
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

"""Tests for directory lookup through Launchpad.net"""

import os

from xmlrpc.client import Fault
from http.client import parse_headers

import breezy
from ... import (
    debug,
    tests,
    transport,
    )
from ...branch import Branch
from ...directory_service import directories
from ...tests import (
    features,
    ssl_certs,
    TestCaseInTempDir,
    TestCaseWithMemoryTransport
)
from . import (
    _register_directory,
    lp_registration,
    )
from .lp_directory import (
    LaunchpadDirectory)
from .account import get_lp_login, set_lp_login
from ...tests import http_server


def load_tests(loader, standard_tests, pattern):
    result = loader.suiteClass()
    t_tests, remaining_tests = tests.split_suite_by_condition(
        standard_tests, tests.condition_isinstance((
            TestXMLRPCTransport,
            )))
    transport_scenarios = [
        ('http', dict(server_class=PreCannedHTTPServer,)),
        ]
    if features.HTTPSServerFeature.available():
        transport_scenarios.append(
            ('https', dict(server_class=PreCannedHTTPSServer,)),
            )
    tests.multiply_tests(t_tests, transport_scenarios, result)

    # No parametrization for the remaining tests
    result.addTests(remaining_tests)

    return result


class FakeResolveFactory(object):

    def __init__(self, test, expected_path, result):
        self._test = test
        self._expected_path = expected_path
        self._result = result
        self._submitted = False

    def __call__(self, path):
        self._test.assertEqual(self._expected_path, path)
        return self

    def submit(self, service):
        self._service_url = service.service_url
        self._submitted = True
        return self._result


class LocalDirectoryURLTests(TestCaseInTempDir):
    """Tests for branch urls that we try to pass through local resolution."""

    def assertResolve(self, expected, url, submitted=False):
        path = url[url.index(':') + 1:].lstrip('/')
        factory = FakeResolveFactory(self, path,
                                     dict(urls=['bzr+ssh://fake-resolved']))
        directory = LaunchpadDirectory()
        self.assertEqual(expected,
                         directory._resolve(url, factory, _lp_login='user'))
        # We are testing local resolution, and the fallback when necessary.
        self.assertEqual(submitted, factory._submitted)

    def test_short_form(self):
        self.assertResolve('bzr+ssh://bazaar.launchpad.net/+branch/apt',
                           'lp:apt')

    def test_short_form_bzr(self):
        self.assertResolve('bzr+ssh://bazaar.launchpad.net/+branch/apt',
                           'lp+bzr:apt')

    def test_two_part_form(self):
        self.assertResolve('bzr+ssh://bazaar.launchpad.net/+branch/apt/2.2',
                           'lp:apt/2.2')

    def test_two_part_plus_subdir(self):
        # We allow you to pass more than just what resolves. That way you can
        # do things like "brz log lp:apt/2.2/BUGS"
        # Though the virtual FS implementation currently aborts when given a
        # URL like this, rather than letting you recurse upwards to find the
        # real branch at lp:apt/2.2
        self.assertResolve('bzr+ssh://bazaar.launchpad.net/+branch/apt/2.2/BUGS',
                           'lp:apt/2.2/BUGS')

    def test_user_expansion(self):
        self.assertResolve('bzr+ssh://bazaar.launchpad.net/~user/apt/foo',
                           'lp:~/apt/foo')

    def test_ubuntu(self):
        # Confirmed against xmlrpc. If you don't have a ~user, xmlrpc doesn't
        # care that you are asking for 'ubuntu'
        self.assertResolve('bzr+ssh://bazaar.launchpad.net/+branch/ubuntu',
                           'lp:ubuntu')

    def test_ubuntu_invalid(self):
        """Invalid ubuntu urls don't crash.

        :seealso: http://pad.lv/843900
        """
        # This ought to be natty-updates.
        self.assertRaises(lp_registration.InvalidURL,
                          self.assertResolve,
                          '',
                          'ubuntu:natty/updates/smartpm')

    def test_ubuntu_apt(self):
        self.assertResolve('bzr+ssh://bazaar.launchpad.net/+branch/ubuntu/apt',
                           'lp:ubuntu/apt')

    def test_ubuntu_natty_apt(self):
        self.assertResolve(
            'bzr+ssh://bazaar.launchpad.net/+branch/ubuntu/natty/apt',
            'lp:ubuntu/natty/apt')

    def test_ubuntu_natty_apt_filename(self):
        self.assertResolve(
            'bzr+ssh://bazaar.launchpad.net/+branch/ubuntu/natty/apt/filename',
            'lp:ubuntu/natty/apt/filename')

    def test_user_two_part(self):
        # We fall back to the ResolveFactory. The real Launchpad one will raise
        # InvalidURL for this case.
        self.assertResolve('bzr+ssh://fake-resolved', 'lp:~jameinel/apt',
                           submitted=True)

    def test_user_three_part(self):
        self.assertResolve('bzr+ssh://bazaar.launchpad.net/~jameinel/apt/foo',
                           'lp:~jameinel/apt/foo')

    def test_user_three_part_plus_filename(self):
        self.assertResolve(
            'bzr+ssh://bazaar.launchpad.net/~jameinel/apt/foo/fname',
            'lp:~jameinel/apt/foo/fname')

    def test_user_ubuntu_two_part(self):
        self.assertResolve('bzr+ssh://fake-resolved', 'lp:~jameinel/ubuntu',
                           submitted=True)
        self.assertResolve('bzr+ssh://fake-resolved', 'lp:~jameinel/debian',
                           submitted=True)

    def test_user_ubuntu_three_part(self):
        self.assertResolve('bzr+ssh://fake-resolved',
                           'lp:~jameinel/ubuntu/natty', submitted=True)
        self.assertResolve('bzr+ssh://fake-resolved',
                           'lp:~jameinel/debian/sid', submitted=True)

    def test_user_ubuntu_four_part(self):
        self.assertResolve('bzr+ssh://fake-resolved',
                           'lp:~jameinel/ubuntu/natty/project', submitted=True)
        self.assertResolve('bzr+ssh://fake-resolved',
                           'lp:~jameinel/debian/sid/project', submitted=True)

    def test_user_ubuntu_five_part(self):
        self.assertResolve(
            'bzr+ssh://bazaar.launchpad.net/~jameinel/ubuntu/natty/apt/branch',
            'lp:~jameinel/ubuntu/natty/apt/branch')
        self.assertResolve(
            'bzr+ssh://bazaar.launchpad.net/~jameinel/debian/sid/apt/branch',
            'lp:~jameinel/debian/sid/apt/branch')

    def test_user_ubuntu_five_part_plus_subdir(self):
        self.assertResolve(
            'bzr+ssh://bazaar.launchpad.net/~jameinel/ubuntu/natty/apt/branch/f',
            'lp:~jameinel/ubuntu/natty/apt/branch/f')
        self.assertResolve(
            'bzr+ssh://bazaar.launchpad.net/~jameinel/debian/sid/apt/branch/f',
            'lp:~jameinel/debian/sid/apt/branch/f')

    def test_handles_special_lp(self):
        self.assertResolve(
            'bzr+ssh://bazaar.launchpad.net/+branch/apt', 'lp:apt')
        self.assertResolve('bzr+ssh://bazaar.launchpad.net/+branch/apt',
                           'lp:///apt')
        self.assertResolve('bzr+ssh://bazaar.launchpad.net/+branch/apt',
                           'lp://production/apt')
        self.assertResolve('bzr+ssh://bazaar.launchpad.test/+branch/apt',
                           'lp://test/apt')
        self.assertResolve('bzr+ssh://bazaar.staging.launchpad.net/+branch/apt',
                           'lp://staging/apt')
        self.assertResolve('bzr+ssh://bazaar.qastaging.launchpad.net/+branch/apt',
                           'lp://qastaging/apt')
        self.assertResolve('bzr+ssh://bazaar.demo.launchpad.net/+branch/apt',
                           'lp://demo/apt')

    def test_debug_launchpad_uses_resolver(self):
        self.assertResolve('bzr+ssh://bazaar.launchpad.net/+branch/bzr',
                           'lp:bzr', submitted=False)
        debug.debug_flags.add('launchpad')
        self.addCleanup(debug.debug_flags.discard, 'launchpad')
        self.assertResolve('bzr+ssh://fake-resolved', 'lp:bzr', submitted=True)


class DirectoryUrlTests(TestCaseInTempDir):
    """Tests for branch urls through Launchpad.net directory"""

    def test_short_form(self):
        """A launchpad url should map to a http url"""
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                'http://bazaar.launchpad.net/~apt/apt/devel']))
        directory = LaunchpadDirectory()
        self.assertEqual('http://bazaar.launchpad.net/~apt/apt/devel',
                         directory._resolve('lp:apt', factory))
        # Make sure that resolve went to the production server.
        self.assertEqual('https://xmlrpc.launchpad.net/bazaar/',
                         factory._service_url)

    def test_qastaging(self):
        """A launchpad url should map to a http url"""
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                'http://bazaar.qastaging.launchpad.net/~apt/apt/devel']))
        url = 'lp://qastaging/apt'
        directory = LaunchpadDirectory()
        self.assertEqual('http://bazaar.qastaging.launchpad.net/~apt/apt/devel',
                         directory._resolve(url, factory))
        # Make sure that resolve went to the qastaging server.
        self.assertEqual('https://xmlrpc.qastaging.launchpad.net/bazaar/',
                         factory._service_url)

    def test_staging(self):
        """A launchpad url should map to a http url"""
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                'http://bazaar.staging.launchpad.net/~apt/apt/devel']))
        url = 'lp://staging/apt'
        directory = LaunchpadDirectory()
        self.assertEqual('http://bazaar.staging.launchpad.net/~apt/apt/devel',
                         directory._resolve(url, factory))
        # Make sure that resolve went to the staging server.
        self.assertEqual('https://xmlrpc.staging.launchpad.net/bazaar/',
                         factory._service_url)

    def test_url_from_directory(self):
        """A launchpad url should map to a http url"""
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                'http://bazaar.launchpad.net/~apt/apt/devel']))
        directory = LaunchpadDirectory()
        self.assertEqual('http://bazaar.launchpad.net/~apt/apt/devel',
                         directory._resolve('lp:///apt', factory))

    def test_directory_skip_bad_schemes(self):
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                'bad-scheme://bazaar.launchpad.net/~apt/apt/devel',
                'http://bazaar.launchpad.net/~apt/apt/devel',
                'http://another/location']))
        directory = LaunchpadDirectory()
        self.assertEqual('http://bazaar.launchpad.net/~apt/apt/devel',
                         directory._resolve('lp:///apt', factory))

    def test_directory_no_matching_schemes(self):
        # If the XMLRPC call does not return any protocols we support,
        # invalidURL is raised.
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                'bad-scheme://bazaar.launchpad.net/~apt/apt/devel']))
        directory = LaunchpadDirectory()
        self.assertRaises(lp_registration.InvalidURL,
                          directory._resolve, 'lp:///apt', factory)

    def test_directory_fault(self):
        # Test that XMLRPC faults get converted to InvalidURL errors.
        factory = FakeResolveFactory(self, 'apt', None)

        def submit(service):
            raise Fault(42, 'something went wrong')
        factory.submit = submit
        directory = LaunchpadDirectory()
        self.assertRaises(lp_registration.InvalidURL,
                          directory._resolve, 'lp:///apt', factory)

    def test_skip_bzr_ssh_launchpad_net_when_anonymous(self):
        # Test that bzr+ssh://bazaar.launchpad.net gets skipped if
        # Bazaar does not know the user's Launchpad ID:
        self.assertEqual(None, get_lp_login())
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                'bzr+ssh://bazaar.launchpad.net/~apt/apt/devel',
                'http://bazaar.launchpad.net/~apt/apt/devel']))
        directory = LaunchpadDirectory()
        self.assertEqual('http://bazaar.launchpad.net/~apt/apt/devel',
                         directory._resolve('lp:///apt', factory))

    def test_skip_sftp_launchpad_net_when_anonymous(self):
        # Test that sftp://bazaar.launchpad.net gets skipped if
        # Bazaar does not know the user's Launchpad ID:
        self.assertEqual(None, get_lp_login())
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                'sftp://bazaar.launchpad.net/~apt/apt/devel',
                'http://bazaar.launchpad.net/~apt/apt/devel']))
        directory = LaunchpadDirectory()
        self.assertEqual('http://bazaar.launchpad.net/~apt/apt/devel',
                         directory._resolve('lp:///apt', factory))

    def test_with_login_avoid_resolve_factory(self):
        # Test that bzr+ssh URLs get rewritten to include the user's
        # Launchpad ID (assuming we know the Launchpad ID).
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                'bzr+ssh://my-super-custom/special/devel',
                'http://bazaar.launchpad.net/~apt/apt/devel']))
        directory = LaunchpadDirectory()
        self.assertEqual(
            'bzr+ssh://bazaar.launchpad.net/+branch/apt',
            directory._resolve('lp:///apt', factory, _lp_login='username'))

    def test_no_rewrite_of_other_bzr_ssh(self):
        # Test that we don't rewrite bzr+ssh URLs for other
        self.assertEqual(None, get_lp_login())
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                'bzr+ssh://example.com/~apt/apt/devel',
                'http://bazaar.launchpad.net/~apt/apt/devel']))
        directory = LaunchpadDirectory()
        self.assertEqual('bzr+ssh://example.com/~apt/apt/devel',
                         directory._resolve('lp:///apt', factory))

    # TODO: check we get an error if the url is unreasonable
    def test_error_for_bad_url(self):
        directory = LaunchpadDirectory()
        self.assertRaises(lp_registration.InvalidURL,
                          directory._resolve, 'lp://ratotehunoahu')

    def test_resolve_tilde_to_user(self):
        factory = FakeResolveFactory(
            self, '~username/apt/test', dict(urls=[
                'bzr+ssh://bazaar.launchpad.net/~username/apt/test']))
        directory = LaunchpadDirectory()
        self.assertEqual(
            'bzr+ssh://bazaar.launchpad.net/~username/apt/test',
            directory._resolve('lp:~/apt/test', factory, _lp_login='username'))
        # Should also happen when the login is just set by config
        set_lp_login('username')
        self.assertEqual(
            'bzr+ssh://bazaar.launchpad.net/~username/apt/test',
            directory._resolve('lp:~/apt/test', factory))

    def test_tilde_fails_no_login(self):
        factory = FakeResolveFactory(
            self, '~username/apt/test', dict(urls=[
                'bzr+ssh://bazaar.launchpad.net/~username/apt/test']))
        self.assertIs(None, get_lp_login())
        directory = LaunchpadDirectory()
        self.assertRaises(lp_registration.InvalidURL,
                          directory._resolve, 'lp:~/apt/test', factory)


class DirectoryOpenBranchTests(TestCaseWithMemoryTransport):

    def test_directory_open_branch(self):
        # Test that opening an lp: branch redirects to the real location.
        target_branch = self.make_branch('target')

        class FooService(object):
            """A directory service that maps the name to a FILE url"""

            def look_up(self, name, url, purpose=None):
                if 'lp:///apt' == url:
                    return target_branch.base.rstrip('/')
                return '!unexpected look_up value!'

        directories.remove('lp:')
        directories.remove('lp+bzr:')
        directories.remove('ubuntu:')
        directories.remove('debianlp:')
        directories.register('lp:', FooService, 'Map lp URLs to local urls')
        self.addCleanup(_register_directory)
        self.addCleanup(directories.remove, 'lp:')
        t = transport.get_transport('lp:///apt')
        branch = Branch.open_from_transport(t)
        self.assertEqual(target_branch.base, branch.base)


class PredefinedRequestHandler(http_server.TestingHTTPRequestHandler):
    """Request handler for a unique and pre-defined request.

    The only thing we care about here is that we receive a connection. But
    since we want to dialog with a real http client, we have to send it correct
    responses.

    We expect to receive a *single* request nothing more (and we won't even
    check what request it is), the tests will recognize us from our response.
    """

    def handle_one_request(self):
        tcs = self.server.test_case_server
        requestline = self.rfile.readline()
        parse_headers(self.rfile)
        if requestline.startswith(b'POST'):
            # The body should be a single line (or we don't know where it ends
            # and we don't want to issue a blocking read)
            self.rfile.readline()

        self.wfile.write(tcs.canned_response)


class PreCannedServerMixin(object):

    def __init__(self):
        super(PreCannedServerMixin, self).__init__(
            request_handler=PredefinedRequestHandler)
        # Bytes read and written by the server
        self.bytes_read = 0
        self.bytes_written = 0
        self.canned_response = None


class PreCannedHTTPServer(PreCannedServerMixin, http_server.HttpServer):
    pass


if features.HTTPSServerFeature.available():
    from ...tests import https_server

    class PreCannedHTTPSServer(PreCannedServerMixin, https_server.HTTPSServer):
        pass


class TestXMLRPCTransport(tests.TestCase):

    # set by load_tests
    server_class = None

    def setUp(self):
        super(TestXMLRPCTransport, self).setUp()
        self.server = self.server_class()
        self.server.start_server()
        self.addCleanup(self.server.stop_server)
        # Ensure we don't clobber env
        self.overrideEnv('BRZ_LP_XMLRPC_URL', None)
        # Ensure we use the right certificates for https.
        # FIXME: There should be a better way but the only alternative I can
        # think of involves carrying the ca_certs through the lp_registration
        # infrastructure to _urllib2_wrappers... -- vila 2012-01-20
        breezy.get_global_state().cmdline_overrides._from_cmdline(
            ['ssl.ca_certs=%s' % ssl_certs.build_path('ca.crt')])

    def set_canned_response(self, server, path):
        response_format = b'''HTTP/1.1 200 OK\r
Date: Tue, 11 Jul 2006 04:32:56 GMT\r
Server: Apache/2.0.54 (Fedora)\r
Last-Modified: Sun, 23 Apr 2006 19:35:20 GMT\r
ETag: "56691-23-38e9ae00"\r
Accept-Ranges: bytes\r
Content-Length: %(length)d\r
Connection: close\r
Content-Type: text/plain; charset=UTF-8\r
\r
<?xml version='1.0'?>
<methodResponse>
<params>
<param>
<value><struct>
<member>
<name>urls</name>
<value><array><data>
<value><string>bzr+ssh://bazaar.launchpad.net/%(path)s</string></value>
<value><string>http://bazaar.launchpad.net/%(path)s</string></value>
</data></array></value>
</member>
</struct></value>
</param>
</params>
</methodResponse>
'''
        length = 334 + 2 * len(path)
        server.canned_response = response_format % {
            b'length': length, b'path': path}

    def do_request(self, server_url):
        os.environ['BRZ_LP_XMLRPC_URL'] = self.server.get_url()
        service = lp_registration.LaunchpadService()
        resolve = lp_registration.ResolveLaunchpadPathRequest('bzr')
        result = resolve.submit(service)
        return result

    def test_direct_request(self):
        self.set_canned_response(self.server, b'~bzr-pqm/bzr/bzr.dev')
        result = self.do_request(self.server.get_url())
        urls = result.get('urls', None)
        self.assertIsNot(None, urls)
        self.assertEqual(
            ['bzr+ssh://bazaar.launchpad.net/~bzr-pqm/bzr/bzr.dev',
             'http://bazaar.launchpad.net/~bzr-pqm/bzr/bzr.dev'],
            urls)
    # FIXME: we need to test with a real proxy, I can't find a way so simulate
    # CONNECT without leaving one server hanging the test :-/ Since that maybe
    # related to the leaking tests problems, I'll punt for now -- vila 20091030


class TestDebuntuExpansions(TestCaseInTempDir):
    """Test expansions for ubuntu: and debianlp: schemes."""

    def setUp(self):
        super(TestDebuntuExpansions, self).setUp()
        self.directory = LaunchpadDirectory()

    def _make_factory(self, package='foo', distro='ubuntu', series=None):
        if series is None:
            path = '%s/%s' % (distro, package)
            url_suffix = '~branch/%s/%s' % (distro, package)
        else:
            path = '%s/%s/%s' % (distro, series, package)
            url_suffix = '~branch/%s/%s/%s' % (distro, series, package)
        return FakeResolveFactory(
            self, path, dict(urls=[
                'http://bazaar.launchpad.net/' + url_suffix]))

    def assertURL(self, expected_url, shortcut, package='foo', distro='ubuntu',
                  series=None):
        factory = self._make_factory(package=package, distro=distro,
                                     series=series)
        self.assertEqual('http://bazaar.launchpad.net/~branch/' + expected_url,
                         self.directory._resolve(shortcut, factory))

    # Bogus distro.

    def test_bogus_distro(self):
        factory = FakeResolveFactory(self, 'foo', dict(urls=[]))
        self.assertRaises(lp_registration.InvalidURL,
                          self.directory._resolve, 'gentoo:foo', factory)

    def test_trick_bogus_distro_u(self):
        factory = FakeResolveFactory(self, 'foo', dict(urls=[]))
        self.assertRaises(lp_registration.InvalidURL,
                          self.directory._resolve, 'utube:foo', factory)

    def test_trick_bogus_distro_d(self):
        factory = FakeResolveFactory(self, 'foo', dict(urls=[]))
        self.assertRaises(lp_registration.InvalidURL,
                          self.directory._resolve, 'debuntu:foo', factory)

    def test_missing_ubuntu_distroseries_without_project(self):
        # Launchpad does not hold source packages for Intrepid.  Missing or
        # bogus distroseries with no project name is treated like a project.
        self.assertURL('ubuntu/intrepid', 'ubuntu:intrepid',
                       package='intrepid')

    def test_missing_ubuntu_distroseries_with_project(self):
        # Launchpad does not hold source packages for Intrepid.  Missing or
        # bogus distroseries with a project name is treated like an unknown
        # series (i.e. we keep it verbatim).
        self.assertURL('ubuntu/intrepid/foo',
                       'ubuntu:intrepid/foo', series='intrepid')

    def test_missing_debian_distroseries(self):
        # Launchpad does not hold source packages for unstable.  Missing or
        # bogus distroseries is treated like a project.
        self.assertURL('debian/sid',
                       'debianlp:sid', package='sid', distro='debian')

    # Ubuntu Default distro series.

    def test_ubuntu_default_distroseries_expansion(self):
        self.assertURL('ubuntu/foo', 'ubuntu:foo')

    def test_ubuntu_natty_distroseries_expansion(self):
        self.assertURL('ubuntu/natty/foo', 'ubuntu:natty/foo', series='natty')

    def test_ubuntu_maverick_distroseries_expansion(self):
        self.assertURL('ubuntu/maverick/foo', 'ubuntu:maverick/foo',
                       series='maverick')

    def test_ubuntu_lucid_distroseries_expansion(self):
        self.assertURL('ubuntu/lucid/foo', 'ubuntu:lucid/foo', series='lucid')

    def test_ubuntu_karmic_distroseries_expansion(self):
        self.assertURL('ubuntu/karmic/foo', 'ubuntu:karmic/foo',
                       series='karmic')

    def test_ubuntu_jaunty_distroseries_expansion(self):
        self.assertURL('ubuntu/jaunty/foo', 'ubuntu:jaunty/foo',
                       series='jaunty')

    def test_ubuntu_hardy_distroseries_expansion(self):
        self.assertURL('ubuntu/hardy/foo', 'ubuntu:hardy/foo', series='hardy')

    def test_ubuntu_dapper_distroseries_expansion(self):
        self.assertURL('ubuntu/dapper/foo', 'ubuntu:dapper/foo',
                       series='dapper')

    # Debian default distro series.

    def test_debian_default_distroseries_expansion(self):
        self.assertURL('debian/foo', 'debianlp:foo', distro='debian')

    def test_debian_squeeze_distroseries_expansion(self):
        self.assertURL('debian/squeeze/foo', 'debianlp:squeeze/foo',
                       distro='debian', series='squeeze')

    def test_debian_lenny_distroseries_expansion(self):
        self.assertURL('debian/lenny/foo', 'debianlp:lenny/foo',
                       distro='debian', series='lenny')
