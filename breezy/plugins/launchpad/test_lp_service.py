# Copyright (C) 2008-2011 Canonical Ltd
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

"""Tests for selection of the right Launchpad service by environment"""

import os
from xmlrpc.client import Fault

from .lp_registration import (
    InvalidURL,
    InvalidLaunchpadInstance,
    LaunchpadService,
    NotLaunchpadBranch,
    )
from .test_lp_directory import FakeResolveFactory
from ...tests import TestCase


class LaunchpadServiceTests(TestCase):
    """Test that the correct Launchpad instance is chosen."""

    def setUp(self):
        super(LaunchpadServiceTests, self).setUp()
        # make sure we have a reproducible standard environment
        self.overrideEnv('BRZ_LP_XMLRPC_URL', None)

    def test_default_service(self):
        service = LaunchpadService()
        self.assertEqual('https://xmlrpc.launchpad.net/bazaar/',
                         service.service_url)

    def test_alter_default_service_url(self):
        LaunchpadService.DEFAULT_SERVICE_URL = 'http://example.com/'
        try:
            service = LaunchpadService()
            self.assertEqual('http://example.com/',
                             service.service_url)
        finally:
            LaunchpadService.DEFAULT_SERVICE_URL = \
                LaunchpadService.LAUNCHPAD_INSTANCE['production']

    def test_staging_service(self):
        service = LaunchpadService(lp_instance='staging')
        self.assertEqual('https://xmlrpc.staging.launchpad.net/bazaar/',
                         service.service_url)

    def test_test_service(self):
        service = LaunchpadService(lp_instance='test')
        self.assertEqual('https://xmlrpc.launchpad.test/bazaar/',
                         service.service_url)

    def test_demo_service(self):
        service = LaunchpadService(lp_instance='demo')
        self.assertEqual('https://xmlrpc.demo.launchpad.net/bazaar/',
                         service.service_url)

    def test_unknown_service(self):
        error = self.assertRaises(InvalidLaunchpadInstance,
                                  LaunchpadService,
                                  lp_instance='fubar')
        self.assertEqual('fubar is not a valid Launchpad instance.',
                         str(error))

    def test_environment_overrides_default(self):
        os.environ['BRZ_LP_XMLRPC_URL'] = 'http://example.com/'
        service = LaunchpadService()
        self.assertEqual('http://example.com/',
                         service.service_url)

    def test_environment_overrides_specified_service(self):
        os.environ['BRZ_LP_XMLRPC_URL'] = 'http://example.com/'
        service = LaunchpadService(lp_instance='staging')
        self.assertEqual('http://example.com/',
                         service.service_url)


class TestURLInference(TestCase):
    """Test the way we infer Launchpad web pages from branch URLs."""

    def test_default_bzr_ssh_url(self):
        service = LaunchpadService()
        web_url = service.get_web_url_from_branch_url(
            'bzr+ssh://bazaar.launchpad.net/~foo/bar/baz')
        self.assertEqual(
            'https://code.launchpad.net/~foo/bar/baz', web_url)

    def test_product_bzr_ssh_url(self):
        service = LaunchpadService(lp_instance='production')
        web_url = service.get_web_url_from_branch_url(
            'bzr+ssh://bazaar.launchpad.net/~foo/bar/baz')
        self.assertEqual(
            'https://code.launchpad.net/~foo/bar/baz', web_url)

    def test_sftp_branch_url(self):
        service = LaunchpadService(lp_instance='production')
        web_url = service.get_web_url_from_branch_url(
            'sftp://bazaar.launchpad.net/~foo/bar/baz')
        self.assertEqual(
            'https://code.launchpad.net/~foo/bar/baz', web_url)

    def test_staging_branch_url(self):
        service = LaunchpadService(lp_instance='production')
        web_url = service.get_web_url_from_branch_url(
            'bzr+ssh://bazaar.staging.launchpad.net/~foo/bar/baz')
        self.assertEqual(
            'https://code.launchpad.net/~foo/bar/baz', web_url)

    def test_non_launchpad_url(self):
        service = LaunchpadService()
        error = self.assertRaises(
            NotLaunchpadBranch, service.get_web_url_from_branch_url,
            'bzr+ssh://example.com/~foo/bar/baz')
        self.assertEqual(
            'bzr+ssh://example.com/~foo/bar/baz is not registered on Launchpad.',
            str(error))

    def test_dodgy_launchpad_url(self):
        service = LaunchpadService()
        self.assertRaises(
            NotLaunchpadBranch, service.get_web_url_from_branch_url,
            'bzr+ssh://launchpad.net/~foo/bar/baz')

    def test_lp_branch_url(self):
        service = LaunchpadService(lp_instance='production')
        factory = FakeResolveFactory(
            self, '~foo/bar/baz',
            dict(urls=['http://bazaar.launchpad.net/~foo/bar/baz']))
        web_url = service.get_web_url_from_branch_url(
            'lp:~foo/bar/baz', factory)
        self.assertEqual(
            'https://code.launchpad.net/~foo/bar/baz', web_url)

    def test_lp_branch_shortcut(self):
        service = LaunchpadService()
        factory = FakeResolveFactory(
            self, 'foo',
            dict(urls=['http://bazaar.launchpad.net/~foo/bar/baz']))
        web_url = service.get_web_url_from_branch_url('lp:foo', factory)
        self.assertEqual(
            'https://code.launchpad.net/~foo/bar/baz', web_url)

    def test_lp_branch_fault(self):
        service = LaunchpadService()
        factory = FakeResolveFactory(self, 'foo', None)

        def submit(service):
            raise Fault(42, 'something went wrong')
        factory.submit = submit
        self.assertRaises(
            InvalidURL, service.get_web_url_from_branch_url, 'lp:foo',
            factory)

    def test_staging_url(self):
        service = LaunchpadService(lp_instance='staging')
        web_url = service.get_web_url_from_branch_url(
            'bzr+ssh://bazaar.launchpad.net/~foo/bar/baz')
        self.assertEqual(
            'https://code.staging.launchpad.net/~foo/bar/baz', web_url)

    def test_test_url(self):
        service = LaunchpadService(lp_instance='test')
        web_url = service.get_web_url_from_branch_url(
            'bzr+ssh://bazaar.launchpad.net/~foo/bar/baz')
        self.assertEqual(
            'https://code.launchpad.test/~foo/bar/baz', web_url)

    def test_demo_url(self):
        service = LaunchpadService(lp_instance='demo')
        web_url = service.get_web_url_from_branch_url(
            'bzr+ssh://bazaar.launchpad.net/~foo/bar/baz')
        self.assertEqual(
            'https://code.demo.launchpad.net/~foo/bar/baz', web_url)
