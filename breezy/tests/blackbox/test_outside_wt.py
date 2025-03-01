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


"""Black-box tests for running brz outside of a working tree."""

import tempfile

from breezy import osutils, tests


class TestOutsideWT(tests.ChrootedTestCase):
    """Test that brz gives proper errors outside of a working tree."""

    def test_cwd_log(self):
        # Watch out for tricky test dir (on OSX /tmp -> /private/tmp)
        tmp_dir = osutils.realpath(tempfile.mkdtemp())
        # We expect a read-to-root attempt to occur.
        self.permit_url("file:///")
        self.addCleanup(osutils.rmtree, tmp_dir)
        out, err = self.run_bzr("log", retcode=3, working_dir=tmp_dir)
        self.assertEqual('brz: ERROR: Not a branch: "{}/".\n'.format(tmp_dir), err)

    def test_url_log(self):
        url = self.get_readonly_url() + "subdir/"
        out, err = self.run_bzr(["log", url], retcode=3)
        self.assertEqual('brz: ERROR: Not a branch: "{}".\n'.format(url), err)

    def test_diff_outside_tree(self):
        tree = self.make_branch_and_tree("branch1")
        tree.commit("nothing")
        tree.commit("nothing")
        # A directory we can run commands from which we hope is not contained
        # in a brz tree (though if there is one at or above $TEMPDIR, this is
        # false and may cause test failures).
        # Watch out for tricky test dir (on OSX /tmp -> /private/tmp)
        tmp_dir = osutils.realpath(tempfile.mkdtemp())
        self.addCleanup(osutils.rmtree, tmp_dir)
        # We expect a read-to-root attempt to occur.
        self.permit_url("file:///")
        expected_error = 'brz: ERROR: Not a branch: "{}/branch2/".\n'.format(tmp_dir)
        # -r X..Y
        out, err = self.run_bzr(
            "diff -r revno:2:branch2..revno:1", retcode=3, working_dir=tmp_dir
        )
        self.assertEqual("", out)
        self.assertEqual(expected_error, err)
        # -r X
        out, err = self.run_bzr(
            "diff -r revno:2:branch2", retcode=3, working_dir=tmp_dir
        )
        self.assertEqual("", out)
        self.assertEqual(expected_error, err)
        # -r X..
        out, err = self.run_bzr(
            "diff -r revno:2:branch2..", retcode=3, working_dir=tmp_dir
        )
        self.assertEqual("", out)
        self.assertEqual(expected_error, err)
        # no -r at all.
        out, err = self.run_bzr("diff", retcode=3, working_dir=tmp_dir)
        self.assertEqual("", out)
        self.assertEqual('brz: ERROR: Not a branch: "{}/".\n'.format(tmp_dir), err)
