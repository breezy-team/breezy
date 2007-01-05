# Copyright (C) 2004, 2005, 2006, 2007 Canonical Ltd
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

from bzrlib.tests import TestCase
from bzrlib.errors import SSHVendorNotFound, UnknownSSH
from bzrlib.transport.ssh import (
    SSHVendorManager,
    OpenSSHSubprocessVendor,
    SSHCorpSubprocessVendor,
    PLinkSubprocessVendor,
    )


class TestSSHVendorManager(SSHVendorManager):

    _ssh_version_string = ""

    def set_ssh_version_string(self, version):
        self._ssh_version_string = version

    def _get_ssh_version_string(self, args):
        return self._ssh_version_string


class SSHVendorManagerTests(TestCase):

    def test_register_vendor(self):
        manager = TestSSHVendorManager()
        self.assertRaises(SSHVendorNotFound, manager.get_vendor, {})
        manager.register_vendor("vendor", "VENDOR")
        self.assertEqual(manager.get_vendor({"BZR_SSH": "vendor"}), "VENDOR")

    def test_default_vendor(self):
        manager = TestSSHVendorManager()
        self.assertRaises(SSHVendorNotFound, manager.get_vendor, {})
        manager.register_vendor("default", "VENDOR")
        self.assertEqual(manager.get_vendor({}), "VENDOR")

    def test_get_vendor_by_environment(self):
        manager = TestSSHVendorManager()
        self.assertRaises(SSHVendorNotFound, manager.get_vendor, {})
        self.assertRaises(UnknownSSH,
            manager.get_vendor, {"BZR_SSH": "vendor"})
        manager.register_vendor("vendor", "VENDOR")
        self.assertEqual(manager.get_vendor({"BZR_SSH": "vendor"}), "VENDOR")

    def test_get_vendor_by_inspection_openssh(self):
        manager = TestSSHVendorManager()
        self.assertRaises(SSHVendorNotFound, manager.get_vendor, {})
        manager.set_ssh_version_string("OpenSSH")
        self.assertIsInstance(manager.get_vendor({}), OpenSSHSubprocessVendor)

    def test_get_vendor_by_inspection_sshcorp(self):
        manager = TestSSHVendorManager()
        self.assertRaises(SSHVendorNotFound, manager.get_vendor, {})
        manager.set_ssh_version_string("SSH Secure Shell")
        self.assertIsInstance(manager.get_vendor({}), SSHCorpSubprocessVendor)

    def test_get_vendor_by_inspection_plink(self):
        manager = TestSSHVendorManager()
        self.assertRaises(SSHVendorNotFound, manager.get_vendor, {})
        manager.set_ssh_version_string("plink")
        self.assertIsInstance(manager.get_vendor({}), PLinkSubprocessVendor)

    def test_cached_vendor(self):
        manager = TestSSHVendorManager()
        self.assertRaises(SSHVendorNotFound, manager.get_vendor, {})
        manager.register_vendor("vendor", "VENDOR")
        self.assertRaises(SSHVendorNotFound, manager.get_vendor, {})
        self.assertEqual(manager.get_vendor({"BZR_SSH": "vendor"}), "VENDOR")
        self.assertEqual(manager.get_vendor({}), "VENDOR")

    def test_vendor_getting_methods_precedence(self):
        manager = TestSSHVendorManager()
        self.assertRaises(SSHVendorNotFound, manager.get_vendor, {})

        manager.register_vendor("default", "DEFAULT")
        self.assertEqual(manager.get_vendor({}), "DEFAULT")

        manager.ssh_vendor = None
        manager.set_ssh_version_string("OpenSSH")
        self.assertIsInstance(manager.get_vendor({}), OpenSSHSubprocessVendor)

        manager.ssh_vendor = None
        manager.register_vendor("vendor", "VENDOR")
        self.assertEqual(manager.get_vendor({"BZR_SSH": "vendor"}), "VENDOR")

        self.assertEqual(manager.get_vendor({}), "VENDOR")


class SubprocessVendorsTests(TestCase):

    def test_openssh_arguments(self):
        vendor = OpenSSHSubprocessVendor()
        self.assertEqual(
            vendor._get_vendor_specific_argv(
                "user", "host", 100, command=["bzr"]),
            ["ssh", "-oForwardX11=no", "-oForwardAgent=no",
                "-oClearAllForwardings=yes", "-oProtocol=2",
                "-oNoHostAuthenticationForLocalhost=yes",
                "-p", "100",
                "-l", "user",
                "host", "bzr"]
            )

    def test_sshcorp_arguments(self):
        vendor = SSHCorpSubprocessVendor()
        self.assertEqual(
            vendor._get_vendor_specific_argv(
                "user", "host", 100, command=["bzr"]),
            ["ssh", "-x",
                "-p", "100",
                "-l", "user",
                "host", "bzr"]
            )

    def test_plink_arguments(self):
        vendor = PLinkSubprocessVendor()
        self.assertEqual(
            vendor._get_vendor_specific_argv(
                "user", "host", 100, command=["bzr"]),
            ["plink", "-x", "-a", "-ssh", "-2",
                "-P", "100",
                "-l", "user",
                "host", "bzr"]
            )
