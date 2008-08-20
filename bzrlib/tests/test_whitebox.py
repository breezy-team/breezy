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

import os
import unittest

from bzrlib import (
    osutils,
    )
from bzrlib.tests import TestCaseWithTransport, TestCase
from bzrlib.branch import Branch
from bzrlib.errors import PathNotChild
from bzrlib.osutils import relpath, pathjoin, abspath, realpath


class MoreTests(TestCaseWithTransport):

    def test_relpath(self):
        """test for branch path lookups
    
        bzrlib.osutils._relpath do a simple but subtle
        job: given a path (either relative to cwd or absolute), work out
        if it is inside a branch and return the path relative to the base.
        """
        import tempfile
        
        savedir = os.getcwdu()
        dtmp = tempfile.mkdtemp()
        # On Mac OSX, /tmp actually expands to /private/tmp
        dtmp = realpath(dtmp)

        def rp(p):
            return relpath(dtmp, p)
        
        try:
            # check paths inside dtmp while standing outside it
            self.assertEqual(rp(pathjoin(dtmp, 'foo')), 'foo')

            # root = nothing
            self.assertEqual(rp(dtmp), '')

            self.assertRaises(PathNotChild,
                              rp,
                              '/etc')

            # now some near-miss operations -- note that
            # os.path.commonprefix gets these wrong!
            self.assertRaises(PathNotChild,
                              rp,
                              dtmp.rstrip('\\/') + '2')

            self.assertRaises(PathNotChild,
                              rp,
                              dtmp.rstrip('\\/') + '2/foo')

            # now operations based on relpath of files in current
            # directory, or nearby
            os.chdir(dtmp)

            self.assertEqual(rp('foo/bar/quux'), 'foo/bar/quux')

            self.assertEqual(rp('foo'), 'foo')

            self.assertEqual(rp('./foo'), 'foo')

            self.assertEqual(rp(abspath('foo')), 'foo')

            self.assertRaises(PathNotChild,
                              rp, '../foo')

        finally:
            os.chdir(savedir)
            osutils.rmtree(dtmp)
