# Copyright (C) 2006 Canonical Ltd
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

"""Basic tests for AtomicFile"""

import os
import stat
import sys

from bzrlib import (
    atomicfile,
    errors,
    osutils,
    symbol_versioning,
    )
from bzrlib.tests import TestCaseInTempDir


class TestAtomicFile(TestCaseInTempDir):

    def test_commit(self):
        f = atomicfile.AtomicFile('test')
        self.failIfExists('test')
        f.write('foo\n')
        f.commit()

        self.assertEqual(['test'], os.listdir('.'))
        self.check_file_contents('test', 'foo\n')
        self.assertRaises(errors.AtomicFileAlreadyClosed, f.commit)
        self.assertRaises(errors.AtomicFileAlreadyClosed, f.abort)
        # close is re-entrant safe
        f.close()

    def test_abort(self):
        f = atomicfile.AtomicFile('test')
        f.write('foo\n')
        f.abort()
        self.assertEqual([], os.listdir('.'))

        self.assertRaises(errors.AtomicFileAlreadyClosed, f.abort)
        self.assertRaises(errors.AtomicFileAlreadyClosed, f.commit)

        # close is re-entrant safe
        f.close()

    def test_close(self):
        f = atomicfile.AtomicFile('test')
        f.write('foo\n')
        # close on an open file is an abort
        f.close()
        self.assertEqual([], os.listdir('.'))

        self.assertRaises(errors.AtomicFileAlreadyClosed, f.abort)
        self.assertRaises(errors.AtomicFileAlreadyClosed, f.commit)

        # close is re-entrant safe
        f.close()
        
    def test_text_mode(self):
        f = atomicfile.AtomicFile('test', mode='wt')
        f.write('foo\n')
        f.commit()

        contents = open('test', 'rb').read()
        if sys.platform == 'win32':
            self.assertEqual('foo\r\n', contents)
        else:
            self.assertEqual('foo\n', contents)

    def can_sys_preserve_mode(self):
        # PLATFORM DEFICIENCY/ TestSkipped
        return sys.platform not in ('win32',)

    def _test_mode(self, mode):
        if not self.can_sys_preserve_mode():
            return
        f = atomicfile.AtomicFile('test', mode='wb', new_mode=mode)
        f.write('foo\n')
        f.commit()
        st = os.lstat('test')
        self.assertEqualMode(mode, stat.S_IMODE(st.st_mode))

    def test_mode_02666(self):
        self._test_mode(02666)

    def test_mode_0666(self):
        self._test_mode(0666)

    def test_mode_0664(self):
        self._test_mode(0664)

    def test_mode_0660(self):
        self._test_mode(0660)

    def test_mode_0660(self):
        self._test_mode(0660)

    def test_mode_0640(self):
        self._test_mode(0640)

    def test_mode_0600(self):
        self._test_mode(0600)

    def test_mode_0400(self):
        self._test_mode(0400)
        # Make it read-write again so cleanup doesn't complain
        os.chmod('test', 0600)

    def test_no_mode(self):
        # The default file permissions should be based on umask
        umask = osutils.get_umask()
        f = atomicfile.AtomicFile('test', mode='wb')
        f.write('foo\n')
        f.commit()
        st = os.lstat('test')
        self.assertEqualMode(0666 & ~umask, stat.S_IMODE(st.st_mode))

    def test_closed(self):
        local_warnings = []
        def capture_warnings(msg, cls, stacklevel=None):
            self.assertEqual(cls, DeprecationWarning)
            local_warnings.append(msg)

        method = symbol_versioning.warn
        try:
            symbol_versioning.set_warning_method(capture_warnings)
            f = atomicfile.AtomicFile('test', mode='wb')
            self.assertEqual(False, f.closed)
            f.abort()
            self.assertEqual(True, f.closed)

            f = atomicfile.AtomicFile('test', mode='wb')
            f.close()
            self.assertEqual(True, f.closed)

            f = atomicfile.AtomicFile('test', mode='wb')
            f.commit()
            self.assertEqual(True, f.closed)
        finally:
            symbol_versioning.set_warning_method(method)

        txt = 'AtomicFile.closed deprecated in bzr 0.10'
        self.assertEqual([txt]*4, local_warnings)
