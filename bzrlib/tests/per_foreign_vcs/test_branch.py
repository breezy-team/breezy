# Copyright (C) 2009 Canonical Ltd
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


"""Tests specific to Branch implementations that use foreign VCS'es."""


from bzrlib.errors import (
    UnstackableBranchFormat,
    )
from bzrlib.revision import (
    NULL_REVISION,
    )


class ForeignBranchTests(object):
    """Basic tests for foreign branch implementations.
    
    These tests mainly make sure that the implementation covers the required 
    bits of the API and returns reasonable values. 
    """
    branch = None # Set to a ForeignBranch instance by adapter

    def test_set_parent(self):
        """Test that setting the parent works."""
        self.branch.set_parent("foobar")

    def test_break_lock(self):
        """Test that break_lock() works, even if it is a no-op."""
        self.branch.break_lock()

    def test_set_push_location(self):
        """Test that setting the push location works."""
        self.branch.set_push_location("http://bar/bloe")

    def test_repr_type(self):
        self.assertIsInstance(repr(self.branch), str)

    def test_get_parent(self):
        """Test that getting the parent location works, and returns None."""
        # TODO: Allow this to be non-None when foreign branches add support 
        #       for storing this URL.
        self.assertIs(None, self.branch.get_parent())

    def test_get_push_location(self):
        """Test that getting the push location works, and returns None."""
        # TODO: Allow this to be non-None when foreign branches add support 
        #       for storing this URL.
        self.assertIs(None, self.branch.get_push_location())

    def test_check(self):
        """See if a basic check works."""
        result = self.branch.check()
        self.assertEqual(self.branch, result.branch) 

    def test_attributes(self):
        """Check that various required attributes are present."""
        self.assertIsNot(None, getattr(self.branch, "repository", None))
        self.assertIsNot(None, getattr(self.branch, "mapping", None))
        self.assertIsNot(None, getattr(self.branch, "_format", None))
        self.assertIsNot(None, getattr(self.branch, "base", None))

    def test__get_nick(self):
        """Make sure _get_nick is implemented and returns a string."""
        self.assertIsInstance(self.branch._get_nick(local=False), str)
        self.assertIsInstance(self.branch._get_nick(local=True), str)

    def test_null_revid_revno(self):
        """null: should return revno 0."""
        self.assertEquals(0, self.branch.revision_id_to_revno(NULL_REVISION))

    def test_get_stacked_on_url(self):
        """Test that get_stacked_on_url() behaves as expected.

        Inter-Format stacking doesn't work yet, so all foreign implementations
        should raise UnstackableBranchFormat at the moment.
        """
        self.assertRaises(UnstackableBranchFormat, 
                          self.branch.get_stacked_on_url)

    def test_get_physical_lock_status(self):
        self.assertFalse(self.branch.get_physical_lock_status())

    def test_last_revision(self):
        (revno, revid) = self.branch.last_revision_info()
        self.assertIsInstance(revno, int)
        self.assertIsInstance(revid, str)
        self.assertEquals(revno, self.branch.revision_id_to_revno(revid))
        self.assertEquals(revid, self.branch.last_revision())


class ForeignBranchFormatTests(object):
    """Basic tests for foreign branch format objects."""
    format = None # Set to a BranchFormat instance by adapter

    def test_initialize(self):
        """Test this format is not initializable.
        
        Remote branches may be initializable on their own, but none currently
        support living in .bzr/branch.
        """
        self.assertRaises(NotImplementedError, self.format.initialize, None)

    def test_get_format_description_type(self):
        self.assertIsInstance(self.format.get_format_description(), str)

    def test_network_name(self):
        self.assertIsInstance(self.format.network_name(), str)


