# Copyright (C) 2007, 2009-2012, 2016 Canonical Ltd
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

"""Tests for breezy.tag."""


from breezy import (
    controldir,
    errors,
    )
from breezy.tag import (
    BasicTags,
    DisabledTags,
    )
from breezy.tests import (
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
        td = dict(stable=b'stable-revid', boring=b'boring-revid')
        packed = store._serialize_tag_dict(td)
        expected = br'd6:boring12:boring-revid6:stable12:stable-revide'
        self.assertEqualDiff(packed, expected)
        self.assertEqual(store._deserialize_tag_dict(packed), td)


class TestTagRevisionRenames(TestCaseWithTransport):

    def make_branch_supporting_tags(self, relpath):
        return self.make_branch(relpath, format='dirstate-tags')

    def test_simple(self):
        store = self.make_branch_supporting_tags('a').tags
        store.set_tag("foo", b"myoldrevid")
        store.rename_revisions({b"myoldrevid": b"mynewrevid"})
        self.assertEqual({"foo": b"mynewrevid"}, store.get_tag_dict())

    def test_unknown_ignored(self):
        store = self.make_branch_supporting_tags('a').tags
        store.set_tag("foo", b"myoldrevid")
        store.rename_revisions({b"anotherrevid": b"mynewrevid"})
        self.assertEqual({"foo": b"myoldrevid"}, store.get_tag_dict())


class TestTagMerging(TestCaseWithTransport):

    def make_knit_branch(self, relpath):
        old_bdf = controldir.format_registry.make_controldir('knit')
        return controldir.ControlDir.create_branch_convenience(relpath, format=old_bdf)

    def make_branch_supporting_tags(self, relpath):
        return self.make_branch(relpath, format='dirstate-tags')

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
        new_branch.tags.set_tag(u'\u2040tag', b'revid')
        old_branch.tags.merge_to(new_branch.tags)
        self.assertRaises(errors.TagsNotSupported,
                          new_branch.tags.merge_to, old_branch.tags)

    def test_merge_to(self):
        a = self.make_branch_supporting_tags('a')
        b = self.make_branch_supporting_tags('b')
        # simple merge
        a.tags.set_tag('tag-1', b'x')
        b.tags.set_tag('tag-2', b'y')
        a.tags.merge_to(b.tags)
        self.assertEqual(b'x', b.tags.lookup_tag('tag-1'))
        self.assertEqual(b'y', b.tags.lookup_tag('tag-2'))
        self.assertRaises(errors.NoSuchTag, a.tags.lookup_tag, 'tag-2')
        # conflicting merge
        a.tags.set_tag('tag-2', b'z')
        updates, conflicts = a.tags.merge_to(b.tags)
        self.assertEqual({}, updates)
        self.assertEqual(list(conflicts), [('tag-2', b'z', b'y')])
        self.assertEqual(b'y', b.tags.lookup_tag('tag-2'))
        # overwrite conflicts
        updates, conflicts = a.tags.merge_to(b.tags, overwrite=True)
        self.assertEqual(list(conflicts), [])
        self.assertEqual({u'tag-2': b'z'}, updates)
        self.assertEqual(b'z', b.tags.lookup_tag('tag-2'))


class TestTagsInCheckouts(TestCaseWithTransport):
    """Tests for how tags are synchronised between the master and child branch
    of a checkout.
    """

    def test_update_tag_into_checkout(self):
        # checkouts are directly connected to the tags of their master branch:
        # adding a tag in the checkout pushes it to the master
        # https://bugs.launchpad.net/bzr/+bug/93860
        master = self.make_branch('master')
        child = self.make_branch('child')
        child.bind(master)
        child.tags.set_tag('foo', b'rev-1')
        self.assertEqual(b'rev-1', master.tags.lookup_tag('foo'))
        # deleting a tag updates the master too
        child.tags.delete_tag('foo')
        self.assertRaises(errors.NoSuchTag,
                          master.tags.lookup_tag, 'foo')

    def test_tag_copied_by_initial_checkout(self):
        # https://bugs.launchpad.net/bzr/+bug/93860
        master = self.make_branch('master')
        master.tags.set_tag('foo', b'rev-1')
        co_tree = master.create_checkout('checkout')
        self.assertEqual(b'rev-1',
                         co_tree.branch.tags.lookup_tag('foo'))

    def test_update_updates_tags(self):
        # https://bugs.launchpad.net/bzr/+bug/93856
        master = self.make_branch('master')
        master.tags.set_tag('foo', b'rev-1')
        child = self.make_branch('child')
        child.bind(master)
        child.update()
        # after an update, the child has all the master's tags
        self.assertEqual(b'rev-1', child.tags.lookup_tag('foo'))
        # add another tag and update again
        master.tags.set_tag('tag2', b'target2')
        child.update()
        self.assertEqual(b'target2', child.tags.lookup_tag('tag2'))

    def test_tag_deletion_from_master_to_bound(self):
        master = self.make_branch('master')
        master.tags.set_tag('foo', b'rev-1')
        child = self.make_branch('child')
        child.bind(master)
        child.update()
        # and deletion of tags should also propagate
        master.tags.delete_tag('foo')
        self.knownFailure("tag deletion does not propagate: "
                          "https://bugs.launchpad.net/bzr/+bug/138802")
        self.assertRaises(errors.NoSuchTag,
                          child.tags.lookup_tag, 'foo')


class DisabledTagsTests(TestCaseWithTransport):

    def setUp(self):
        super(DisabledTagsTests, self).setUp()
        branch = self.make_branch('.')
        self.tags = DisabledTags(branch)

    def test_set_tag(self):
        self.assertRaises(errors.TagsNotSupported, self.tags.set_tag)

    def test_get_reverse_tag_dict(self):
        self.assertEqual(self.tags.get_reverse_tag_dict(), {})
