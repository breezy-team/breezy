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
