# Copyright (C) 2004, 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


import os

from bzrlib.branch import Branch
import bzrlib.errors
from bzrlib.osutils import abspath, realpath, getcwd
from bzrlib.urlutils import local_path_from_url, local_path_to_url, escape
from bzrlib.tests import TestCaseWithTransport


"""Tests for Branch parent URL"""


class TestParent(TestCaseWithTransport):

    def test_no_default_parent(self):
        """Branches should have no parent by default"""
        b = self.make_branch('.')
        self.assertEquals(b.get_parent(), None)
        
    def test_set_get_parent(self):
        """Set, re-get and reset the parent"""
        b = self.make_branch('.')
        url = 'http://bazaar-vcs.org/bzr/bzr.dev'
        b.set_parent(url)
        self.assertEquals(b.get_parent(), url)
        self.assertEqual(b.control_files.get('parent').read().strip('\n'), url)

        b.set_parent(None)
        self.assertEquals(b.get_parent(), None)

        b.set_parent('../other_branch')
        cwd = getcwd()

        self.assertEquals(b.get_parent(), local_path_to_url('../other_branch'))
        path = local_path_to_url('../yanb')
        b.set_parent(path)
        self.assertEqual(b.control_files.get('parent').read().strip('\n'), 
            '../yanb')
        self.assertEqual(b.get_parent(), path)


        self.assertRaises(bzrlib.errors.InvalidURL, b.set_parent, u'\xb5')
        b.set_parent(escape(u'\xb5'))
        self.assertEqual(b.control_files.get('parent').read().strip('\n'), 
            '%C2%B5')

        self.assertEqual(b.get_parent(), b.base + '%C2%B5')

