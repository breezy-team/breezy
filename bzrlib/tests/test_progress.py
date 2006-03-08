# Copyright (C) 2006 by Canonical Ltd
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

from bzrlib.progress import DummyProgress, ChildProgress
from bzrlib.tests import TestCase

class TestProgress(TestCase):
    def setUp(self):
        self.top = ChildProgress(stack=[DummyProgress()])

    def test_propogation(self):
        self.top.update('foobles', 1, 2)
        self.assertEqual(self.top.message, 'foobles')
        self.assertEqual(self.top.current, 1)
        self.assertEqual(self.top.total, 2)
        self.assertEqual(self.top.child_fraction, 0)
        child = ChildProgress(stack=[self.top])
        child.update('baubles', 2, 4)
        self.assertEqual(self.top.message, 'foobles')
        self.assertEqual(self.top.current, 1)
        self.assertEqual(self.top.total, 2)
        self.assertEqual(self.top.child_fraction, 0.5)
        grandchild = ChildProgress(stack=[child])
        grandchild.update('barbells', 1, 2)
        self.assertEqual(self.top.child_fraction, 0.625)
        self.assertEqual(child.child_fraction, 0.5)
        child.update('baubles', 3, 4)
        self.assertEqual(child.child_fraction, 0)
        self.assertEqual(self.top.child_fraction, 0.75)
        grandchild.update('barbells', 1, 2)
        self.assertEqual(self.top.child_fraction, 0.875)
        grandchild.update('barbells', 2, 2)
        self.assertEqual(self.top.child_fraction, 1)
        child.update('baubles', 4, 4)
        self.assertEqual(self.top.child_fraction, 1)
        #test clamping
        grandchild.update('barbells', 2, 2)
        self.assertEqual(self.top.child_fraction, 1)
