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


class TestProber(tests.TestCaseWithTransport):
    """Per-prober tests."""

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
        known_formats = self.prober_cls.known_formats()
        self.assertIsInstance(known_formats, set)
        for format in known_formats:
            self.assertIsInstance(format, controldir.ControlDirFormat,
                repr(format))


class NotBzrDir(controldir.ControlDir):
    """A non .bzr based control directory."""

    def __init__(self, transport, format):
        self._format = format
        self.root_transport = transport
        self.transport = transport.clone('.not')


class NotBzrDirFormat(controldir.ControlDirFormat):
    """A test class representing any non-.bzr based disk format."""

    def initialize_on_transport(self, transport):
        """Initialize a new .not dir in the base directory of a Transport."""
        transport.mkdir('.not')
        return self.open(transport)

    def open(self, transport):
        """Open this directory."""
        return NotBzrDir(transport, self)


class NotBzrDirProber(controldir.Prober):

    def probe_transport(self, transport):
        """Our format is present if the transport ends in '.not/'."""
        if transport.has('.not'):
            return NotBzrDirFormat()

    @classmethod
    def known_formats(cls):
        return set([NotBzrDirFormat()])


class TestNotBzrDir(tests.TestCaseWithTransport):
    """Tests for using the controldir api with a non .bzr based disk format.

    If/when one of these is in the core, we can let the implementation tests
    verify this works.
    """

    def test_create_and_find_format(self):
        # create a .notbzr dir
        format = NotBzrDirFormat()
        dir = format.initialize(self.get_url())
        self.assertIsInstance(dir, NotBzrDir)
        # now probe for it.
        controldir.ControlDirFormat.register_prober(NotBzrDirProber)
        try:
            found = controldir.ControlDirFormat.find_format(self.get_transport())
            self.assertIsInstance(found, NotBzrDirFormat)
        finally:
            controldir.ControlDirFormat.unregister_prober(NotBzrDirProber)

    def test_included_in_known_formats(self):
        controldir.ControlDirFormat.register_prober(NotBzrDirProber)
        self.addCleanup(controldir.ControlDirFormat.unregister_prober, NotBzrDirProber)
        formats = controldir.ControlDirFormat.known_formats()
        self.assertIsInstance(formats, set)
        for format in formats:
            if isinstance(format, NotBzrDirFormat):
                break
        else:
            self.fail("No NotBzrDirFormat in %s" % formats)
