# Copyright (C) 2005 by Canonical Ltd
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

"""Test that various operations work in a non-ASCII environment."""

import os
import sys
from unicodedata import normalize

from bzrlib import osutils
from bzrlib.osutils import pathjoin
from bzrlib.tests import TestCase, TestCaseWithTransport, TestSkipped
from bzrlib.workingtree import WorkingTree


class NonAsciiTest(TestCaseWithTransport):

    def test_add_in_nonascii_branch(self):
        """Test adding in a non-ASCII branch."""
        br_dir = u"\u1234"
        try:
            wt = self.make_branch_and_tree(br_dir)
        except UnicodeEncodeError:
            raise TestSkipped("filesystem can't accomodate nonascii names")
            return
        file(pathjoin(br_dir, "a"), "w").write("hello")
        wt.add(["a"], ["a-id"])


a_circle_c = u'\xe5'
a_circle_d = u'a\u030a'
a_dots_c = u'\xe4'
a_dots_d = u'a\u0308'
z_umlat_c = u'\u017d'
z_umlat_d = u'Z\u030c'


class TestNormalization(TestCase):
    """Verify that we have our normalizations correct."""

    def test_normalize(self):
        self.assertEqual(a_circle_d, normalize('NFKD', a_circle_c))
        self.assertEqual(a_circle_c, normalize('NFKC', a_circle_d))
        self.assertEqual(a_dots_d, normalize('NFKD', a_dots_c))
        self.assertEqual(a_dots_c, normalize('NFKC', a_dots_d))
        self.assertEqual(z_umlat_d, normalize('NFKD', z_umlat_c))
        self.assertEqual(z_umlat_c, normalize('NFKC', z_umlat_d))


class NormalizedFilename(TestCaseWithTransport):
    """Test normalized_filename and associated helpers"""

    def test__accessible_normalized_filename(self):
        anf = osutils._accessible_normalized_filename
        self.assertEqual((a_circle_c, True), anf(a_circle_c))
        self.assertEqual((a_circle_c, True), anf(a_circle_d))
        self.assertEqual((a_dots_c, True), anf(a_dots_c))
        self.assertEqual((a_dots_c, True), anf(a_dots_d))
        self.assertEqual((z_umlat_c, True), anf(z_umlat_c))
        self.assertEqual((z_umlat_c, True), anf(z_umlat_d))

    def test__inaccessible_normalized_filename(self):
        inf = osutils._inaccessible_normalized_filename
        self.assertEqual((a_circle_c, True), inf(a_circle_c))
        self.assertEqual((a_circle_c, False), inf(a_circle_d))
        self.assertEqual((a_dots_c, True), inf(a_dots_c))
        self.assertEqual((a_dots_c, False), inf(a_dots_d))
        self.assertEqual((z_umlat_c, True), inf(z_umlat_c))
        self.assertEqual((z_umlat_c, False), inf(z_umlat_d))

    def test_functions(self):
        if osutils.normalizes_filenames():
            self.assertEqual(osutils.normalized_filename,
                             osutils._accessible_normalized_filename)
        else:
            self.assertEqual(osutils.normalized_filename,
                             osutils._inaccessible_normalized_filename)

    def test_platform(self):
        try:
            self.build_tree([a_circle_c, a_dots_c, z_umlat_c])
        except UnicodeError:
            raise TestSkipped("filesystem cannot create unicode files")

        if sys.platform == 'darwin':
            expected = sorted([a_circle_d, a_dots_d, z_umlat_d])
        else:
            expected = sorted([a_circle_c, a_dots_c, z_umlat_c])

        present = sorted(os.listdir(u'.'))
        self.assertEqual(expected, present)

    def test_access_normalized(self):
        # We should always be able to access files created with normalized filenames
        files = [a_circle_c, a_dots_c, z_umlat_c]
        try:
            self.build_tree(files)
        except UnicodeError:
            raise TestSkipped("filesystem cannot create unicode files")

        for fname in files:
            # We should get an exception if we can't open the file at
            # this location.
            path, can_access = osutils.normalized_filename(fname)

            self.assertEqual(path, fname)
            self.assertTrue(can_access)

            f = open(path, 'rb')
            f.close()

    def test_access_non_normalized(self):
        # Sometimes we can access non-normalized files by their normalized
        # path, verify that normalized_filename returns the right info
        files = [a_circle_d, a_dots_d, z_umlat_d]

        try:
            self.build_tree(files)
        except UnicodeError:
            raise TestSkipped("filesystem cannot create unicode files")

        for fname in files:
            # We should get an exception if we can't open the file at
            # this location.
            path, can_access = osutils.normalized_filename(fname)

            self.assertNotEqual(path, fname)

            # We should always be able to access them from the name
            # they were created with
            f = open(fname, 'rb')
            f.close()

            # And normalized_filename sholud tell us correctly if we can
            # access them by an alternate name
            if can_access:
                f = open(path, 'rb')
                f.close()
            else:
                self.assertRaises(IOError, open, path, 'rb')
