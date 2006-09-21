# Copyright (C) 2006 Canonical Ltd
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

"""Tests for revision properties."""

from bzrlib.tests.repository_implementations.test_repository import (
    TestCaseWithRepository,
    )

class TestRevProps(TestCaseWithRepository):

    def test_simple_revprops(self):
        """Simple revision properties"""
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        b.nick = 'Nicholas'
        props = dict(flavor='choc-mint',
                     condiment='orange\n  mint\n\tcandy',
                     empty='',
                     non_ascii=u'\xb5')
        wt.commit(message='initial null commit', 
                 revprops=props,
                 allow_pointless=True,
                 rev_id='test@user-1')
        rev = b.repository.get_revision('test@user-1')
        self.assertTrue('flavor' in rev.properties)
        self.assertEquals(rev.properties['flavor'], 'choc-mint')
        self.assertEquals([('branch-nick', 'Nicholas'), 
                           ('condiment', 'orange\n  mint\n\tcandy'),
                           ('empty', ''),
                           ('flavor', 'choc-mint'),
                           ('non_ascii', u'\xb5'),
                          ], sorted(rev.properties.items()))

    def test_invalid_revprops(self):
        """Invalid revision properties"""
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        self.assertRaises(ValueError,
                          wt.commit, 
                          message='invalid',
                          revprops={'what a silly property': 'fine'})
        self.assertRaises(ValueError,
                          wt.commit, 
                          message='invalid',
                          revprops=dict(number=13))


class TestRevisionAttributes(TestCaseWithRepository):
    """Test that revision attributes are correct."""

    def test_revision_accessors(self):
        """Make sure the values that come out of a revision are the 
        same as the ones that go in.
        """
        tree1 = self.make_branch_and_tree("br1")

        # create a revision
        tree1.commit(message="quux", allow_pointless=True, committer="jaq",
                     revprops={'empty':'',
                               'value':'one',
                               'unicode':'\xb5',
                               'multiline':'foo\nbar\n\n'
                              })
        assert len(tree1.branch.revision_history()) > 0
        rev_a = tree1.branch.repository.get_revision(
                            tree1.branch.last_revision())

        tree2 = self.make_branch_and_tree("br2")
        tree2.commit(message=rev_a.message,
                     timestamp=rev_a.timestamp,
                     timezone=rev_a.timezone,
                     committer=rev_a.committer,
                     rev_id=rev_a.revision_id,
                     revprops=rev_a.properties,
                     allow_pointless=True, # there's nothing in this commit
                     strict=True,
                     verbose=True)
        rev_b = tree2.branch.repository.get_revision(
                            tree2.branch.last_revision())
        
        self.assertEqual(rev_a.message, rev_b.message)
        self.assertEqual(rev_a.timestamp, rev_b.timestamp)
        self.assertEqual(rev_a.timezone, rev_b.timezone)
        self.assertEqual(rev_a.committer, rev_b.committer)
        self.assertEqual(rev_a.revision_id, rev_b.revision_id)
        self.assertEqual(rev_a.properties, rev_b.properties)

    def test_zero_timezone(self):
        tree1 = self.make_branch_and_tree("br1")

        # create a revision
        tree1.commit(message="quux", timezone=0, rev_id='r1')
        rev_a = tree1.branch.repository.get_revision('r1')
        self.assertEqual(0, rev_a.timezone)
