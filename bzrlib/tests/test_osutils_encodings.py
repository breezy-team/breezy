# Copyright (C) 2005, 2006 Canonical Ltd
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

"""Tests for the osutils wrapper."""

import codecs
import encodings
import sys

import bzrlib
from bzrlib import (
    errors,
    osutils,
    )
from bzrlib.tests import (
        StringIOWrapper,
        TestCase, 
        TestSkipped,
        )


class FakeCodec(object):
    """Special singleton class that helps testing
    over several non-existed encodings.
    
    Clients could add new encoding names, but cannot remove it.
    """
    _registered = False
    _enabled_encodings = set()

    def add(self, encoding_name):
        if not self._registered:
            codecs.register(self)
            self._registered = True
        self._enabled_encodings.add(encoding_name)
        
    def __call__(self, encoding_name):
        """Called indirectly by codecs module during lookup"""
        if encoding_name in self._enabled_encodings:
            return codecs.lookup('latin-1')
#class FakeCodec

fake_codec = FakeCodec()


class TestFakeCodec(TestCase):
    
    def test_fake_codec(self):
        self.assertRaises(LookupError, codecs.lookup, 'fake')

        fake_codec.add('fake')
        codecs.lookup('fake')


class TestTerminalEncoding(TestCase):
    """Test the auto-detection of proper terminal encoding."""

    def setUp(self):
        self._stdout = sys.stdout
        self._stderr = sys.stderr
        self._stdin = sys.stdin
        self._user_encoding = bzrlib.user_encoding

        self.addCleanup(self._reset)

    def make_wrapped_streams(self, 
                             stdout_encoding,
                             stderr_encoding,
                             stdin_encoding,
                             user_encoding='user_encoding',
                             enable_fake_encodings=True):
        sys.stdout = StringIOWrapper()
        sys.stdout.encoding = stdout_encoding
        fake_codec.add(stdout_encoding)
        sys.stderr = StringIOWrapper()
        sys.stderr.encoding = stderr_encoding
        fake_codec.add(stderr_encoding)
        sys.stdin = StringIOWrapper()
        sys.stdin.encoding = stdin_encoding
        fake_codec.add(stdin_encoding)
        bzrlib.user_encoding = user_encoding

    def _reset(self):
        sys.stdout = self._stdout
        sys.stderr = self._stderr
        sys.stdin = self._stdin
        bzrlib.user_encoding = self._user_encoding

    def test_get_terminal_encoding(self):
        self.make_wrapped_streams('stdout_encoding',
                                  'stderr_encoding',
                                  'stdin_encoding')

        # first preference is stdout encoding
        self.assertEqual('stdout_encoding', osutils.get_terminal_encoding())

        sys.stdout.encoding = None
        # if sys.stdout is None, fall back to sys.stdin
        self.assertEqual('stdin_encoding', osutils.get_terminal_encoding())

        sys.stdin.encoding = None
        # and in the worst case, use bzrlib.user_encoding
        self.assertEqual('user_encoding', osutils.get_terminal_encoding())

    def test_terminal_cp0(self):
        # test cp0 encoding (Windows tell cp0 when there is no encoding)
        self.make_wrapped_streams('cp0',
                                  None,
                                  None,
                                  user_encoding='latin-1',
                                  enable_fake_encodings=False)

        # cp0 is invalid encoding. We should fall back to user_encoding
        self.assertEqual('latin-1', osutils.get_terminal_encoding())

        # check stderr
        self.assertEquals('', sys.stderr.getvalue())

    def test_terminal_cpUNKNOWN(self):
        # test against really unknown encoding
        # catch warning at stderr
        self.make_wrapped_streams('cpUNKNOWN',
                                  None,
                                  None,
                                  user_encoding='latin-1',
                                  enable_fake_encodings=False)
        
        self.assertEqual('latin-1', osutils.get_terminal_encoding())

        # check stderr
        self.assertEquals('bzr: warning: unknown encoding cpUNKNOWN.\n'
                          '  Using encoding latin-1 instead.\n', 
                          sys.stderr.getvalue())
