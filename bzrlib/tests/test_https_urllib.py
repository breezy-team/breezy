# Copyright (C) 2011 Canonical Ltd
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

"""Tests for the SSL support in the urllib HTTP transport.

"""

import os
import ssl

from bzrlib import (
    config,
    trace,
    )
from bzrlib.errors import (
    CertificateError,
    ConfigOptionValueError,
    )
from bzrlib.tests import (
    TestCase,
    TestCaseInTempDir,
    )
from bzrlib.transport.http import _urllib2_wrappers


class CaCertsConfigTests(TestCaseInTempDir):

    def get_stack(self, content):
        return config.MemoryStack(content.encode('utf-8'))

    def test_default_raises_value_error(self):
        stack = self.get_stack("")
        self.overrideAttr(_urllib2_wrappers, "DEFAULT_CA_PATH",
                "/i-do-not-exist")
        self.assertRaises(ValueError, stack.get, 'ssl.ca_certs')

    def test_default_exists(self):
        self.build_tree(['cacerts.pem'])
        stack = self.get_stack("")
        path = os.path.join(self.test_dir, "cacerts.pem")
        self.overrideAttr(_urllib2_wrappers, "DEFAULT_CA_PATH", path)
        self.assertEquals(path, stack.get('ssl.ca_certs'))

    def test_specified(self):
        self.build_tree(['cacerts.pem'])
        path = os.path.join(self.test_dir, "cacerts.pem")
        stack = self.get_stack("ssl.ca_certs = %s\n" % path)
        self.assertEquals(path, stack.get('ssl.ca_certs'))

    def test_specified_doesnt_exist(self):
        path = os.path.join(self.test_dir, "nonexisting.pem")
        stack = self.get_stack("ssl.ca_certs = %s\n" % path)
        self.warnings = []
        def warning(*args):
            self.warnings.append(args[0] % args[1:])
        self.overrideAttr(trace, 'warning', warning)
        self.assertEquals(_urllib2_wrappers.DEFAULT_CA_PATH,
                          stack.get('ssl.ca_certs'))
        self.assertLength(1, self.warnings)
        self.assertContainsRe(self.warnings[0],
                              "is not valid for \"ssl.ca_certs\"")


class CertReqsConfigTests(TestCaseInTempDir):

    def test_default(self):
        stack = config.MemoryStack("")
        self.assertEquals(ssl.CERT_REQUIRED, stack.get("ssl.cert_reqs"))

    def test_from_string(self):
        stack = config.MemoryStack("ssl.cert_reqs = none\n")
        self.assertEquals(ssl.CERT_NONE, stack.get("ssl.cert_reqs"))
        stack = config.MemoryStack("ssl.cert_reqs = optional\n")
        self.assertEquals(ssl.CERT_OPTIONAL, stack.get("ssl.cert_reqs"))
        stack = config.MemoryStack("ssl.cert_reqs = required\n")
        self.assertEquals(ssl.CERT_REQUIRED, stack.get("ssl.cert_reqs"))
        stack = config.MemoryStack("ssl.cert_reqs = invalid\n")
        self.assertRaises(ConfigOptionValueError, stack.get, "ssl.cert_reqs")


class MatchHostnameTests(TestCase):

    def test_no_certificate(self):
        self.assertRaises(ValueError,
                          _urllib2_wrappers.match_hostname, {}, "example.com")

    def test_no_valid_attributes(self):
        self.assertRaises(CertificateError, _urllib2_wrappers.match_hostname,
                          {"Problem": "Solved"}, "example.com")

    def test_common_name(self):
        cert = {'subject': ((('commonName', 'example.com'),),)}
        self.assertIs(None,
                      _urllib2_wrappers.match_hostname(cert, "example.com"))
        self.assertRaises(CertificateError, _urllib2_wrappers.match_hostname,
                          cert, "example.org")
