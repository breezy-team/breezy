# Copyright (C) 2005, 2006 by Canonical Ltd
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
#

"""Tests of the 'bzr setup-default-ignores' command."""

import sys

import bzrlib
from bzrlib import config
from bzrlib.tests import TestCaseInTempDir


class TestSetupDefaultIgnores(TestCaseInTempDir):
    
    def test_create(self):
        user_ignore_file = config.user_ignore_config_filename()
        out, err = self.run_bzr('setup-default-ignores')
        self.assertEqual('', err)
        
        helpful_ignore_fname = '~/.bazaar/ignore'
        if sys.platform == 'win32':
            helpful_ignore_fname = user_ignore_file

        expected_out = 'Wrote %d patterns to %s\n' % (
                        len(bzrlib.DEFAULT_IGNORE),
                        helpful_ignore_fname)

        self.assertEqual(expected_out, out)

        f = open(user_ignore_file, 'rb')
        try:
            # This ensures the file is properly encoded
            lines = f.read().decode('utf8').splitlines()
        finally:
            f.close()

        # And we added the right patterns
        self.assertEqual(len(lines), len(bzrlib.DEFAULT_IGNORE))
        for line, ignore in zip(lines, bzrlib.DEFAULT_IGNORE):
            self.assertEqual(line, ignore)

    def test_no_overwrite(self):
        user_ignore_file = config.user_ignore_config_filename()
        config.ensure_config_dir_exists()

        f = open(user_ignore_file, 'wb')
        try:
            f.write('foo\nbar\n*.sw[nop]\n')
        finally:
            f.close()

        self.run_bzr_error(['bzr: ERROR: .*ignore already exists'],
                           'setup-default-ignores')

        # Make sure nothing was changed
        self.check_file_contents(user_ignore_file, 'foo\nbar\n*.sw[nop]\n')
