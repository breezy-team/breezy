# Copyright (C) 2011 Canonical Ltd
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

"""Tests for the ControlDir facility.

For interface contract tests, see tests/per_control_dir.
"""

from bzrlib import (
    controldir,
    tests,
    )


class SampleComponentFormat(controldir.ControlComponentFormat):

    def get_format_string(self):
        return "Example component format."


class SampleExtraComponentFormat(controldir.ControlComponentFormat):
    """Extra format, no format string."""


class TestMetaComponentFormatRegistry(tests.TestCase):

    def setUp(self):
        super(TestMetaComponentFormatRegistry, self).setUp()
        self.registry = controldir.ControlComponentFormatRegistry()

    def test_register_unregister_format(self):
        format = SampleComponentFormat()
        self.registry.register(format)
        self.assertEquals(format,
            self.registry.get("Example component format."))
        self.registry.remove(format)
        self.assertRaises(KeyError, self.registry.get,
            "Example component format.")

    def test_get_all(self):
        format = SampleComponentFormat()
        self.assertEquals([], self.registry._get_all())
        self.registry.register(format)
        self.assertEquals([format], self.registry._get_all())

    def test_get_all_modules(self):
        format = SampleComponentFormat()
        self.assertEquals(set(), self.registry._get_all_modules())
        self.registry.register(format)
        self.assertEquals(
            set(["bzrlib.tests.test_controldir"]),
            self.registry._get_all_modules())

    def test_register_extra(self):
        format = SampleExtraComponentFormat()
        self.assertEquals([], self.registry._get_all())
        self.registry.register_extra(format)
        self.assertEquals([format], self.registry._get_all())

    def test_register_extra_lazy(self):
        self.assertEquals([], self.registry._get_all())
        self.registry.register_extra_lazy("bzrlib.tests.test_controldir",
            "SampleExtraComponentFormat")
        formats = self.registry._get_all()
        self.assertEquals(1, len(formats))
        self.assertIsInstance(formats[0], SampleExtraComponentFormat)
