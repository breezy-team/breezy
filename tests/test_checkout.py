# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Checkout tests."""

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.errors import NoRepositoryPresent, UninitializableFormat
from bzrlib.tests import TestCase

from bzrlib.plugins.svn.convert import SvnConverter
from bzrlib.plugins.svn.workingtree import SvnWorkingTreeFormat
from bzrlib.plugins.svn.format import SvnWorkingTreeDirFormat
from bzrlib.plugins.svn.tests import TestCaseWithSubversionRepository

class TestWorkingTreeFormat(TestCase):
    def setUp(self):
        super(TestWorkingTreeFormat, self).setUp()
        self.format = SvnWorkingTreeFormat(4)

    def test_get_format_desc(self):
        self.assertEqual("Subversion Working Copy Version 4", 
                         self.format.get_format_description())

    def test_initialize(self):
        self.assertRaises(NotImplementedError, self.format.initialize, None)

    def test_open(self):
        self.assertRaises(NotImplementedError, self.format.open, None)


class TestCheckoutFormat(TestCase):
    def setUp(self):
        super(TestCheckoutFormat, self).setUp()
        self.format = SvnWorkingTreeDirFormat()

    def test_get_converter(self):
        self.assertRaises(NotImplementedError, self.format.get_converter)

    def test_initialize(self):
        self.assertRaises(UninitializableFormat, 
                          self.format.initialize_on_transport, None)


class TestCheckout(TestCaseWithSubversionRepository):
    def test_not_for_writing(self):
        self.make_client("d", "dc")
        x = BzrDir.create_branch_convenience("dc/foo")
        self.assertFalse(hasattr(x.repository, "uuid"))

    def test_open_repository(self):
        self.make_client("d", "dc")
        x = self.open_checkout_bzrdir("dc")
        self.assertRaises(NoRepositoryPresent, x.open_repository)

    def test_find_repository(self):
        self.make_client("d", "dc")
        x = self.open_checkout_bzrdir("dc")
        self.assertRaises(NoRepositoryPresent, x.find_repository)

    def test__find_repository(self):
        self.make_client("d", "dc")
        x = self.open_checkout_bzrdir("dc")
        self.assertTrue(hasattr(x._find_repository(), "uuid"))

    def test_needs_format_conversion_default(self):
        self.make_client("d", "dc")
        x = self.open_checkout_bzrdir("dc")
        self.assertTrue(x.needs_format_conversion())

    def test_needs_format_conversion_self(self):
        self.make_client("d", "dc")
        x = self.open_checkout_bzrdir("dc")
        self.assertFalse(x.needs_format_conversion(SvnWorkingTreeDirFormat()))
        
    def test_checkout_checkout(self):
        """Test making a checkout of a checkout."""
        self.make_client("d", "dc")
        x = Branch.open("dc")
        x.create_checkout("de", lightweight=True)

    def test_checkout_branch(self):
        repos_url = self.make_client("d", "dc")

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("trunk")
        dc.close()

        self.client_update("dc")
        x = self.open_checkout_bzrdir("dc/trunk")
        self.assertEquals(repos_url+"/trunk", x.open_branch().base)
