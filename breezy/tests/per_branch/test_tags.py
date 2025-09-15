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

"""Tags stored within a branch.

The tags are actually in the Branch.tags namespace, but these are
1:1 with Branch implementations so can be tested from here.
"""

from breezy import branch, controldir, errors, tests
from breezy.bzr import branch as bzrbranch
from breezy.tests import per_branch


class TestBranchTags(per_branch.TestCaseWithBranch):
    def setUp(self):
        super().setUp()
        # formats that don't support tags can skip the rest of these
        # tests...
        branch = self.make_branch("probe")
        if not branch._format.supports_tags():
            raise tests.TestSkipped(f"format {branch._format} doesn't support tags")

    def make_branch_with_revisions(self, relpath, revisions):
        builder = self.make_branch_builder(relpath)
        builder.start_series()
        for revid in revisions:
            builder.build_commit(rev_id=revid)
        builder.finish_series()
        return builder.get_branch()

    def make_branch_with_revision_tuple(self, relpath, count):
        builder = self.make_branch_builder(relpath)
        builder.start_series()
        revids = [builder.build_commit() for i in range(count)]
        builder.finish_series()
        return builder.get_branch(), revids

    def test_tags_initially_empty(self):
        b = self.make_branch("b")
        tags = b.tags.get_tag_dict()
        self.assertEqual(tags, {})

    def test_make_and_lookup_tag(self):
        b, [target_revid1, target_revid2] = self.make_branch_with_revision_tuple("b", 2)
        b.tags.set_tag("tag-name", target_revid1)
        b.tags.set_tag("other-name", target_revid2)
        # then reopen the branch and see they're still there
        b = branch.Branch.open("b")
        self.assertEqual(
            b.tags.get_tag_dict(),
            {
                "tag-name": target_revid1,
                "other-name": target_revid2,
            },
        )
        # read one at a time
        result = b.tags.lookup_tag("tag-name")
        self.assertEqual(result, target_revid1)
        # and try has_tag
        self.assertTrue(b.tags.has_tag("tag-name"))
        self.assertFalse(b.tags.has_tag("imaginary"))

    def test_reverse_tag_dict(self):
        b, [target_revid1, target_revid2] = self.make_branch_with_revision_tuple("b", 2)
        b.tags.set_tag("tag-name", target_revid1)
        b.tags.set_tag("other-name", target_revid2)
        # then reopen the branch and check reverse map id->tags list
        b = branch.Branch.open("b")
        self.assertEqual(
            dict(b.tags.get_reverse_tag_dict()),
            {
                target_revid1: {"tag-name"},
                target_revid2: {"other-name"},
            },
        )

    def test_ghost_tag(self):
        b = self.make_branch("b")
        if not b._format.supports_tags_referencing_ghosts():
            self.assertRaises(
                errors.GhostTagsNotSupported, b.tags.set_tag, "ghost", b"idontexist"
            )
        else:
            b.tags.set_tag("ghost", b"idontexist")
            self.assertEqual(b"idontexist", b.tags.lookup_tag("ghost"))

    def test_no_such_tag(self):
        b = self.make_branch("b")
        try:
            b.tags.lookup_tag("bosko")
        except errors.NoSuchTag as e:
            self.assertEqual(e.tag_name, "bosko")
            self.assertEqual(str(e), "No such tag: bosko")
        else:
            self.fail("didn't get expected exception")

    def test_merge_tags(self):
        b1, [revid, revid1] = self.make_branch_with_revision_tuple("b1", 2)
        w2 = b1.controldir.sprout("b2", revision_id=revid).open_workingtree()
        revid2 = w2.commit("revision 2")
        b2 = w2.branch
        # if there are tags in the source and not the destination, then they
        # just go across
        b1.tags.set_tag("tagname", revid)
        b1.tags.merge_to(b2.tags)
        self.assertEqual(b2.tags.lookup_tag("tagname"), revid)
        # if a tag is in the destination and not in the source, it is not
        # removed when we merge them
        b2.tags.set_tag("in-destination", revid)
        updates, conflicts = b1.tags.merge_to(b2.tags)
        self.assertEqual(list(conflicts), [])
        self.assertEqual(updates, {})
        self.assertEqual(b2.tags.lookup_tag("in-destination"), revid)
        # if there's a conflicting tag, it's reported -- the command line
        # interface will say "these tags couldn't be copied"
        b1.tags.set_tag("conflicts", revid1)
        b2.tags.set_tag("conflicts", revid2)
        updates, conflicts = b1.tags.merge_to(b2.tags)
        self.assertEqual(list(conflicts), [("conflicts", revid1, revid2)])
        # and it keeps the same value
        self.assertEqual(updates, {})
        self.assertEqual(b2.tags.lookup_tag("conflicts"), revid2)

    def test_merge_tags_selector(self):
        b1, [revid, _revid1] = self.make_branch_with_revision_tuple("b1", 2)
        w2 = b1.controldir.sprout("b2", revision_id=revid).open_workingtree()
        revid2 = w2.commit("revision 2")
        b2 = w2.branch
        # if there are tags in the source and not the destination, then they
        # just go across
        b1.tags.set_tag("tag1", revid)
        b1.tags.set_tag("tag2", revid2)
        updates, conflicts = b1.tags.merge_to(b2.tags, selector=lambda x: x == "tag1")
        self.assertEqual({"tag1": revid}, updates)
        self.assertEqual(set(), set(conflicts))
        self.assertEqual(b2.tags.lookup_tag("tag1"), revid)
        self.assertRaises(errors.NoSuchTag, b2.tags.lookup_tag, "tag2")

    def test_unicode_tag(self):
        tag_name = "\u3070"
        b1, [revid] = self.make_branch_with_revision_tuple("b", 1)
        b1.tags.set_tag(tag_name, revid)
        self.assertEqual(b1.tags.lookup_tag(tag_name), revid)

    def test_delete_tag(self):
        tag_name = "\N{GREEK SMALL LETTER ALPHA}"
        b, [revid] = self.make_branch_with_revision_tuple("b", 1)
        b.tags.set_tag(tag_name, revid)
        # now try to delete it
        b.tags.delete_tag(tag_name)
        # now you can't look it up
        self.assertRaises(errors.NoSuchTag, b.tags.lookup_tag, tag_name)
        # and it's not in the dictionary
        self.assertEqual(b.tags.get_tag_dict(), {})
        # and you can't remove it a second time
        self.assertRaises(errors.NoSuchTag, b.tags.delete_tag, tag_name)
        # or remove a tag that never existed
        self.assertRaises(errors.NoSuchTag, b.tags.delete_tag, tag_name + "2")

    def test_merge_empty_tags(self):
        # you can merge tags between two instances, since neither have tags
        b1 = self.make_branch("b1")
        b2 = self.make_branch("b2")
        b1.tags.merge_to(b2.tags)

    def test_read_lock_caches_tags(self):
        """Tags are read from a branch only once during a read-lock."""
        # Open the same branch twice.  Read-lock one, and then mutate the tags
        # in the second.  The read-locked branch never re-reads the tags, so it
        # never observes the changed/new tags.
        b1, [rev1, rev2, rev3] = self.make_branch_with_revision_tuple("b", 3)
        b1.tags.set_tag("one", rev1)
        b2 = controldir.ControlDir.open("b").open_branch()
        b1.lock_read()
        self.assertEqual({"one": rev1}, b1.tags.get_tag_dict())
        # Add a tag and modify a tag in b2.  b1 is read-locked and has already
        # read the tags, so it is unaffected.
        b2.tags.set_tag("one", rev2)
        b2.tags.set_tag("two", rev3)
        self.assertEqual({"one": rev1}, b1.tags.get_tag_dict())
        b1.unlock()
        # Once unlocked the cached value is forgotten, so now the latest tags
        # will be retrieved.
        self.assertEqual({"one": rev2, "two": rev3}, b1.tags.get_tag_dict())

    def test_unlocked_does_not_cache_tags(self):
        """Unlocked branches do not cache tags."""
        # Open the same branch twice.
        b1, [rev1, rev2, rev3] = self.make_branch_with_revision_tuple("b", 3)
        b1.tags.set_tag("one", rev1)
        b2 = b1.controldir.open_branch()
        self.assertEqual({"one": rev1}, b1.tags.get_tag_dict())
        # Add a tag and modify a tag in b2.  b1 isn't locked, so it will
        # immediately return the new tags too.
        b2.tags.set_tag("one", rev2)
        b2.tags.set_tag("two", rev3)
        self.assertEqual({"one": rev2, "two": rev3}, b1.tags.get_tag_dict())

    def test_cached_tag_dict_not_accidentally_mutable(self):
        """When there's a cached version of the tags, b.tags.get_tag_dict
        returns a copy of the cached data so that callers cannot accidentally
        corrupt the cache.
        """
        b, [rev1, rev2, rev3] = self.make_branch_with_revision_tuple("b", 3)
        b.tags.set_tag("one", rev1)
        self.addCleanup(b.lock_read().unlock)
        # The first time the data returned will not be in the cache
        tags_dict = b.tags.get_tag_dict()
        tags_dict["two"] = rev2
        # The second time the data comes from the cache
        tags_dict = b.tags.get_tag_dict()
        tags_dict["three"] = rev3
        # The get_tag_dict() result should still be unchanged, even though we
        # mutated its earlier return values.
        self.assertEqual({"one": rev1}, b.tags.get_tag_dict())

    def make_write_locked_branch_with_one_tag(self):
        b, revids = self.make_branch_with_revision_tuple("b", 3)
        b.tags.set_tag("one", revids[0])
        self.addCleanup(b.lock_write().unlock)
        # Populate the cache
        b.tags.get_tag_dict()
        return b, revids

    def test_set_tag_invalides_cache(self):
        b, revids = self.make_write_locked_branch_with_one_tag()
        b.tags.set_tag("one", revids[1])
        self.assertEqual({"one": revids[1]}, b.tags.get_tag_dict())

    def test_delete_tag_invalides_cache(self):
        b, _revids = self.make_write_locked_branch_with_one_tag()
        b.tags.delete_tag("one")
        self.assertEqual({}, b.tags.get_tag_dict())

    def test_merge_to_invalides_cache(self):
        b1, revids = self.make_write_locked_branch_with_one_tag()
        b2 = b1.controldir.sprout("b2").open_branch()
        b2.tags.set_tag("two", revids[1])
        b2.tags.merge_to(b1.tags)
        self.assertEqual({"one": revids[0], "two": revids[1]}, b1.tags.get_tag_dict())

    def test_rename_revisions_invalides_cache(self):
        b, revids = self.make_write_locked_branch_with_one_tag()
        b.tags.rename_revisions({revids[0]: revids[1]})
        self.assertEqual({"one": revids[1]}, b.tags.get_tag_dict())


