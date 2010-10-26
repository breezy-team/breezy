# Copyright (C) 2007, 2009, 2010 Canonical Ltd
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

"""Tests for bzrlib.tag."""


from bzrlib import (
    bzrdir,
    errors,
    )
from bzrlib.tag import (
    BasicTags,
    DisabledTags,
    )
from bzrlib.tests import (
    KnownFailure,
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


class TestTagRevisionRenames(TestCaseWithTransport):

    def make_branch_supporting_tags(self, relpath):
        return self.make_branch(relpath, format='dirstate-tags')

    def test_simple(self):
        store = self.make_branch_supporting_tags('a').tags
        store.set_tag("foo", "myoldrevid")
        store.rename_revisions({"myoldrevid": "mynewrevid"})
        self.assertEquals({"foo": "mynewrevid"}, store.get_tag_dict())

    def test_unknown_ignored(self):
        store = self.make_branch_supporting_tags('a').tags
        store.set_tag("foo", "myoldrevid")
        store.rename_revisions({"anotherrevid": "mynewrevid"})
        self.assertEquals({"foo": "myoldrevid"}, store.get_tag_dict())


class TestTagMerging(TestCaseWithTransport):

    def make_knit_branch(self, relpath):
        old_bdf = bzrdir.format_registry.make_bzrdir('knit')
        return bzrdir.BzrDir.create_branch_convenience(relpath, format=old_bdf)

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
        new_branch.tags.set_tag(u'\u2040tag', 'revid')
        old_branch.tags.merge_to(new_branch.tags)
        self.assertRaises(errors.TagsNotSupported,
            new_branch.tags.merge_to, old_branch.tags)

    def test_merge_to(self):
        a = self.make_branch_supporting_tags('a')
        b = self.make_branch_supporting_tags('b')
        # simple merge
        a.tags.set_tag('tag-1', 'x')
        b.tags.set_tag('tag-2', 'y')
        a.tags.merge_to(b.tags)
        self.assertEqual('x', b.tags.lookup_tag('tag-1'))
        self.assertEqual('y', b.tags.lookup_tag('tag-2'))
        self.assertRaises(errors.NoSuchTag, a.tags.lookup_tag, 'tag-2')
        # conflicting merge
        a.tags.set_tag('tag-2', 'z')
        conflicts = a.tags.merge_to(b.tags)
        self.assertEqual(conflicts, [('tag-2', 'z', 'y')])
        self.assertEqual('y', b.tags.lookup_tag('tag-2'))
        # overwrite conflicts
        conflicts = a.tags.merge_to(b.tags, overwrite=True)
        self.assertEqual(conflicts, [])
        self.assertEqual('z', b.tags.lookup_tag('tag-2'))


class TestTagsInCheckouts(TestCaseWithTransport):
    """Tests for how tags are synchronised between the master and child branch
    of a checkout.

    Note that it is possible (although a bit uncommon) for the master and child
    to have different sets of tags.  So this includes tests for those cases to
    make sure the behaviour in those situations is well-defined.
    """

    def test_update_tag_into_checkout(self):
        # checkouts are directly connected to the tags of their master branch:
        # adding a tag in the checkout pushes it to the master
        # https://bugs.launchpad.net/bzr/+bug/93860
        master = self.make_branch('master')
        child = self.make_branch('child')
        child.bind(master)
        child.tags.set_tag('foo', 'rev-1')
        self.assertEquals('rev-1', master.tags.lookup_tag('foo'))
        # deleting a tag updates the master too
        child.tags.delete_tag('foo')
        self.assertRaises(errors.NoSuchTag,
            master.tags.lookup_tag, 'foo')

    def test_tag_copied_by_initial_checkout(self):
        # https://bugs.launchpad.net/bzr/+bug/93860
        master = self.make_branch('master')
        master.tags.set_tag('foo', 'rev-1')
        co_tree = master.create_checkout('checkout')
        self.assertEquals('rev-1',
            co_tree.branch.tags.lookup_tag('foo'))

    def test_update_updates_tags(self):
        # https://bugs.launchpad.net/bzr/+bug/93856
        master = self.make_branch('master')
        master.tags.set_tag('foo', 'rev-1')
        child = self.make_branch('child')
        child.bind(master)
        child.update()
        # after an update, the child has all the master's tags
        self.assertEquals('rev-1', child.tags.lookup_tag('foo'))
        # add another tag and update again
        master.tags.set_tag('tag2', 'target2')
        child.update()
        self.assertEquals('target2', child.tags.lookup_tag('tag2'))

    def test_merge_to_propagates_tags(self):
        """merge_to(child) also merges tags to the master.
        
        https://bugs.launchpad.net/bzr/+bug/603395
        """
        master = self.make_branch('master')
        other = self.make_branch('other')
        other.tags.set_tag('foo', 'rev-1')
        child = self.make_branch('child')
        child.bind(master)
        child.update()
        other.tags.merge_to(child.tags)
        self.assertEquals('rev-1', child.tags.lookup_tag('foo'))
        self.assertEquals('rev-1', master.tags.lookup_tag('foo'))

    def test_merge_to_overwrite_conflict_in_master(self):
        """merge_to(child, overwrite=True) overwrites any conflicting tags in
        the master.
        
        https://bugs.launchpad.net/bzr/+bug/603395
        """
        master = self.make_branch('master')
        other = self.make_branch('other')
        other.tags.set_tag('foo', 'rev-1')
        child = self.make_branch('child')
        child.bind(master)
        child.update()
        master.tags.set_tag('foo', 'rev-2')
        tag_conflicts = other.tags.merge_to(child.tags, overwrite=True)
        self.assertEquals('rev-1', child.tags.lookup_tag('foo'))
        self.assertEquals('rev-1', master.tags.lookup_tag('foo'))
        self.assertLength(0, tag_conflicts)

    def test_merge_to_overwrite_conflict_in_child_and_master(self):
        """merge_to(child, overwrite=True) overwrites any conflicting tags in
        both the child and the master.
        
        https://bugs.launchpad.net/bzr/+bug/603395
        """
        master = self.make_branch('master')
        master.tags.set_tag('foo', 'rev-2')
        other = self.make_branch('other')
        other.tags.set_tag('foo', 'rev-1')
        child = self.make_branch('child')
        child.bind(master)
        child.update()
        tag_conflicts = other.tags.merge_to(child.tags, overwrite=True)
        self.assertEquals('rev-1', child.tags.lookup_tag('foo'))
        self.assertEquals('rev-1', master.tags.lookup_tag('foo'))
        self.assertLength(0, tag_conflicts)

    def test_merge_to_conflict_in_child_only(self):
        """When new_tags.merge_to(child.tags) conflicts with the child but not
        the master, a conflict is reported and the child receives the new tag.
        
        https://bugs.launchpad.net/bzr/+bug/603395
        """
        master = self.make_branch('master')
        master.tags.set_tag('foo', 'rev-2')
        other = self.make_branch('other')
        other.tags.set_tag('foo', 'rev-1')
        child = self.make_branch('child')
        child.bind(master)
        child.update()
        master.tags.delete_tag('foo')
        tag_conflicts = other.tags.merge_to(child.tags)
        # Conflict in child, so it is unchanged.
        self.assertEquals('rev-2', child.tags.lookup_tag('foo'))
        # No conflict in the master, so the 'foo' tag equals other's value here.
        self.assertEquals('rev-1', master.tags.lookup_tag('foo'))
        # The conflict is reported.
        self.assertEquals([(u'foo', 'rev-1', 'rev-2')], tag_conflicts)

    def test_merge_to_conflict_in_master_only(self):
        """When new_tags.merge_to(child.tags) conflicts with the master but not
        the child, a conflict is reported and the child receives the new tag.
        
        https://bugs.launchpad.net/bzr/+bug/603395
        """
        master = self.make_branch('master')
        other = self.make_branch('other')
        other.tags.set_tag('foo', 'rev-1')
        child = self.make_branch('child')
        child.bind(master)
        child.update()
        master.tags.set_tag('foo', 'rev-2')
        tag_conflicts = other.tags.merge_to(child.tags)
        # No conflict in the child, so the 'foo' tag equals other's value here.
        self.assertEquals('rev-1', child.tags.lookup_tag('foo'))
        # Conflict in master, so it is unchanged.
        self.assertEquals('rev-2', master.tags.lookup_tag('foo'))
        # The conflict is reported.
        self.assertEquals([(u'foo', 'rev-1', 'rev-2')], tag_conflicts)

    def test_tag_deletion_from_master_to_bound(self):
        master = self.make_branch('master')
        master.tags.set_tag('foo', 'rev-1')
        child = self.make_branch('child')
        child.bind(master)
        child.update()
        # and deletion of tags should also propagate
        master.tags.delete_tag('foo')
        raise KnownFailure("tag deletion does not propagate: "
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



