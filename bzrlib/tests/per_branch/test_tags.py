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

"""Tags stored within a branch

The tags are actually in the Branch.tags namespace, but these are
1:1 with Branch implementations so can be tested from here.
"""

from bzrlib import (
    branch,
    bzrdir,
    errors,
    repository,
    tests,
    )
from bzrlib.tests import per_branch


class TestBranchTags(per_branch.TestCaseWithBranch):

    def setUp(self):
        super(TestBranchTags, self).setUp()
        # formats that don't support tags can skip the rest of these
        # tests...
        branch = self.make_branch('probe')
        if not branch._format.supports_tags():
            raise tests.TestSkipped(
                "format %s doesn't support tags" % branch._format)

    def test_tags_initially_empty(self):
        b = self.make_branch('b')
        tags = b.tags.get_tag_dict()
        self.assertEqual(tags, {})

    def test_make_and_lookup_tag(self):
        b = self.make_branch('b')
        b.tags.set_tag('tag-name', 'target-revid-1')
        b.tags.set_tag('other-name', 'target-revid-2')
        # then reopen the branch and see they're still there
        b = branch.Branch.open('b')
        self.assertEqual(b.tags.get_tag_dict(),
            {'tag-name': 'target-revid-1',
             'other-name': 'target-revid-2',
            })
        # read one at a time
        result = b.tags.lookup_tag('tag-name')
        self.assertEqual(result, 'target-revid-1')
        # and try has_tag
        self.assertTrue(b.tags.has_tag('tag-name'))
        self.assertFalse(b.tags.has_tag('imaginary'))

    def test_reverse_tag_dict(self):
        b = self.make_branch('b')
        b.tags.set_tag('tag-name', 'target-revid-1')
        b.tags.set_tag('other-name', 'target-revid-2')
        # then reopen the branch and check reverse map id->tags list
        b = branch.Branch.open('b')
        self.assertEqual(b.tags.get_reverse_tag_dict(),
            {'target-revid-1': ['tag-name'],
             'target-revid-2': ['other-name'],
            })

    def test_no_such_tag(self):
        b = self.make_branch('b')
        try:
            b.tags.lookup_tag('bosko')
        except errors.NoSuchTag, e:
            self.assertEquals(e.tag_name, 'bosko')
            self.assertEquals(str(e), 'No such tag: bosko')
        else:
            self.fail("didn't get expected exception")

    def test_merge_tags(self):
        b1 = self.make_branch('b1')
        b2 = self.make_branch('b2')
        # if there are tags in the source and not the destination, then they
        # just go across
        b1.tags.set_tag('tagname', 'revid')
        b1.tags.merge_to(b2.tags)
        self.assertEquals(b2.tags.lookup_tag('tagname'), 'revid')
        # if a tag is in the destination and not in the source, it is not
        # removed when we merge them
        b2.tags.set_tag('in-destination', 'revid')
        result = b1.tags.merge_to(b2.tags)
        self.assertEquals(result, [])
        self.assertEquals(b2.tags.lookup_tag('in-destination'), 'revid')
        # if there's a conflicting tag, it's reported -- the command line
        # interface will say "these tags couldn't be copied"
        b1.tags.set_tag('conflicts', 'revid-1')
        b2.tags.set_tag('conflicts', 'revid-2')
        result = b1.tags.merge_to(b2.tags)
        self.assertEquals(result,
            [('conflicts', 'revid-1', 'revid-2')])
        # and it keeps the same value
        self.assertEquals(b2.tags.lookup_tag('conflicts'), 'revid-2')


    def test_unicode_tag(self):
        b1 = self.make_branch('b')
        tag_name = u'\u3070'
        # in anticipation of the planned change to treating revision ids as
        # just 8bit strings
        revid = ('revid' + tag_name).encode('utf-8')
        b1.tags.set_tag(tag_name, revid)
        self.assertEquals(b1.tags.lookup_tag(tag_name), revid)

    def test_delete_tag(self):
        b = self.make_branch('b')
        tag_name = u'\N{GREEK SMALL LETTER ALPHA}'
        revid = ('revid' + tag_name).encode('utf-8')
        b.tags.set_tag(tag_name, revid)
        # now try to delete it
        b.tags.delete_tag(tag_name)
        # now you can't look it up
        self.assertRaises(errors.NoSuchTag,
            b.tags.lookup_tag, tag_name)
        # and it's not in the dictionary
        self.assertEquals(b.tags.get_tag_dict(), {})
        # and you can't remove it a second time
        self.assertRaises(errors.NoSuchTag,
            b.tags.delete_tag, tag_name)
        # or remove a tag that never existed
        self.assertRaises(errors.NoSuchTag,
            b.tags.delete_tag, tag_name + '2')

    def test_merge_empty_tags(self):
        # you can merge tags between two instances, since neither have tags
        b1 = self.make_branch('b1')
        b2 = self.make_branch('b2')
        b1.tags.merge_to(b2.tags)


