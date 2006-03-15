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

import xmlrpclib

from bzrlib.tests import TestCase

# local import
from lp_registration import BranchRegistrationRequest

class TestBranchRegistration(TestCase):
    SAMPLE_URL = 'http://bazaar-vcs.org/bzr/bzr.dev/'

    def test_register_help(self):
        out, err = self.run_bzr('register-branch', '--help')
        self.assertContainsRe(out, r'Register a branch')

    def test_register_no_url(self):
        self.run_bzr('register-branch', retcode=3)

    def test_register_cmd_simple_branch(self):
        """Register a well-known branch to fake server"""
        self.run_bzr('register-branch', self.SAMPLE_URL)

    def test_make_branch_registration(self):
        from lp_registration import BranchRegistrationRequest
        rego = BranchRegistrationRequest(self.SAMPLE_URL)

    def test_request_xml(self):
        rego = BranchRegistrationRequest(self.SAMPLE_URL)
        req_xml = rego._request_xml()
        # other representations are possible; this is a bit hardcoded to
        # python's xmlrpclib
        self.assertEqualDiff(req_xml,
r'''<?xml version='1.0'?>
<methodCall>
<methodName>register_branch</methodName>
<params>
<param>
<value><string>%s</string></value>
</param>
</params>
</methodCall>
''' % self.SAMPLE_URL)

    def test_request_roundtrip(self):
        """Check the request can be parsed and meets the interface spec"""
        rego = BranchRegistrationRequest(self.SAMPLE_URL)
        req_xml = rego._request_xml()
        unpacked, method = xmlrpclib.loads(req_xml)
        self.assertEquals(unpacked, (self.SAMPLE_URL, ))
        self.assertEquals(method, 'register_branch')
