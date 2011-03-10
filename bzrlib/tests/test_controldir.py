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
    errors,
    tests,
    )
from bzrlib.tests.scenarios import load_tests_apply_scenarios


load_tests = load_tests_apply_scenarios


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


class ControlDirFormatTest1(controldir.ControlDirFormat):
    """A test control dir format."""


class TestControlDirFormat(tests.TestCaseWithTransport):
    """Tests for the ControlDirFormat facility."""

    def test_register_unregister_format(self):
        format = ControlDirFormatTest1()
        controldir.ControlDirFormat.register_format("myformat", format)
        self.assertTrue(format in controldir.ControlDirFormat.known_formats())
        controldir.ControlDirFormat.unregister_format("myformat")
        self.assertFalse(format in controldir.ControlDirFormat.known_formats())
        self.assertRaises(KeyError,
            controldir.ControlDirFormat.unregister_format, "myformat")

    def test_register_unregister_format_lazy(self):
        controldir.ControlDirFormat.register_lazy_format(
            "lui", "bzrlib.tests.test_controldir", "ControlDirFormatTest1")
        self.assertTrue(
            ControlDirFormatTest1 in
            controldir.ControlDirFormat.known_formats())
        controldir.ControlDirFormat.unregister_format("lui")
        self.assertFalse(
            ControlDirFormatTest1 in
            controldir.ControlDirFormat.known_formats())
        self.assertRaises(KeyError,
            controldir.ControlDirFormat.unregister_format, "myformat")


class TestProber(tests.TestCaseWithTransport):

    scenarios = [
        (prober_cls.__name__, {'prober_cls': prober_cls})
        for prober_cls in controldir.ControlDirFormat._probers]

    def setUp(self):
        super(TestProber, self).setUp()
        self.prober = self.prober_cls()

    def test_probe_transport_empty(self):
        transport = self.get_transport(".")
        self.assertRaises(errors.NotBranchError,
            self.prober.probe_transport, transport)

    def test_known_formats(self):
        known_formats = self.prober.known_formats()
        self.assertIsInstance(known_formats, set)
        for format in known_formats:
            self.assertIsInstance(format, controldir.ControlDirFormat,
                repr(format))