class TestTagsMergeToInCheckouts(per_branch.TestCaseWithBranch):
    """Tests for checkout.branch.tags.merge_to.

    In particular this exercises variations in tag conflicts in the master
    branch and/or the checkout (child).  It may seem strange to have different
    tags in the child and master, but 'bzr merge' intentionally updates the
    child and not the master (instead the next 'bzr commit', if the user
    decides to commit, will update the master).  Also, merge_to in bzr < 2.3
    didn't propagate changes to the master, and current bzr versions may find
    themselves operating on checkouts touched by older bzrs

    So we need to make sure bzr copes gracefully with differing tags in the
    master versus the child.

    See also <https://bugs.launchpad.net/bzr/+bug/603395>.
    """

    def setUp(self):
        super().setUp()
        branch1 = self.make_branch("tags-probe")
        if not branch1._format.supports_tags():
            raise tests.TestSkipped(f"format {branch1._format} doesn't support tags")
        branch2 = self.make_branch("bind-probe")
        try:
            branch2.bind(branch1)
        except branch.BindingUnsupported as e:
            raise tests.TestNotApplicable(
                f"format {branch2._format} doesn't support bound branches"
            ) from e

    def test_merge_to_propagates_tags(self):
        """merge_to(child) also merges tags to the master."""
        master = self.make_branch("master")
        other = self.make_branch("other")
        other.tags.set_tag("foo", b"rev-1")
        child = self.make_branch("child")
        child.bind(master)
        child.update()
        other.tags.merge_to(child.tags)
        self.assertEqual(b"rev-1", child.tags.lookup_tag("foo"))
        self.assertEqual(b"rev-1", master.tags.lookup_tag("foo"))

    def test_ignore_master_disables_tag_propagation(self):
        """merge_to(child, ignore_master=True) does not merge tags to the
        master.
        """
        master = self.make_branch("master")
        other = self.make_branch("other")
        other.tags.set_tag("foo", b"rev-1")
        child = self.make_branch("child")
        child.bind(master)
        child.update()
        other.tags.merge_to(child.tags, ignore_master=True)
        self.assertEqual(b"rev-1", child.tags.lookup_tag("foo"))
        self.assertRaises(errors.NoSuchTag, master.tags.lookup_tag, "foo")

    def test_merge_to_overwrite_conflict_in_master(self):
        """merge_to(child, overwrite=True) overwrites any conflicting tags in
        the master.
        """
        master = self.make_branch("master")
        other = self.make_branch("other")
        other.tags.set_tag("foo", b"rev-1")
        child = self.make_branch("child")
        child.bind(master)
        child.update()
        master.tags.set_tag("foo", b"rev-2")
        tag_updates, tag_conflicts = other.tags.merge_to(child.tags, overwrite=True)
        self.assertEqual(b"rev-1", child.tags.lookup_tag("foo"))
        self.assertEqual(b"rev-1", master.tags.lookup_tag("foo"))
        self.assertEqual({"foo": b"rev-1"}, tag_updates)
        self.assertLength(0, tag_conflicts)

    def test_merge_to_overwrite_conflict_in_child_and_master(self):
        """merge_to(child, overwrite=True) overwrites any conflicting tags in
        both the child and the master.
        """
        master = self.make_branch("master")
        master.tags.set_tag("foo", b"rev-2")
        other = self.make_branch("other")
        other.tags.set_tag("foo", b"rev-1")
        child = self.make_branch("child")
        child.bind(master)
        child.update()
        tag_updates, tag_conflicts = other.tags.merge_to(child.tags, overwrite=True)
        self.assertEqual(b"rev-1", child.tags.lookup_tag("foo"))
        self.assertEqual(b"rev-1", master.tags.lookup_tag("foo"))
        self.assertEqual({"foo": b"rev-1"}, tag_updates)
        self.assertLength(0, tag_conflicts)

    def test_merge_to_conflict_in_child_only(self):
        """When new_tags.merge_to(child.tags) conflicts with the child but not
        the master, a conflict is reported and the child receives the new tag.
        """
        master = self.make_branch("master")
        master.tags.set_tag("foo", b"rev-2")
        other = self.make_branch("other")
        other.tags.set_tag("foo", b"rev-1")
        child = self.make_branch("child")
        child.bind(master)
        child.update()
        master.tags.delete_tag("foo")
        tag_updates, tag_conflicts = other.tags.merge_to(child.tags)
        # Conflict in child, so it is unchanged.
        self.assertEqual(b"rev-2", child.tags.lookup_tag("foo"))
        # No conflict in the master, so the 'foo' tag equals other's value here.
        self.assertEqual(b"rev-1", master.tags.lookup_tag("foo"))
        # The conflict is reported.
        self.assertEqual([("foo", b"rev-1", b"rev-2")], list(tag_conflicts))
        self.assertEqual({"foo": b"rev-1"}, tag_updates)

    def test_merge_to_conflict_in_master_only(self):
        """When new_tags.merge_to(child.tags) conflicts with the master but not
        the child, a conflict is reported and the child receives the new tag.
        """
        master = self.make_branch("master")
        other = self.make_branch("other")
        other.tags.set_tag("foo", b"rev-1")
        child = self.make_branch("child")
        child.bind(master)
        child.update()
        master.tags.set_tag("foo", b"rev-2")
        tag_updates, tag_conflicts = other.tags.merge_to(child.tags)
        # No conflict in the child, so the 'foo' tag equals other's value here.
        self.assertEqual(b"rev-1", child.tags.lookup_tag("foo"))
        # Conflict in master, so it is unchanged.
        self.assertEqual(b"rev-2", master.tags.lookup_tag("foo"))
        # The conflict is reported.
        self.assertEqual({"foo": b"rev-1"}, tag_updates)
        self.assertEqual([("foo", b"rev-1", b"rev-2")], list(tag_conflicts))

    def test_merge_to_same_conflict_in_master_and_child(self):
        """When new_tags.merge_to(child.tags) conflicts the same way with the
        master and the child a single conflict is reported.
        """
        master = self.make_branch("master")
        master.tags.set_tag("foo", b"rev-2")
        other = self.make_branch("other")
        other.tags.set_tag("foo", b"rev-1")
        child = self.make_branch("child")
        child.bind(master)
        child.update()
        tag_updates, tag_conflicts = other.tags.merge_to(child.tags)
        # Both master and child conflict, so both stay as rev-2
        self.assertEqual(b"rev-2", child.tags.lookup_tag("foo"))
        self.assertEqual(b"rev-2", master.tags.lookup_tag("foo"))
        # The conflict is reported exactly once, even though it occurs in both
        # master and child.
        self.assertEqual({}, tag_updates)
        self.assertEqual([("foo", b"rev-1", b"rev-2")], list(tag_conflicts))

    def test_merge_to_different_conflict_in_master_and_child(self):
        """When new_tags.merge_to(child.tags) conflicts differently in the
        master and the child both conflicts are reported.
        """
        master = self.make_branch("master")
        master.tags.set_tag("foo", b"rev-2")
        other = self.make_branch("other")
        other.tags.set_tag("foo", b"rev-1")
        child = self.make_branch("child")
        child.bind(master)
        child.update()
        # We use the private method _set_tag_dict because normally bzr tries to
        # avoid this scenario.
        child.tags._set_tag_dict({"foo": b"rev-3"})
        tag_updates, tag_conflicts = other.tags.merge_to(child.tags)
        # Both master and child conflict, so both stay as they were.
        self.assertEqual(b"rev-3", child.tags.lookup_tag("foo"))
        self.assertEqual(b"rev-2", master.tags.lookup_tag("foo"))
        # Both conflicts are reported.
        self.assertEqual({}, tag_updates)
        self.assertEqual(
            [("foo", b"rev-1", b"rev-2"), ("foo", b"rev-1", b"rev-3")],
            sorted(tag_conflicts),
        )


