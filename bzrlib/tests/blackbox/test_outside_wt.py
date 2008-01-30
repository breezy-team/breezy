# Copyright (C) 2006 Canonical Ltd
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

from bzrlib import (
    osutils,
    tests,
    urlutils,
    )


class TestOutsideWT(tests.ChrootedTestCase):
    """Test that bzr gives proper errors outside of a working tree."""

    def test_cwd_log(self):
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: osutils.rmtree(tmp_dir))
        os.chdir(tmp_dir)
        out, err = self.run_bzr('log', retcode=3)
        self.assertEqual(u'bzr: ERROR: Not a branch: "%s/".\n'
                         % (osutils.getcwd(),),
                         err)

    def test_url_log(self):
        url = self.get_readonly_url() + 'subdir/'
        out, err = self.run_bzr(['log', url], retcode=3)
        self.assertEqual(u'bzr: ERROR: Not a branch:'
                         u' "%s".\n' % url, err)

    def test_diff_outside_tree(self):
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: osutils.rmtree(tmp_dir))
        os.chdir(tmp_dir)
        self.run_bzr('init branch1')
        self.run_bzr(['commit', '-m', 'nothing',
                               '--unchanged', 'branch1'])
        self.run_bzr(['commit', '-m', 'nothing',
                               '--unchanged', 'branch1'])
        this_dir = osutils.getcwd()
        branch2 = "%s/branch2" % (this_dir,)
        # -r X..Y
        out, err = self.run_bzr('diff -r revno:2:branch2..revno:1', retcode=3)
        self.assertEquals('', out)
        self.assertEqual(u'bzr: ERROR: Not a branch: "%s/".\n' % (branch2,),
                         err)
        # -r X
        out, err = self.run_bzr('diff -r revno:2:branch2', retcode=3)
        self.assertEquals('', out)
        self.assertEqual(u'bzr: ERROR: Not a branch: "%s/".\n' % (branch2,),
                         err)
        # -r X..
        out, err = self.run_bzr('diff -r revno:2:branch2..', retcode=3)
        self.assertEquals('', out)
        self.assertEqual(u'bzr: ERROR: Not a branch: "%s/".\n' % (branch2,),
                         err)
        # no -r at all.
        out, err = self.run_bzr('diff', retcode=3)
        self.assertEquals('', out)
        self.assertEqual(u'bzr: ERROR: Not a branch: "%s/".\n' % (this_dir,),
                         err)
