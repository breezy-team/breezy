# Copyright (C) 2007 Canonical Ltd
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

"""Tests for the FileNames class."""

from bzrlib import errors
from bzrlib.file_names import FileNames
from bzrlib.tests import TestCaseWithMemoryTransport
from bzrlib.transport import get_transport


class TestFileNames(TestCaseWithMemoryTransport):

    def test_initialise(self):
        t = self.get_transport()
        for name in ('index', '00index'):
            names = FileNames(t, name)
            names.initialise()
            self.assertFalse(t.has(name))
            names.save()
            self.assertEqual('', t.get_bytes(name))
        
    def test_allocate_trivial(self):
        t = self.get_transport()
        names = FileNames(t, 'index')
        names.initialise()
        name = names.allocate()
        self.assertEqual('0', name)
        self.assertFalse(t.has('index'))
        name = names.allocate()
        self.assertEqual('1', name)
        self.assertFalse(t.has('index'))

    def test_allocate_overrun(self):
        t = self.get_transport()
        names = FileNames(t, 'index')
        names.initialise()
        names._cap = 5
        for number in xrange(5):
            name = names.allocate()
        self.assertRaises(errors.BzrError, names.allocate)

    def test_load(self):
        t = self.get_transport()
        names = FileNames(t, 'index')
        names.initialise()
        names.allocate()
        names.allocate()
        names.save()
        names = FileNames(t, 'index')
        names.load()
        self.assertEqual(set(['0', '1']), names.names())

    def test_load_empty(self):
        t = self.get_transport()
        names = FileNames(t, 'index')
        names.initialise()
        names.save()
        names = FileNames(t, 'index')
        names.load()
        self.assertEqual(set(), names.names())

    def test_names(self):
        t = self.get_transport()
        names = FileNames(t, 'index')
        names.initialise()
        names.allocate()
        names.allocate()
        self.assertEqual(set(['0', '1']), names.names())

    def test_names_on_unlistable_works(self):
        t = self.get_transport()
        names = FileNames(t, 'index')
        names.initialise()
        names.allocate()
        names.allocate()
        names.save()
        names = FileNames(
            get_transport('unlistable+' + self.get_url()), 'index')
        names.load()
        self.assertEqual(set(['0', '1']), names.names())

    def test_remove(self):
        t = self.get_transport()
        names = FileNames(t, 'index')
        names.initialise()
        name1 = names.allocate()
        name2 = names.allocate()
        names.remove(name1)
        self.assertEqual(set([name2]), names.names())
