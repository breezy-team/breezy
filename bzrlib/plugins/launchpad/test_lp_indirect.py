# Copyright (C) 2007 Canonical Ltd
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

"""Tests for indirect branch urls through Launchpad.net"""

import xmlrpclib

from bzrlib import (
    errors,
    )
from bzrlib.tests import TestCase
from bzrlib.plugins.launchpad.lp_indirect import (
    LaunchpadTransport)


class FakeResolveFactory(object):
    def __init__(self, test, expected_path, result):
        self._test = test
        self._expected_path = expected_path
        self._result = result

    def __call__(self, path):
        self._test.assertEqual(self._expected_path, path)
        return self

    def submit(self, service):
        return self._result


class IndirectUrlTests(TestCase):
    """Tests for indirect branch urls through Launchpad.net"""

    def test_short_form(self):
        """A launchpad url should map to a http url"""
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                    'http://bazaar.launchpad.net/~apt/apt/devel']))
        transport = LaunchpadTransport('lp:apt')
        self.assertEquals('http://bazaar.launchpad.net/~apt/apt/devel',
                          transport._resolve_base(factory))

    def test_indirect_through_url(self):
        """A launchpad url should map to a http url"""
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                    'http://bazaar.launchpad.net/~apt/apt/devel']))
        transport = LaunchpadTransport('lp:///apt')
        self.assertEquals('http://bazaar.launchpad.net/~apt/apt/devel',
                          transport._resolve_base(factory))

    def test_indirect_no_matching_schemes(self):
        # If the XMLRPC call does not return any protocols we support,
        # invalidURL is raised.
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                    'bad-scheme://bazaar.launchpad.net/~apt/apt/devel']))
        transport = LaunchpadTransport('lp:///apt')
        self.assertRaises(errors.InvalidURL, transport._resolve_base, factory)

    def test_indirect_fault(self):
        # Test that XMLRPC faults get converted to InvalidURL errors.
        factory = FakeResolveFactory(self, 'apt', None)
        def submit(service):
            raise xmlrpclib.Fault(42, 'something went wrong')
        factory.submit = submit
        transport = LaunchpadTransport('lp:///apt')
        self.assertRaises(errors.InvalidURL, transport._resolve_base, factory)

    # TODO: check we get an error if the url is unreasonable
    def test_error_for_bad_indirection(self):
        self.assertRaises(errors.InvalidURL,
            LaunchpadTransport, 'lp://ratotehunoahu')
