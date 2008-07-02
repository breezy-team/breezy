# Copyright (C) 2008 Canonical Ltd
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

"""Test directory service implementation"""

from bzrlib import errors
from bzrlib.directory_service import DirectoryServiceRegistry, directories
from bzrlib.tests import TestCase, TestCaseWithTransport
from bzrlib.transport import get_transport


class FooService(object):
    """A directory service that maps the name to a FILE url"""

    def look_up(self, name, url):
        return 'file:///foo' + name


class TestDirectoryLookup(TestCase):

    def setUp(self):
        TestCase.setUp(self)
        self.registry = DirectoryServiceRegistry()
        self.registry.register('foo:', FooService, 'Map foo URLs to http urls')

    def test_get_directory_service(self):
        directory, suffix = self.registry.get_prefix('foo:bar')
        self.assertIs(FooService, directory)
        self.assertEqual('bar', suffix)

    def test_dereference(self):
        self.assertEqual('file:///foobar',
                         self.registry.dereference('foo:bar'))
        self.assertEqual('baz:qux', self.registry.dereference('baz:qux'))

    def test_get_transport(self):
        directories.register('foo:', FooService, 'Map foo URLs to http urls')
        self.addCleanup(lambda: directories.remove('foo:'))
        self.assertEqual('file:///foobar/', get_transport('foo:bar').base)


class TestAliasDirectory(TestCaseWithTransport):

    def test_lookup_parent(self):
        branch = self.make_branch('.')
        branch.set_parent('http://a')
        self.assertEqual('http://a', directories.dereference(':parent'))

    def test_lookup_submit(self):
        branch = self.make_branch('.')
        branch.set_submit_branch('http://b')
        self.assertEqual('http://b', directories.dereference(':submit'))

    def test_lookup_public(self):
        branch = self.make_branch('.')
        branch.set_public_branch('http://c')
        self.assertEqual('http://c', directories.dereference(':public'))

    def test_lookup_bound(self):
        branch = self.make_branch('.')
        branch.set_bound_location('http://d')
        self.assertEqual('http://d', directories.dereference(':bound'))

    def test_lookup_push(self):
        branch = self.make_branch('.')
        branch.set_push_location('http://e')
        self.assertEqual('http://e', directories.dereference(':push'))

    def test_lookup_this(self):
        branch = self.make_branch('.')
        self.assertEqual(branch.base, directories.dereference(':this'))

    def test_lookup_badname(self):
        branch = self.make_branch('.')
        e = self.assertRaises(errors.InvalidLocationAlias,
                              directories.dereference, ':booga')
        self.assertEqual('":booga" is not a valid location alias.',
                         str(e))

    def test_lookup_badvalue(self):
        branch = self.make_branch('.')
        e = self.assertRaises(errors.UnsetLocationAlias,
                              directories.dereference, ':parent')
        self.assertEqual('No parent location assigned.', str(e))
