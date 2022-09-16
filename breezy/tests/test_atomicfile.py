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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Basic tests for AtomicFile"""

import os
import stat
import sys

from .. import (
    atomicfile,
    osutils,
    )
from . import TestCaseInTempDir, TestSkipped


class TestAtomicFile(TestCaseInTempDir):

    def test_commit(self):
        f = atomicfile.AtomicFile('test')
        self.assertPathDoesNotExist('test')
        f.write(b'foo\n')
        f.commit()

        self.assertEqual(['test'], os.listdir('.'))
        self.check_file_contents('test', b'foo\n')
        self.assertRaises(atomicfile.AtomicFileAlreadyClosed, f.commit)
        self.assertRaises(atomicfile.AtomicFileAlreadyClosed, f.abort)
        # close is re-entrant safe
        f.close()

    def test_abort(self):
        f = atomicfile.AtomicFile('test')
        f.write(b'foo\n')
        f.abort()
        self.assertEqual([], os.listdir('.'))

        self.assertRaises(atomicfile.AtomicFileAlreadyClosed, f.abort)
        self.assertRaises(atomicfile.AtomicFileAlreadyClosed, f.commit)

        # close is re-entrant safe
        f.close()

    def test_close(self):
        f = atomicfile.AtomicFile('test')
        f.write(b'foo\n')
        # close on an open file is an abort
        f.close()
        self.assertEqual([], os.listdir('.'))

        self.assertRaises(atomicfile.AtomicFileAlreadyClosed, f.abort)
        self.assertRaises(atomicfile.AtomicFileAlreadyClosed, f.commit)

        # close is re-entrant safe
        f.close()

    def test_text_mode(self):
        f = atomicfile.AtomicFile('test', mode='wt')
        f.write(b'foo\n')
        f.commit()

        with open('test', 'rb') as f:
            contents = f.read()
        if sys.platform == 'win32':
            self.assertEqual(b'foo\r\n', contents)
        else:
            self.assertEqual(b'foo\n', contents)

    def can_sys_preserve_mode(self):
        # PLATFORM DEFICIENCY/ TestSkipped
        return sys.platform not in ('win32',)

    def _test_mode(self, mode):
        if not self.can_sys_preserve_mode():
            raise TestSkipped("This test cannot be run on your platform")
        f = atomicfile.AtomicFile('test', mode='wb', new_mode=mode)
        f.write(b'foo\n')
        f.commit()
        st = os.lstat('test')
        self.assertEqualMode(mode, stat.S_IMODE(st.st_mode))

    def test_mode_0666(self):
        self._test_mode(0o666)

    def test_mode_0664(self):
        self._test_mode(0o664)

    def test_mode_0660(self):
        self._test_mode(0o660)

    def test_mode_0660(self):
        self._test_mode(0o660)

    def test_mode_0640(self):
        self._test_mode(0o640)

    def test_mode_0600(self):
        self._test_mode(0o600)

    def test_mode_0400(self):
        self._test_mode(0o400)
        # Make it read-write again so cleanup doesn't complain
        os.chmod('test', 0o600)

    def test_no_mode(self):
        # The default file permissions should be based on umask
        umask = osutils.get_umask()
        f = atomicfile.AtomicFile('test', mode='wb')
        f.write(b'foo\n')
        f.commit()
        st = os.lstat('test')
        self.assertEqualMode(0o666 & ~umask, stat.S_IMODE(st.st_mode))

    def test_context_manager_commit(self):
        with atomicfile.AtomicFile('test') as f:
            self.assertPathDoesNotExist('test')
            f.write(b'foo\n')

        self.assertEqual(['test'], os.listdir('.'))
        self.check_file_contents('test', b'foo\n')

    def test_context_manager_abort(self):
        def abort():
            with atomicfile.AtomicFile('test') as f:
                f.write(b'foo\n')
                raise AssertionError
        self.assertRaises(AssertionError, abort)
        self.assertEqual([], os.listdir('.'))
