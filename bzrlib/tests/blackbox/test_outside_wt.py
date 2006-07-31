# Copyright (C) 2006 by Canonical Ltd
# -*- coding: utf-8 -*-
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


"""Black-box tests for running bzr outside of a working tree."""

import os
import tempfile

from bzrlib.tests import ChrootedTestCase
from bzrlib.osutils import getcwd
import bzrlib.urlutils as urlutils


class TestOutsideWT(ChrootedTestCase):
    """Test that bzr gives proper errors outside of a working tree."""

    def test_cwd_log(self):
        os.chdir(tempfile.mkdtemp())
        out, err = self.run_bzr('log', retcode=3)
        self.assertEqual(u'bzr: ERROR: Not a branch: %s/\n' % (getcwd(),),
                         err)

    def test_url_log(self):
        url = self.get_readonly_url() + 'subdir/'
        out, err = self.run_bzr('log', 
                                url, retcode=3)
        self.assertEqual(u'bzr: ERROR: Not a branch:'
                         u' %s\n' % url, err)

    def test_diff_ouside_tree(self):
        os.chdir(tempfile.mkdtemp())
        self.run_bzr_captured(['init', 'branch1'])
        self.run_bzr_captured(['commit', '-m', 'nothing', 
                               '--unchanged', 'branch1'])
        self.run_bzr_captured(['commit', '-m', 'nothing', 
                               '--unchanged', 'branch1'])
        # -r X..Y
        out, err = self.run_bzr_captured(['diff', 
                                          '-r', 'revno:2:branch2..revno:1'],
                                         retcode=3)
        self.assertEquals('', out)
        self.assertEqual(u'bzr: ERROR: Not a branch: %s/\n' % (getcwd(),),
                         err)
        # -r X
        out, err = self.run_bzr_captured(['diff', '-r', 'revno:2:branch2'],
                                         retcode=3)
        self.assertEquals('', out)
        self.assertEqual(u'bzr: ERROR: Not a branch: %s/\n' % (getcwd(),),
                         err)
        # -r X..
        out, err = self.run_bzr_captured(['diff', '-r', 'revno:2:branch2..'],
                                         retcode=3)
        self.assertEquals('', out)
        self.assertEqual(u'bzr: ERROR: Not a branch: %s/\n' % (getcwd(),),
                         err)
        # no -r at all.
        out, err = self.run_bzr_captured(['diff'],
                                         retcode=3)
        self.assertEquals('', out)
        self.assertEqual(u'bzr: ERROR: Not a branch: %s/\n' % (getcwd(),),
                         err)
        

