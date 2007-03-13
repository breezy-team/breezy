# Copyright (C) 2006, 2007 Canonical Ltd
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


from bzrlib import (
    branch,
    bzrdir,
    errors,
    tag,
    )
from bzrlib.tag import (
    BasicTags,
    _merge_tags_if_possible,
    )
from bzrlib.tests import (
    TestCase,
    TestCaseWithTransport,
    )


class TestTagSerialization(TestCase):

    def test_tag_serialization(self):
        """Test the precise representation of tag dicts."""
        # Don't change this after we commit to this format, as it checks 
        # that the format is stable and compatible across releases.
        #
        # This release stores them in bencode as a dictionary from name to
        # target.
        store = BasicTags(branch=None)
        td = dict(stable='stable-revid', boring='boring-revid')
        packed = store._serialize_tag_dict(td)
        expected = r'd6:boring12:boring-revid6:stable12:stable-revide'
        self.assertEqualDiff(packed, expected)
        self.assertEqual(store._deserialize_tag_dict(packed), td)


class TestTagMerging(TestCaseWithTransport):

    def make_knit_branch(self, relpath):
        old_bdf = bzrdir.format_registry.make_bzrdir('knit')
        return bzrdir.BzrDir.create_branch_convenience(relpath, format=old_bdf)

    def make_branch_supporting_tags(self, relpath):
        return self.make_branch(relpath, format='dirstate-with-subtree')

    def test_merge_not_possible(self):
        # test merging between branches which do and don't support tags
        old_branch = self.make_knit_branch('old')
        new_branch = self.make_branch_supporting_tags('new')
        # just to make sure this test is valid
        self.assertFalse(old_branch.supports_tags(),
            "%s is expected to not support tags but does" % old_branch)
        self.assertTrue(new_branch.supports_tags(),
            "%s is expected to support tags but does not" % new_branch)
        # there are no tags in the old one, and we can merge from it into the
        # new one
        old_branch.tags.merge_to(new_branch.tags)
        # we couldn't merge tags from the new branch to the old one, but as
        # there are not any yet this isn't a problem
        new_branch.tags.merge_to(old_branch.tags)
        # but if there is a tag in the new one, we get a warning when trying
        # to move it back
        new_branch.tags.set_tag(u'\u2040tag', 'revid')
        old_branch.tags.merge_to(new_branch.tags)
        self.assertRaises(errors.TagsNotSupported,
            new_branch.tags.merge_to, old_branch.tags)
