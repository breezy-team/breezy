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

from bzrlib.directory_service import DirectoryServiceRegistry, directories
from bzrlib.tests import TestCase
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
