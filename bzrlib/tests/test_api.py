# Copyright (C) 2005 Canonical Ltd
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

"""Tests for library API infrastructure

This is specifically for things controlling the interface, such as versioning.  
Tests for particular parts of the library interface should be in specific
relevant test modules.
"""

import bzrlib
import bzrlib.api
from bzrlib.tests import TestCase

class APITests(TestCase):

    def test_library_version(self):
        """Library API version is exposed"""
        self.assert_(isinstance(bzrlib.__version__, str))
        self.assert_(isinstance(bzrlib.version_string, str))
        self.assert_(isinstance(bzrlib.version_info, tuple))
        self.assertEqual(len(bzrlib.version_info), 5)


class TrivialObject(object):
    """This class allows assignment to any attribute."""


class TestAPIVersioning(TestCase):

    def test_get_minimum_api_version_reads_api_minimum_version(self):
        an_object = TrivialObject()
        an_object.api_minimum_version = (0, 1, 2)
        self.assertEqual((0, 1, 2),
            bzrlib.api.get_minimum_api_version(an_object))

    def test_get_minimum_api_version_fallsback_to_bzr_minimum_version(self):
        an_object = TrivialObject()
        self.assertEqual(bzrlib.api_minimum_version,
            bzrlib.api.get_minimum_api_version(an_object))

    def test_get_current_api_version_reads_api_current_version(self):
        an_object = TrivialObject()
        an_object.api_current_version = (3, 2, 1)
        an_object.version_info = (1, 2, 3, "final", 0)
        self.assertEqual((3, 2, 1),
            bzrlib.api.get_current_api_version(an_object))

    def test_get_current_api_version_fallsback_to_version_info(self):
        an_object = TrivialObject()
        an_object.version_info = (1, 2, 3, "final", 0)
        self.assertEqual((1, 2, 3),
            bzrlib.api.get_current_api_version(an_object))

    def test_get_current_api_version_fallsback_to_bzrlib_version_info(self):
        an_object = TrivialObject()
        self.assertEqual(bzrlib.version_info[0:3],
            bzrlib.api.get_current_api_version(an_object))
