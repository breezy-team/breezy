# Copyright (C) 2005-2011 Canonical Ltd
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

from . import TestCase

from ..views import (
    FileOutsideView,
    NoSuchView,
    ViewsNotSupported,
    )


class TestErrors(TestCase):

    def test_no_such_view(self):
        err = NoSuchView('foo')
        self.assertEqual("No such view: foo.", str(err))

    def test_views_not_supported(self):
        err = ViewsNotSupported('atree')
        err_str = str(err)
        self.assertStartsWith(err_str, "Views are not supported by ")
        self.assertEndsWith(err_str, "; use 'brz upgrade' to change your "
                            "tree to a later format.")

    def test_file_outside_view(self):
        err = FileOutsideView('baz', ['foo', 'bar'])
        self.assertEqual('Specified file "baz" is outside the current view: '
                         'foo, bar', str(err))
