# Copyright (C) 2005-2011, 2015, 2016 Canonical Ltd
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

"""Tests for breezy.location."""

from .. import (
    osutils,
    tests,
    urlutils,
    )
from ..directory_service import directories
from ..location import (
    location_to_url,
    )


class SomeDirectory(object):

    def look_up(self, name, url):
        return "http://bar"


class TestLocationToUrl(tests.TestCase):

    def get_base_location(self):
        path = osutils.abspath('/foo/bar')
        if path.startswith('/'):
            url = 'file://%s' % (path,)
        else:
            # On Windows, abspaths start with the drive letter, so we have to
            # add in the extra '/'
            url = 'file:///%s' % (path,)
        return path, url

    def test_regular_url(self):
        self.assertEqual("file://foo", location_to_url("file://foo"))

    def test_directory(self):
        directories.register("bar:", SomeDirectory, "Dummy directory")
        self.addCleanup(directories.remove, "bar:")
        self.assertEqual("http://bar", location_to_url("bar:"))

    def test_unicode_url(self):
        self.assertRaises(urlutils.InvalidURL, location_to_url,
                          b"http://fo/\xc3\xaf".decode("utf-8"))

    def test_unicode_path(self):
        path, url = self.get_base_location()
        location = path + b"\xc3\xaf".decode("utf-8")
        url += '%C3%AF'
        self.assertEqual(url, location_to_url(location))

    def test_path(self):
        path, url = self.get_base_location()
        self.assertEqual(url, location_to_url(path))

    def test_relative_file_url(self):
        self.assertEqual(urlutils.local_path_to_url(".") + "/bar",
                         location_to_url("file:bar"))

    def test_absolute_file_url(self):
        self.assertEqual("file:///bar", location_to_url("file:/bar"))
