# Copyright (C) 2008, 2009, 2011, 2016 Canonical Ltd
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

"""Test uncommit."""


from .. import (
    errors,
    tests,
    uncommit,
    )


class TestUncommit(tests.TestCaseWithTransport):

    def make_linear_tree(self):
        tree = self.make_branch_and_tree('tree')
        tree.lock_write()
        try:
            self.build_tree(['tree/one'])
            tree.add('one')
            rev_id1 = tree.commit('one')
            self.build_tree(['tree/two'])
            tree.add('two')
            rev_id2 = tree.commit('two')
        finally:
            tree.unlock()
        return tree, [rev_id1, rev_id2]

    def test_uncommit(self):
        tree, history = self.make_linear_tree()
        self.assertEqual(history[1], tree.last_revision())
        self.assertEqual((2, history[1]), tree.branch.last_revision_info())
        uncommit.uncommit(tree.branch, tree=tree)
        self.assertEqual(history[0], tree.last_revision())
        self.assertEqual((1, history[0]), tree.branch.last_revision_info())

        # The file should not be removed
        self.assertPathExists('tree/two')
        # And it should still be listed as added
        self.assertTrue(tree.is_versioned('two'))

    def test_uncommit_bound(self):
        tree, history = self.make_linear_tree()
        child = tree.controldir.sprout('child').open_workingtree()
        child.branch.bind(tree.branch)

        self.assertEqual(history[1], tree.last_revision())
        self.assertEqual((2, history[1]), tree.branch.last_revision_info())
        self.assertEqual(history[1], child.last_revision())
        self.assertEqual((2, history[1]), child.branch.last_revision_info())

        # Uncommit in a bound branch should uncommit the master branch, but not
        # touch the other working tree.
        uncommit.uncommit(child.branch, tree=child)

        self.assertEqual(history[1], tree.last_revision())
        self.assertEqual((1, history[0]), tree.branch.last_revision_info())
        self.assertEqual(history[0], child.last_revision())
        self.assertEqual((1, history[0]), child.branch.last_revision_info())

    def test_uncommit_bound_local(self):
        tree, history = self.make_linear_tree()
        child = tree.controldir.sprout('child').open_workingtree()
        child.branch.bind(tree.branch)

        self.assertEqual(history[1], tree.last_revision())
        self.assertEqual((2, history[1]), tree.branch.last_revision_info())
        self.assertEqual(history[1], child.last_revision())
        self.assertEqual((2, history[1]), child.branch.last_revision_info())

        # Uncommit local=True should only affect the local branch
        uncommit.uncommit(child.branch, tree=child, local=True)

        self.assertEqual(history[1], tree.last_revision())
        self.assertEqual((2, history[1]), tree.branch.last_revision_info())
        self.assertEqual(history[0], child.last_revision())
        self.assertEqual((1, history[0]), child.branch.last_revision_info())

    def test_uncommit_unbound_local(self):
        tree, history = self.make_linear_tree()

        # If this tree isn't bound, local=True raises an exception
        self.assertRaises(errors.LocalRequiresBoundBranch,
                          uncommit.uncommit, tree.branch, tree=tree,
                          local=True)

    def test_uncommit_remove_tags(self):
        tree, history = self.make_linear_tree()
        self.assertEqual(history[1], tree.last_revision())
        self.assertEqual((2, history[1]), tree.branch.last_revision_info())
        tree.branch.tags.set_tag(u"pointsatexisting", history[0])
        tree.branch.tags.set_tag(u"pointsatremoved", history[1])
        uncommit.uncommit(tree.branch, tree=tree)
        self.assertEqual(history[0], tree.last_revision())
        self.assertEqual((1, history[0]), tree.branch.last_revision_info())
        self.assertEqual({
            "pointsatexisting": history[0]
            }, tree.branch.tags.get_tag_dict())

    def test_uncommit_remove_tags_keeps_pending_merges(self):
        tree, history = self.make_linear_tree()
        copy = tree.controldir.sprout('copyoftree').open_workingtree()
        copy.commit(message='merged', rev_id=b'merged')
        tree.merge_from_branch(copy.branch)
        tree.branch.tags.set_tag('pointsatmerged', b'merged')
        history.append(tree.commit('merge'))
        self.assertEqual(
            b'merged', tree.branch.tags.lookup_tag('pointsatmerged'))
        self.assertEqual(history[2], tree.last_revision())
        self.assertEqual((3, history[2]), tree.branch.last_revision_info())
        tree.branch.tags.set_tag(u"pointsatexisting", history[1])
        tree.branch.tags.set_tag(u"pointsatremoved", history[2])
        uncommit.uncommit(tree.branch, tree=tree)
        self.assertEqual(history[1], tree.last_revision())
        self.assertEqual((2, history[1]), tree.branch.last_revision_info())
        self.assertEqual([history[1], b'merged'], tree.get_parent_ids())
        self.assertEqual({
            "pointsatexisting": history[1],
            "pointsatmerged": b'merged',
            }, tree.branch.tags.get_tag_dict())

    def test_uncommit_keep_tags(self):
        tree, history = self.make_linear_tree()
        self.assertEqual(history[1], tree.last_revision())
        self.assertEqual((2, history[1]), tree.branch.last_revision_info())
        tree.branch.tags.set_tag(u"pointsatexisting", history[0])
        tree.branch.tags.set_tag(u"pointsatremoved", history[1])
        uncommit.uncommit(tree.branch, tree=tree, keep_tags=True)
        self.assertEqual(history[0], tree.last_revision())
        self.assertEqual((1, history[0]), tree.branch.last_revision_info())
        self.assertEqual({
            "pointsatexisting": history[0],
            "pointsatremoved": history[1],
            }, tree.branch.tags.get_tag_dict())
