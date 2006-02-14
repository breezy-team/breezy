# Copyright (C) 2005 by Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for signing and verifying blobs of data via gpg."""

# import system imports here
import os
import sys

import bzrlib.errors as errors
import bzrlib.gpg as gpg
from bzrlib.tests import TestCase, TestCaseInTempDir

class FakeConfig(object):

    def gpg_signing_command(self):
        return "false"
        

class TestCommandLine(TestCase):

    def test_signing_command_line(self):
        my_gpg = gpg.GPGStrategy(FakeConfig())
        self.assertEqual(['false',  '--output', '-', '--clearsign'],
                         my_gpg._command_line())

    def test_checks_return_code(self):
        # This test needs a unix like platform - one with 'false' to run.
        # if you have one, please make this work :)
        my_gpg = gpg.GPGStrategy(FakeConfig())
        self.assertRaises(errors.SigningFailed, my_gpg.sign, 'content')

    def test_returns_output(self):
        # This test needs a 'cat' command or similar to work.
        my_gpg = gpg.GPGStrategy(FakeConfig())
        content = "some content\nwith newlines\n"

        if sys.platform == 'win32':
            # Windows doesn't come with cat, and we don't require it
            # so lets try using python instead.
            # But stupid windows and line-ending conversions. 
            # It is too much work to make sys.stdout be in binary mode.
            # http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/65443
            my_gpg._command_line = lambda:[sys.executable, '-c',
                    'import sys; sys.stdout.write(open(sys.argv[-1].read()))']
            new_content = content.replace('\n', '\r\n')

            self.assertEqual(new_content, my_gpg.sign(content))
        else:
            my_gpg._command_line = lambda:['cat']
            self.assertEqual(content, my_gpg.sign(content))


class TestDisabled(TestCase):

    def test_sign(self):
        self.assertRaises(errors.SigningFailed,
                          gpg.DisabledGPGStrategy(None).sign, 'content')