class TestUnsupportedTags(per_branch.TestCaseWithBranch):
    """Formats that don't support tags should give reasonable errors."""

    def setUp(self):
        super().setUp()
        branch = self.make_branch("probe")
        if branch._format.supports_tags():
            raise tests.TestSkipped(
                "Format {} declares that tags are supported".format(branch._format)
            )
            # it's covered by TestBranchTags

    def test_tag_methods_raise(self):
        b = self.make_branch("b")
        self.assertRaises(errors.TagsNotSupported, b.tags.set_tag, "foo", "bar")
        self.assertRaises(errors.TagsNotSupported, b.tags.lookup_tag, "foo")
        self.assertRaises(errors.TagsNotSupported, b.tags.set_tag, "foo", "bar")
        self.assertRaises(errors.TagsNotSupported, b.tags.delete_tag, "foo")

    def test_merge_empty_tags(self):
        # you can merge tags between two instances, since neither have tags
        b1 = self.make_branch("b1")
        b2 = self.make_branch("b2")
        b1.tags.merge_to(b2.tags)


class AutomaticTagNameTests(per_branch.TestCaseWithBranch):
    def setUp(self):
        super().setUp()
        if isinstance(self.branch_format, bzrbranch.BranchReferenceFormat):
            # This test could in principle apply to BranchReferenceFormat, but
            # make_branch_builder doesn't support it.
            raise tests.TestSkipped("BranchBuilder can't make reference branches.")
        self.builder = self.make_branch_builder(".")
        self.builder.build_snapshot(
            None, [("add", ("", None, "directory", None))], message="foo"
        )
        self.branch = self.builder.get_branch()
        if not self.branch._format.supports_tags():
            raise tests.TestSkipped(
                f"format {self.branch._format} doesn't support tags"
            )

    def test_no_functions(self):
        rev = self.branch.last_revision()
        self.assertEqual(None, self.branch.automatic_tag_name(rev))

    def test_returns_tag_name(self):
        def get_tag_name(br, revid):
            return "foo"

        branch.Branch.hooks.install_named_hook(
            "automatic_tag_name", get_tag_name, "get tag name foo"
        )
        self.assertEqual(
            "foo", self.branch.automatic_tag_name(self.branch.last_revision())
        )

    def test_uses_first_return(self):
        def get_tag_name_1(br, revid):
            return "foo1"

        def get_tag_name_2(br, revid):
            return "foo2"

        branch.Branch.hooks.install_named_hook(
            "automatic_tag_name", get_tag_name_1, "tagname1"
        )
        branch.Branch.hooks.install_named_hook(
            "automatic_tag_name", get_tag_name_2, "tagname2"
        )
        self.assertEqual(
            "foo1", self.branch.automatic_tag_name(self.branch.last_revision())
        )

    def test_ignores_none(self):
        def get_tag_name_1(br, revid):
            return None

        def get_tag_name_2(br, revid):
            return "foo2"

        branch.Branch.hooks.install_named_hook(
            "automatic_tag_name", get_tag_name_1, "tagname1"
        )
        branch.Branch.hooks.install_named_hook(
            "automatic_tag_name", get_tag_name_2, "tagname2"
        )
        self.assertEqual(
            "foo2", self.branch.automatic_tag_name(self.branch.last_revision())
        )
