# Copyright (C) 2007, 2008 Canonical Ltd
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

"""Tests for directory lookup through Launchpad.net"""

import xmlrpclib

from bzrlib import (
    errors,
    )
from bzrlib.branch import Branch
from bzrlib.directory_service import directories
from bzrlib.tests import TestCase, TestCaseWithMemoryTransport
from bzrlib.transport import get_transport
from bzrlib.plugins.launchpad import _register_directory
from bzrlib.plugins.launchpad.lp_directory import (
    LaunchpadDirectory)
from bzrlib.plugins.launchpad.account import get_lp_login


class FakeResolveFactory(object):
    def __init__(self, test, expected_path, result):
        self._test = test
        self._expected_path = expected_path
        self._result = result

    def __call__(self, path):
        self._test.assertEqual(self._expected_path, path)
        return self

    def submit(self, service):
        self._service_url = service.service_url
        return self._result


class DirectoryUrlTests(TestCase):
    """Tests for branch urls through Launchpad.net directory"""

    def test_short_form(self):
        """A launchpad url should map to a http url"""
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                    'http://bazaar.launchpad.net/~apt/apt/devel']))
        directory = LaunchpadDirectory()
        self.assertEquals('http://bazaar.launchpad.net/~apt/apt/devel',
                          directory._resolve('lp:apt', factory))
        # Make sure that resolve went to the production server.
        self.assertEquals('https://xmlrpc.edge.launchpad.net/bazaar/',
                          factory._service_url)

    def test_staging(self):
        """A launchpad url should map to a http url"""
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                    'http://bazaar.staging.launchpad.net/~apt/apt/devel']))
        url = 'lp://staging/apt'
        directory = LaunchpadDirectory()
        self.assertEquals('http://bazaar.staging.launchpad.net/~apt/apt/devel',
                          directory._resolve(url, factory))
        # Make sure that resolve went to the staging server.
        self.assertEquals('https://xmlrpc.staging.launchpad.net/bazaar/',
                          factory._service_url)

    def test_url_from_directory(self):
        """A launchpad url should map to a http url"""
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                    'http://bazaar.launchpad.net/~apt/apt/devel']))
        directory = LaunchpadDirectory()
        self.assertEquals('http://bazaar.launchpad.net/~apt/apt/devel',
                          directory._resolve('lp:///apt', factory))

    def test_directory_skip_bad_schemes(self):
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                    'bad-scheme://bazaar.launchpad.net/~apt/apt/devel',
                    'http://bazaar.launchpad.net/~apt/apt/devel',
                    'http://another/location']))
        directory = LaunchpadDirectory()
        self.assertEquals('http://bazaar.launchpad.net/~apt/apt/devel',
                          directory._resolve('lp:///apt', factory))

    def test_directory_no_matching_schemes(self):
        # If the XMLRPC call does not return any protocols we support,
        # invalidURL is raised.
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                    'bad-scheme://bazaar.launchpad.net/~apt/apt/devel']))
        directory = LaunchpadDirectory()
        self.assertRaises(errors.InvalidURL,
                          directory._resolve, 'lp:///apt', factory)

    def test_directory_fault(self):
        # Test that XMLRPC faults get converted to InvalidURL errors.
        factory = FakeResolveFactory(self, 'apt', None)
        def submit(service):
            raise xmlrpclib.Fault(42, 'something went wrong')
        factory.submit = submit
        directory = LaunchpadDirectory()
        self.assertRaises(errors.InvalidURL,
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
        self.assertEquals('http://bazaar.launchpad.net/~apt/apt/devel',
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
        self.assertEquals('http://bazaar.launchpad.net/~apt/apt/devel',
                          directory._resolve('lp:///apt', factory))

    def test_rewrite_bzr_ssh_launchpad_net(self):
        # Test that bzr+ssh URLs get rewritten to include the user's
        # Launchpad ID (assuming we know the Launchpad ID).
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                    'bzr+ssh://bazaar.launchpad.net/~apt/apt/devel',
                    'http://bazaar.launchpad.net/~apt/apt/devel']))
        directory = LaunchpadDirectory()
        self.assertEquals(
            'bzr+ssh://username@bazaar.launchpad.net/~apt/apt/devel',
            directory._resolve('lp:///apt', factory, _lp_login='username'))

    def test_no_rewrite_of_other_bzr_ssh(self):
        # Test that we don't rewrite bzr+ssh URLs for other 
        self.assertEqual(None, get_lp_login())
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                    'bzr+ssh://example.com/~apt/apt/devel',
                    'http://bazaar.launchpad.net/~apt/apt/devel']))
        directory = LaunchpadDirectory()
        self.assertEquals('bzr+ssh://example.com/~apt/apt/devel',
                          directory._resolve('lp:///apt', factory))

    # TODO: check we get an error if the url is unreasonable
    def test_error_for_bad_url(self):
        directory = LaunchpadDirectory()
        self.assertRaises(errors.InvalidURL,
            directory._resolve, 'lp://ratotehunoahu')


class DirectoryOpenBranchTests(TestCaseWithMemoryTransport):

    def test_directory_open_branch(self):
        # Test that opening an lp: branch redirects to the real location.
        target_branch = self.make_branch('target')
        class FooService(object):
            """A directory service that maps the name to a FILE url"""

            def look_up(self, name, url):
                if 'lp:///apt' == url:
                    return target_branch.base.rstrip('/')
                return '!unexpected look_up value!'

        directories.remove('lp:')
        directories.register('lp:', FooService, 'Map lp URLs to local urls')
        self.addCleanup(_register_directory)
        self.addCleanup(lambda: directories.remove('lp:'))
        transport = get_transport('lp:///apt')
        branch = Branch.open_from_transport(transport)
        self.assertEqual(target_branch.base, branch.base)
