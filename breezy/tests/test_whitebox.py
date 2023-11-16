# Copyright (C) 2005, 2006, 2008-2012 Canonical Ltd
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

import os
import tempfile

from .. import errors, osutils, tests
from ..osutils import abspath, pathjoin, realpath, relpath


class MoreTests(tests.TestCaseWithTransport):
    def test_relpath(self):
        """Test for branch path lookups.

        breezy.osutils._relpath do a simple but subtle
        job: given a path (either relative to cwd or absolute), work out
        if it is inside a branch and return the path relative to the base.
        """
        dtmp = tempfile.mkdtemp()
        self.addCleanup(osutils.rmtree, dtmp)
        # On Mac OSX, /tmp actually expands to /private/tmp
        dtmp = realpath(dtmp)

        def rp(p):
            return relpath(dtmp, p)

        # check paths inside dtmp while standing outside it
        self.assertEqual("foo", rp(pathjoin(dtmp, "foo")))

        # root = nothing
        self.assertEqual("", rp(dtmp))
        self.assertRaises(errors.PathNotChild, rp, "/etc")

        # now some near-miss operations -- note that
        # os.path.commonprefix gets these wrong!
        self.assertRaises(errors.PathNotChild, rp, dtmp.rstrip("\\/") + "2")
        self.assertRaises(errors.PathNotChild, rp, dtmp.rstrip("\\/") + "2/foo")

        # now operations based on relpath of files in current
        # directory, or nearby

        os.chdir(dtmp)
        self.assertEqual("foo/bar/quux", rp("foo/bar/quux"))
        self.assertEqual("foo", rp("foo"))
        self.assertEqual("foo", rp("./foo"))
        self.assertEqual("foo", rp(abspath("foo")))
        self.assertRaises(errors.PathNotChild, rp, "../foo")
