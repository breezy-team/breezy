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


"""External tests of 'brz export-pot'"""


from breezy.tests import TestCaseWithMemoryTransport
from breezy.tests.features import PluginLoadedFeature


class TestExportPot(TestCaseWithMemoryTransport):
    def test_export_pot(self):
        out, err = self.run_bzr("export-pot")
        self.assertContainsRe(err, "Exporting messages from builtin command: add")
        self.assertContainsRe(
            out,
            "help of 'change' option\n"
            'msgid "Select changes introduced by the specified revision.',
        )

    def test_export_pot_plugin_unknown(self):
        out, err = self.run_bzr("export-pot --plugin=lalalala", retcode=3)
        self.assertContainsRe(err, "ERROR: Plugin lalalala is not loaded")

    def test_export_pot_plugin(self):
        self.requireFeature(PluginLoadedFeature("launchpad"))
        out, err = self.run_bzr("export-pot --plugin=launchpad")
        self.assertContainsRe(
            err, "Exporting messages from plugin command: launchpad-login in launchpad"
        )
        self.assertContainsRe(out, 'msgid "Show or set the Launchpad user ID."')
