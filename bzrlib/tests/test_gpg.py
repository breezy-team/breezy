# Copyright (C) 2005, 2006, 2007, 2009, 2011 Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

"""Tests for signing and verifying blobs of data via gpg."""

# import system imports here
import sys

from bzrlib import errors, ui
import bzrlib.gpg as gpg
from bzrlib.tests import TestCase

class FakeConfig(object):

    def gpg_signing_command(self):
        return "false"


class TestCommandLine(TestCase):

    def test_signing_command_line(self):
        my_gpg = gpg.GPGStrategy(FakeConfig())
        self.assertEqual(['false',  '--clearsign'],
                         my_gpg._command_line())

    def test_checks_return_code(self):
        # This test needs a unix like platform - one with 'false' to run.
        # if you have one, please make this work :)
        my_gpg = gpg.GPGStrategy(FakeConfig())
        self.assertRaises(errors.SigningFailed, my_gpg.sign, 'content')

    def assertProduces(self, content):
        # This needs a 'cat' command or similar to work.
        my_gpg = gpg.GPGStrategy(FakeConfig())
        if sys.platform == 'win32':
            # Windows doesn't come with cat, and we don't require it
            # so lets try using python instead.
            # But stupid windows and line-ending conversions.
            # It is too much work to make sys.stdout be in binary mode.
            # http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/65443
            my_gpg._command_line = lambda:[sys.executable, '-c',
                    'import sys; sys.stdout.write(sys.stdin.read())']
            new_content = content.replace('\n', '\r\n')

            self.assertEqual(new_content, my_gpg.sign(content))
        else:
            my_gpg._command_line = lambda:['cat', '-']
            self.assertEqual(content, my_gpg.sign(content))

    def test_returns_output(self):
        content = "some content\nwith newlines\n"
        self.assertProduces(content)

    def test_clears_progress(self):
        content = "some content\nwith newlines\n"
        old_clear_term = ui.ui_factory.clear_term
        clear_term_called = []
        def clear_term():
            old_clear_term()
            clear_term_called.append(True)
        ui.ui_factory.clear_term = clear_term
        try:
            self.assertProduces(content)
        finally:
            ui.ui_factory.clear_term = old_clear_term
        self.assertEqual([True], clear_term_called)

    def test_aborts_on_unicode(self):
        """You can't sign Unicode text; it must be encoded first."""
        self.assertRaises(errors.BzrBadParameterUnicode,
                          self.assertProduces, u'foo')

    def test_verify_valid(self):
        """FIXME how to get this to work on a computer other than mine?"""
        content = """-----BEGIN PGP SIGNED MESSAGE-----
Hash: SHA1

bazaar-ng testament short form 1
revision-id: amy@example.com-20110527185938-hluafawphszb8dl1
sha1: 6411f9bdf6571200357140c9ce7c0f50106ac9a4
-----BEGIN PGP SIGNATURE-----
Version: GnuPG v1.4.11 (GNU/Linux)

iEYEARECAAYFAk33gYsACgkQpQbm1N1NUIhiDACglOuQDlnSF4NxfHSkN/zrmFy8
nswAoNGXAVuR9ONasAKIGBNUE0b+lolx
=SOuC
-----END PGP SIGNATURE-----
"""
        my_gpg = gpg.GPGStrategy(FakeConfig())
        self.assertEqual(gpg.SIGNATURE_VALID, my_gpg.verify(content))

    def test_verify_invalid(self):
        content = """-----BEGIN PGP SIGNED MESSAGE-----
Hash: SHA1

bazaar-ng testament short form 1
revision-id: amy@example.com-20110527185938-hluafawphszb8dl1
sha1: 6411f9bdf6571200357140c9ce7c0f50106ac9a4
-----BEGIN PGP SIGNATURE-----
Version: GnuPG v1.4.11 (GNU/Linux)

iEYEARECAAYFAk33gYsACgkQpQbm1N1NUIhiDACglOuQDlnSF4NxfHSkN/zrmFy8
nswAoNGXAVuR9ONasAKIGBNUE0b+lols
=SOuC
-----END PGP SIGNATURE-----
"""
        my_gpg = gpg.GPGStrategy(FakeConfig())
        self.assertEqual(gpg.SIGNATURE_NOT_VALID, my_gpg.verify(content))

#FIXME test if gpgme isn't installed?
#FIXME test for gpgme error?

    def test_set_acceptable_keys(self):
        my_gpg = gpg.GPGStrategy(FakeConfig())
        my_gpg.set_acceptable_keys("jriddell")
        self.assertEqual(my_gpg.acceptable_keys,
                        [u'13C16D03EDE728514473AA73A506E6D4DD4D5088'])

    def test_set_acceptable_keys_unknown(self):
        my_gpg = gpg.GPGStrategy(FakeConfig())
        my_gpg.set_acceptable_keys("unknown")
        self.assertEqual(my_gpg.acceptable_keys, [])

class TestDisabled(TestCase):

    def test_sign(self):
        self.assertRaises(errors.SigningFailed,
                          gpg.DisabledGPGStrategy(None).sign, 'content')

    def test_verify(self):
        self.assertRaises(errors.VerifyFailed,
                          gpg.DisabledGPGStrategy(None).verify, 'content')
