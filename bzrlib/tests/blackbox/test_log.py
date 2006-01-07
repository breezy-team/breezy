# Copyright (C) 2005 by Canonical Ltd
# -*- coding: utf-8 -*-

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Black-box tests for bzr log.
"""

import bzrlib
import sys
from bzrlib.tests import TestCaseInTempDir, TestSkipped

class TestLog(TestCaseInTempDir):

    _mu = u'\xb5'
    _message = u'Message with \xb5'

    # Encodings which can encode mu
    good_encodings = [
        'utf-8',
        'latin-1',
        'iso-8859-1',
        'cp437', # Common windows encoding
        'cp1251', # Alexander Belchenko's windows encoding
        'cp1258', # Common windows encoding
    ]
    # Encodings which cannot encode mu
    bad_encodings = [
        'ascii',
        'iso-8859-2',
        'koi8_r',
    ]

    def create_branch(self):
        bzr = self.run_bzr
        bzr('init')
        open('a', 'wb').write('some stuff\n')
        bzr('add', 'a')
        bzr('commit', '-m', self._message)

    def try_encoding(self, encoding, fail=False):
        bzr = self.run_bzr
        if fail:
            self.assertRaises(UnicodeEncodeError,
                self._mu.encode, encoding)
            encoded_msg = self._message.encode(encoding, 'replace')
        else:
            encoded_msg = self._message.encode(encoding)

        old_encoding = bzrlib.user_encoding
        # This test requires that 'run_bzr' uses the current
        # bzrlib, because we override user_encoding, and expect
        # it to be used
        try:
            bzrlib.user_encoding = 'ascii'
            # We should be able to handle any encoding
            out, err = bzr('log', encoding=encoding)
            if not fail:
                # Make sure we wrote mu as we expected it to exist
                self.assertNotEqual(-1, out.find(encoded_msg))
                out_unicode = out.decode(encoding)
                self.assertNotEqual(-1, out_unicode.find(self._message))
            else:
                self.assertNotEqual(-1, out.find('Message with ?'))
        finally:
            bzrlib.user_encoding = old_encoding

    def test_log_handles_encoding(self):
        self.create_branch()

        for encoding in self.good_encodings:
            self.try_encoding(encoding)

    def test_log_handles_bad_encoding(self):
        self.create_branch()

        for encoding in self.bad_encodings:
            self.try_encoding(encoding, fail=True)