class TestTagsMergeToInCheckouts(per_branch.TestCaseWithBranch):
    """Tests for checkout.branch.tags.merge_to.
    
    In particular this exercises variations in tag conflicts in the master
    branch and/or the checkout (child).  It's unusual to have different tags in
    the child and master (they child is supposed to synchronised to the
    master, and e.g. 'bzr update' will unconditionally overwrite the child
    tags), but it can happen as merge_to in bzr < 2.2.2 didn't propagate
    changes to the master.  Current bzr versions may find themselves operating
    on checkouts touched by older bzrs, so we make sure bzr copes gracefully
    with this surprising situation.

    See also <https://bugs.launchpad.net/bzr/+bug/603395>.
    """

    def setUp(self):
        super(TestTagsMergeToInCheckouts, self).setUp()
        branch1 = self.make_branch('tags-probe')
        if not branch1._format.supports_tags():
            raise tests.TestSkipped(
                "format %s doesn't support tags" % branch1._format)
        branch2 = self.make_branch('bind-probe')
        try:
            branch2.bind(branch1)
        except errors.UpgradeRequired:
            raise tests.TestNotApplicable(
                "format %s doesn't support bound branches" % branch2._format)

    def test_merge_to_propagates_tags(self):
        """merge_to(child) also merges tags to the master."""
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

    def test_merge_to_same_conflict_in_master_and_child(self):
        """When new_tags.merge_to(child.tags) conflicts the same way with the
        master and the child a single conflict is reported.
        """
        master = self.make_branch('master')
        master.tags.set_tag('foo', 'rev-2')
        other = self.make_branch('other')
        other.tags.set_tag('foo', 'rev-1')
        child = self.make_branch('child')
        child.bind(master)
        child.update()
        tag_conflicts = other.tags.merge_to(child.tags)
        # Both master and child conflict, so both stay as rev-2
        self.assertEquals('rev-2', child.tags.lookup_tag('foo'))
        self.assertEquals('rev-2', master.tags.lookup_tag('foo'))
        # The conflict is reported exactly once, even though it occurs in both
        # master and child.
        self.assertEquals([(u'foo', 'rev-1', 'rev-2')], tag_conflicts)

    def test_merge_to_different_conflict_in_master_and_child(self):
        """When new_tags.merge_to(child.tags) conflicts differently in the
        master and the child both conflicts are reported.
        """
        master = self.make_branch('master')
        master.tags.set_tag('foo', 'rev-2')
        other = self.make_branch('other')
        other.tags.set_tag('foo', 'rev-1')
        child = self.make_branch('child')
        child.bind(master)
        child.update()
        # We need to use the private method _set_tag_dict because normally bzr
        # tries to prevent this scenario.
        child.tags._set_tag_dict({'foo': 'rev-3'})
        tag_conflicts = other.tags.merge_to(child.tags)
        # Both master and child conflict, so both stay as they were.
        self.assertEquals('rev-3', child.tags.lookup_tag('foo'))
        self.assertEquals('rev-2', master.tags.lookup_tag('foo'))
        # Both conflicts are reported.
        self.assertEquals(
            [(u'foo', 'rev-1', 'rev-2'), (u'foo', 'rev-1', 'rev-3')],
            sorted(tag_conflicts))


class TestUnsupportedTags(per_branch.TestCaseWithBranch):
    """Formats that don't support tags should give reasonable errors."""

    def setUp(self):
        super(TestUnsupportedTags, self).setUp()
        branch = self.make_branch('probe')
        if branch._format.supports_tags():
            raise tests.TestSkipped("Format %s declares that tags are supported"
                                    % branch._format)
            # it's covered by TestBranchTags

    def test_tag_methods_raise(self):
        b = self.make_branch('b')
        self.assertRaises(errors.TagsNotSupported,
            b.tags.set_tag, 'foo', 'bar')
        self.assertRaises(errors.TagsNotSupported,
            b.tags.lookup_tag, 'foo')
        self.assertRaises(errors.TagsNotSupported,
            b.tags.set_tag, 'foo', 'bar')
        self.assertRaises(errors.TagsNotSupported,
            b.tags.delete_tag, 'foo')

    def test_merge_empty_tags(self):
        # you can merge tags between two instances, since neither have tags
        b1 = self.make_branch('b1')
        b2 = self.make_branch('b2')
        b1.tags.merge_to(b2.tags)


class AutomaticTagNameTests(per_branch.TestCaseWithBranch):

    def setUp(self):
        super(AutomaticTagNameTests, self).setUp()
        if isinstance(self.branch_format, branch.BranchReferenceFormat):
            # This test could in principle apply to BranchReferenceFormat, but
            # make_branch_builder doesn't support it.
            raise tests.TestSkipped(
                "BranchBuilder can't make reference branches.")
        self.builder = self.make_branch_builder('.')
        self.builder.build_snapshot('foo', None,
            [('add', ('', None, 'directory', None))],
            message='foo')
        self.branch = self.builder.get_branch()
        if not self.branch._format.supports_tags():
            raise tests.TestSkipped(
                "format %s doesn't support tags" % self.branch._format)

    def test_no_functions(self):
        rev = self.branch.last_revision()
        self.assertEquals(None, self.branch.automatic_tag_name(rev))

    def test_returns_tag_name(self):
        def get_tag_name(br, revid):
            return "foo"
        branch.Branch.hooks.install_named_hook('automatic_tag_name',
            get_tag_name, 'get tag name foo')
        self.assertEquals("foo", self.branch.automatic_tag_name(
            self.branch.last_revision()))
    
    def test_uses_first_return(self):
        get_tag_name_1 = lambda br, revid: "foo1"
        get_tag_name_2 = lambda br, revid: "foo2"
        branch.Branch.hooks.install_named_hook('automatic_tag_name',
            get_tag_name_1, 'tagname1')
        branch.Branch.hooks.install_named_hook('automatic_tag_name',
            get_tag_name_2, 'tagname2')
        self.assertEquals("foo1", self.branch.automatic_tag_name(
            self.branch.last_revision()))

    def test_ignores_none(self):
        get_tag_name_1 = lambda br, revid: None
        get_tag_name_2 = lambda br, revid: "foo2"
        branch.Branch.hooks.install_named_hook('automatic_tag_name',
            get_tag_name_1, 'tagname1')
        branch.Branch.hooks.install_named_hook('automatic_tag_name',
            get_tag_name_2, 'tagname2')
        self.assertEquals("foo2", self.branch.automatic_tag_name(
            self.branch.last_revision()))
