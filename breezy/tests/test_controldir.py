# Copyright (C) 2011, 2016 Canonical Ltd
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

from .. import (
    controldir,
    errors,
    tests,
    ui,
    )
from .scenarios import load_tests_apply_scenarios


load_tests = load_tests_apply_scenarios


class TestErrors(tests.TestCase):

    def test_must_have_working_tree(self):
        err = controldir.MustHaveWorkingTree('foo', 'bar')
        self.assertEqual(str(err), "Branching 'bar'(foo) must create a"
                                   " working tree.")


class SampleComponentFormat(controldir.ControlComponentFormat):

    def get_format_string(self):
        return b"Example component format."


class SampleExtraComponentFormat(controldir.ControlComponentFormat):
    """Extra format, no format string."""


class TestMetaComponentFormatRegistry(tests.TestCase):

    def setUp(self):
        super(TestMetaComponentFormatRegistry, self).setUp()
        self.registry = controldir.ControlComponentFormatRegistry()

    def test_register_unregister_format(self):
        format = SampleComponentFormat()
        self.registry.register(format)
        self.assertEqual(format,
                         self.registry.get(b"Example component format."))
        self.registry.remove(format)
        self.assertRaises(KeyError, self.registry.get,
                          b"Example component format.")

    def test_get_all(self):
        format = SampleComponentFormat()
        self.assertEqual([], self.registry._get_all())
        self.registry.register(format)
        self.assertEqual([format], self.registry._get_all())

    def test_get_all_modules(self):
        format = SampleComponentFormat()
        self.assertEqual(set(), self.registry._get_all_modules())
        self.registry.register(format)
        self.assertEqual(
            {"breezy.tests.test_controldir"},
            self.registry._get_all_modules())

    def test_register_extra(self):
        format = SampleExtraComponentFormat()
        self.assertEqual([], self.registry._get_all())
        self.registry.register_extra(format)
        self.assertEqual([format], self.registry._get_all())

    def test_register_extra_lazy(self):
        self.assertEqual([], self.registry._get_all())
        self.registry.register_extra_lazy("breezy.tests.test_controldir",
                                          "SampleExtraComponentFormat")
        formats = self.registry._get_all()
        self.assertEqual(1, len(formats))
        self.assertIsInstance(formats[0], SampleExtraComponentFormat)


class TestProber(tests.TestCaseWithTransport):
    """Per-prober tests."""

    scenarios = [
        (prober_cls.__name__, {'prober_cls': prober_cls})
        for prober_cls in controldir.ControlDirFormat._probers]

    def setUp(self):
        super(TestProber, self).setUp()
        self.prober = self.prober_cls()

    def test_priority(self):
        transport = self.get_transport(".")
        self.assertIsInstance(self.prober.priority(transport), int)

    def test_probe_transport_empty(self):
        transport = self.get_transport(".")
        self.assertRaises(errors.NotBranchError,
                          self.prober.probe_transport, transport)

    def test_known_formats(self):
        known_formats = self.prober_cls.known_formats()
        self.assertIsInstance(known_formats, list)
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
        return [NotBzrDirFormat()]


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
            found = controldir.ControlDirFormat.find_format(
                self.get_transport())
            self.assertIsInstance(found, NotBzrDirFormat)
        finally:
            controldir.ControlDirFormat.unregister_prober(NotBzrDirProber)

    def test_included_in_known_formats(self):
        controldir.ControlDirFormat.register_prober(NotBzrDirProber)
        self.addCleanup(
            controldir.ControlDirFormat.unregister_prober, NotBzrDirProber)
        formats = controldir.ControlDirFormat.known_formats()
        self.assertIsInstance(formats, list)
        for format in formats:
            if isinstance(format, NotBzrDirFormat):
                break
        else:
            self.fail("No NotBzrDirFormat in %s" % formats)


class UnsupportedControlComponentFormat(controldir.ControlComponentFormat):

    def is_supported(self):
        return False


class OldControlComponentFormat(controldir.ControlComponentFormat):

    def get_format_description(self):
        return "An old format that is slow"

    upgrade_recommended = True


class DefaultControlComponentFormatTests(tests.TestCase):
    """Tests for default ControlComponentFormat implementation."""

    def test_check_support_status_unsupported(self):
        self.assertRaises(errors.UnsupportedFormatError,
                          UnsupportedControlComponentFormat().check_support_status,
                          allow_unsupported=False)
        UnsupportedControlComponentFormat().check_support_status(
            allow_unsupported=True)

    def test_check_support_status_supported(self):
        controldir.ControlComponentFormat().check_support_status(
            allow_unsupported=False)
        controldir.ControlComponentFormat().check_support_status(
            allow_unsupported=True)

    def test_recommend_upgrade_current_format(self):
        ui.ui_factory = tests.TestUIFactory()
        format = controldir.ControlComponentFormat()
        format.check_support_status(allow_unsupported=False,
                                    recommend_upgrade=True)
        self.assertEqual("", ui.ui_factory.stderr.getvalue())

    def test_recommend_upgrade_old_format(self):
        ui.ui_factory = tests.TestUIFactory()
        format = OldControlComponentFormat()
        format.check_support_status(allow_unsupported=False,
                                    recommend_upgrade=False)
        self.assertEqual("", ui.ui_factory.stderr.getvalue())
        format.check_support_status(allow_unsupported=False,
                                    recommend_upgrade=True, basedir='apath')
        self.assertEqual(
            'An old format that is slow is deprecated and a better format '
            'is available.\nIt is recommended that you upgrade by running '
            'the command\n  brz upgrade apath\n',
            ui.ui_factory.stderr.getvalue())


class IsControlFilenameTest(tests.TestCase):

    def test_is_bzrdir(self):
        self.assertTrue(controldir.is_control_filename('.bzr'))
        self.assertTrue(controldir.is_control_filename('.git'))

    def test_is_not_bzrdir(self):
        self.assertFalse(controldir.is_control_filename('bla'))
