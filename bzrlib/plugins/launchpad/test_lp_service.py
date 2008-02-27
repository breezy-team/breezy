# Copyright (C) 2008 Canonical Ltd
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

"""Tests for selection of the right Launchpad service by environment"""

import os

from bzrlib.tests import TestCase
from bzrlib.plugins.launchpad.lp_registration import (
    InvalidLaunchpadInstance, LaunchpadService)


class LaunchpadServiceTests(TestCase):
    """Test that the correct Launchpad instance is chosen."""

    def setUp(self):
        super(LaunchpadServiceTests, self).setUp()
        # make sure we have a reproducible standard environment
        self._captureVar('BZR_LP_XMLRPC_URL', None)

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

    def test_edge_service(self):
        service = LaunchpadService(lp_instance='edge')
        self.assertEqual('https://xmlrpc.edge.launchpad.net/bazaar/',
                         service.service_url)

    def test_dev_service(self):
        service = LaunchpadService(lp_instance='dev')
        self.assertEqual('http://xmlrpc.launchpad.dev/bazaar/',
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
        os.environ['BZR_LP_XMLRPC_URL'] = 'http://example.com/'
        service = LaunchpadService()
        self.assertEqual('http://example.com/',
                         service.service_url)

    def test_environment_overrides_specified_service(self):
        os.environ['BZR_LP_XMLRPC_URL'] = 'http://example.com/'
        service = LaunchpadService(lp_instance='staging')
        self.assertEqual('http://example.com/',
                         service.service_url)
