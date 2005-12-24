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

from bzrlib.tests import TestCaseInTempDir, TestSkipped

class TestLog(TestCaseInTempDir):

    def test_log_uses_stdout_encoding(self):
        # bzr log should be able to handle non-ascii characters
        # The trick is that the greek letter mu (µ)
        # exists in latin-1, as well as utf-8. 
        # So probably most encodings can handle it, 
        # but ascii would not be able to handle it
        import sys
        import bzrlib

        bzr = self.run_bzr

        mu = u'\xb5'
        encoding = getattr(sys.stdout, 'encoding', None)
        if not encoding:
            raise TestSkipped('sys.stdout must have a valid encoding'
                              'to test that it is used')

        try:
            encoded_mu = mu.encode(encoding)
        except UnicodeEncodeError:
            raise TestSkipped('encoding %r cannot encode greek letter mu' 
                              % encoding)

        old_encoding = bzrlib.user_encoding

        # This test requires that 'run_bzr' uses the current
        # bzrlib, because we override user_encoding, and expect
        # it to be used
        try:
            bzr('init')
            open('a', 'wb').write('some stuff\n')
            bzr('add', 'a')
            bzr('commit', '-m', u'Message with ' + mu)

            bzrlib.user_encoding = 'ascii'
            # Log should not fail, even though we have a log message
            # with an invalid character. In fact, it should use sys.
            out, err = bzr('log')
            self.assertNotEqual(-1, out.find(encoded_mu))
        finally:
            bzrlib.user_encoding = old_encoding

