# Copyright (C) 2005-2014, 2016 Canonical Ltd
# Copyright (C) 2019 Breezy developers
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

"""Tests for deriving user configuration from system environment."""

import os
import sys

from .. import bedding, osutils, tests

if sys.platform == "win32":
    from .. import win32utils


def override_whoami(test):
    test.overrideEnv("EMAIL", None)
    test.overrideEnv("BRZ_EMAIL", None)
    # Also, make sure that it's not inferred from mailname.
    test.overrideAttr(bedding, "_auto_user_id", lambda: (None, None))


class TestConfigPath(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.overrideEnv("HOME", "/home/bogus")
        self.overrideEnv("XDG_CACHE_HOME", "")
        if sys.platform == "win32":
            self.overrideEnv(
                "BRZ_HOME", r"C:\Documents and Settings\bogus\Application Data"
            )
            self.brz_home = "C:/Documents and Settings/bogus/Application Data/breezy"
        else:
            self.brz_home = "/home/bogus/.config/breezy"

    def test_config_dir(self):
        self.assertEqual(bedding.config_dir(), self.brz_home)

    def test_config_dir_is_unicode(self):
        self.assertIsInstance(bedding.config_dir(), str)

    def test_config_path(self):
        self.assertEqual(bedding.config_path(), self.brz_home + "/breezy.conf")

    def test_locations_config_path(self):
        self.assertEqual(
            bedding.locations_config_path(), self.brz_home + "/locations.conf"
        )

    def test_authentication_config_path(self):
        self.assertEqual(
            bedding.authentication_config_path(), self.brz_home + "/authentication.conf"
        )


class TestConfigPathFallback(tests.TestCaseInTempDir):
    def setUp(self):
        super().setUp()
        self.overrideEnv("HOME", self.test_dir)
        self.overrideEnv("XDG_CACHE_HOME", "")
        self.bzr_home = os.path.join(self.test_dir, ".bazaar")
        os.mkdir(self.bzr_home)

    def test_config_dir(self):
        self.assertEqual(bedding.config_dir(), self.bzr_home)

    def test_config_dir_is_unicode(self):
        self.assertIsInstance(bedding.config_dir(), str)

    def test_config_path(self):
        self.assertEqual(bedding.config_path(), self.bzr_home + "/bazaar.conf")

    def test_locations_config_path(self):
        self.assertEqual(
            bedding.locations_config_path(), self.bzr_home + "/locations.conf"
        )

    def test_authentication_config_path(self):
        self.assertEqual(
            bedding.authentication_config_path(), self.bzr_home + "/authentication.conf"
        )


class TestConfigPathFallbackWindows(tests.TestCaseInTempDir):
    def mock_special_folder_path(self, csidl):
        if csidl == win32utils.CSIDL_APPDATA:
            return self.appdata
        elif csidl == win32utils.CSIDL_PERSONAL:
            return self.test_dir
        return None

    def setUp(self):
        if sys.platform != "win32":
            raise tests.TestNotApplicable("This test is specific to Windows platform")
        super().setUp()
        # Note: No HOME fallback on Windows.  The configs MUST be in AppData,
        # and we only fall back from breezy to bazaar configuration files.
        self.appdata = os.path.join(self.test_dir, "appdata")
        self.appdata_bzr = os.path.join(self.appdata, "bazaar", "2.0")
        os.makedirs(self.appdata_bzr)
        self.overrideAttr(
            win32utils, "_get_sh_special_folder_path", self.mock_special_folder_path
        )
        # The safety net made by super() has set BZR_HOME and BRZ_HOME
        # to the temporary directory.  As they take precedence, we need
        # to erase the variables in order to check Windows special folders.
        self.overrideEnv("BRZ_HOME", None)
        self.overrideEnv("BZR_HOME", None)

    def test_config_dir(self):
        self.assertIsSameRealPath(bedding.config_dir(), self.appdata_bzr)

    def test_config_dir_is_unicode(self):
        self.assertIsInstance(bedding.config_dir(), str)

    def test_config_path(self):
        self.assertIsSameRealPath(
            bedding.config_path(), self.appdata_bzr + "/bazaar.conf"
        )
        self.overrideAttr(win32utils, "get_appdata_location", lambda: None)
        self.assertRaises(RuntimeError, bedding.config_path)

    def test_locations_config_path(self):
        self.assertIsSameRealPath(
            bedding.locations_config_path(), self.appdata_bzr + "/locations.conf"
        )
        self.overrideAttr(win32utils, "get_appdata_location", lambda: None)
        self.assertRaises(RuntimeError, bedding.locations_config_path)

    def test_authentication_config_path(self):
        self.assertIsSameRealPath(
            bedding.authentication_config_path(),
            self.appdata_bzr + "/authentication.conf",
        )
        self.overrideAttr(win32utils, "get_appdata_location", lambda: None)
        self.assertRaises(RuntimeError, bedding.authentication_config_path)


class TestXDGConfigDir(tests.TestCaseInTempDir):
    # must be in temp dir because config tests for the existence of the bazaar
    # subdirectory of $XDG_CONFIG_HOME

    def setUp(self):
        if sys.platform == "win32":
            raise tests.TestNotApplicable("XDG config dir not used on this platform")
        super().setUp()
        self.overrideEnv("HOME", self.test_home_dir)
        # BRZ_HOME overrides everything we want to test so unset it.
        self.overrideEnv("BRZ_HOME", None)

    def test_xdg_config_dir_exists(self):
        """When ~/.config/bazaar exists, use it as the config dir."""
        newdir = osutils.pathjoin(self.test_home_dir, ".config", "bazaar")
        os.makedirs(newdir)
        self.assertEqual(bedding.config_dir(), newdir)

    def test_xdg_config_home(self):
        """When XDG_CONFIG_HOME is set, use it."""
        xdgconfigdir = osutils.pathjoin(self.test_home_dir, "xdgconfig")
        self.overrideEnv("XDG_CONFIG_HOME", xdgconfigdir)
        newdir = osutils.pathjoin(xdgconfigdir, "bazaar")
        os.makedirs(newdir)
        self.assertEqual(bedding.config_dir(), newdir)

    def test_ensure_config_dir_exists(self):
        xdgconfigdir = osutils.pathjoin(self.test_home_dir, "xdgconfig")
        self.overrideEnv("XDG_CONFIG_HOME", xdgconfigdir)
        bedding.ensure_config_dir_exists()
        newdir = osutils.pathjoin(xdgconfigdir, "breezy")
        self.assertTrue(os.path.isdir(newdir))


class TestDefaultMailDomain(tests.TestCaseInTempDir):
    """Test retrieving default domain from mailname file."""

    def test_default_mail_domain_simple(self):
        with open("simple", "w") as f:
            f.write("domainname.com\n")
        r = bedding._get_default_mail_domain("simple")
        self.assertEqual("domainname.com", r)

    def test_default_mail_domain_no_eol(self):
        with open("no_eol", "w") as f:
            f.write("domainname.com")
        r = bedding._get_default_mail_domain("no_eol")
        self.assertEqual("domainname.com", r)

    def test_default_mail_domain_multiple_lines(self):
        with open("multiple_lines", "w") as f:
            f.write("domainname.com\nsome other text\n")
        r = bedding._get_default_mail_domain("multiple_lines")
        self.assertEqual("domainname.com", r)


class TestAutoUserId(tests.TestCase):
    """Test inferring an automatic user name."""

    def test_auto_user_id(self):
        """Automatic inference of user name.

        This is a bit hard to test in an isolated way, because it depends on
        system functions that go direct to /etc or perhaps somewhere else.
        But it's reasonable to say that on Unix, with an /etc/mailname, we ought
        to be able to choose a user name with no configuration.
        """
        if sys.platform == "win32":
            raise tests.TestSkipped("User name inference not implemented on win32")
        realname, address = bedding._auto_user_id()
        if os.path.exists("/etc/mailname"):
            self.assertIsNot(None, realname)
            self.assertIsNot(None, address)
        else:
            self.assertEqual((None, None), (realname, address))


class TestXDGCacheDir(tests.TestCaseInTempDir):
    # must be in temp dir because tests for the existence of the breezy
    # subdirectory of $XDG_CACHE_HOME

    def setUp(self):
        super().setUp()
        if sys.platform in ("darwin", "win32"):
            raise tests.TestNotApplicable("XDG cache dir not used on this platform")
        self.overrideEnv("HOME", self.test_home_dir)
        # BZR_HOME overrides everything we want to test so unset it.
        self.overrideEnv("BZR_HOME", None)

    def test_xdg_cache_dir_exists(self):
        """When ~/.cache/breezy exists, use it as the cache dir."""
        cachedir = osutils.pathjoin(self.test_home_dir, ".cache")
        newdir = osutils.pathjoin(cachedir, "breezy")
        self.assertEqual(bedding.cache_dir(), newdir)

    def test_xdg_cache_home_unix(self):
        """When XDG_CACHE_HOME is set, use it."""
        if sys.platform in ("nt", "win32"):
            raise tests.TestNotApplicable("XDG cache dir not used on this platform")
        xdgcachedir = osutils.pathjoin(self.test_home_dir, "xdgcache")
        self.overrideEnv("XDG_CACHE_HOME", xdgcachedir)
        newdir = osutils.pathjoin(xdgcachedir, "breezy")
        self.assertEqual(bedding.cache_dir(), newdir)
