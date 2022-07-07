# Copyright (C) 2006, 2009, 2010, 2011 Canonical Ltd
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

"""Tests for versioning of breezy."""

from io import StringIO
import platform
import re

from .. import (
    tests,
    version,
    workingtree,
    )
from .scenarios import load_tests_apply_scenarios


load_tests = load_tests_apply_scenarios


class TestBzrlibVersioning(tests.TestCase):

    def test_get_brz_source_tree(self):
        """Get tree for bzr source, if any."""
        self.permit_source_tree_branch_repo()
        # We don't know if these tests are being run from a checkout or branch
        # of bzr, from an installed copy, or from source unpacked from a
        # tarball.  We don't construct a branch just for testing this, so we
        # just assert that it must either return None or the tree.
        src_tree = version._get_brz_source_tree()
        if src_tree is None:
            raise tests.TestSkipped(
                "bzr tests aren't run from a bzr working tree")
        else:
            # ensure that what we got was in fact a working tree instance.
            self.assertIsInstance(src_tree, workingtree.WorkingTree)

    def test_python_binary_path(self):
        self.permit_source_tree_branch_repo()
        sio = StringIO()
        version.show_version(show_config=False, show_copyright=False,
                             to_file=sio)
        out = sio.getvalue()
        m = re.search(r"Python interpreter: (.*) [0-9]", out)
        self.assertIsNot(m, None)
        self.assertPathExists(m.group(1))


class TestPlatformUse(tests.TestCase):

    scenarios = [('ascii', dict(_platform='test-platform')),
                 ('unicode', dict(_platform='Schr\xc3\xb6dinger'))]

    def setUp(self):
        super(TestPlatformUse, self).setUp()
        self.permit_source_tree_branch_repo()

    def test_platform(self):
        out = self.make_utf8_encoded_stringio()
        self.overrideAttr(platform, 'platform', lambda **
                          kwargs: self._platform)
        version.show_version(show_config=False, show_copyright=False,
                             to_file=out)
        expected = r'(?m)^  Platform: %s' % self._platform
        expected = expected.encode('utf-8')
        self.assertContainsRe(out.getvalue(), expected)
