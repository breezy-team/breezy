# Copyright (C) 2004, 2005 by Canonical Ltd
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


import cStringIO
import os
import sys

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
        self.assertEqual(None, b.get_parent())
        
    def test_set_get_parent(self):
        """Set, re-get and reset the parent"""
        b = self.make_branch('.')
        url = 'http://bazaar-vcs.org/bzr/bzr.dev'
        b.set_parent(url)
        self.assertEqual(url, b.get_parent())
        self.assertEqual(url, b.control_files.get('parent').read().strip('\n'))

        b.set_parent(None)
        self.assertEqual(None, b.get_parent())

        b.set_parent('../other_branch')
        cwd = getcwd()

        self.assertEqual(local_path_to_url('../other_branch'), b.get_parent())
        path = local_path_to_url('../yanb')
        b.set_parent(path)
        self.assertEqual('../yanb',
            b.control_files.get('parent').read().strip('\n'))
        self.assertEqual(path, b.get_parent())


        self.assertRaises(bzrlib.errors.InvalidURL, b.set_parent, u'\xb5')
        b.set_parent(escape(u'\xb5'))
        self.assertEqual('%C2%B5', 
            b.control_files.get('parent').read().strip('\n'))

        self.assertEqual(b.base + '%C2%B5', b.get_parent())

        # Handle the case for older style absolute local paths
        if sys.platform == 'win32':
            # TODO: jam 20060515 Do we want to special case Windows local
            #       paths as well? Nobody has complained about it.
            pass
        else:
            b.control_files.put('parent', cStringIO.StringIO('/local/abs/path'))
            self.assertEqual('file:///local/abs/path', b.get_parent())

