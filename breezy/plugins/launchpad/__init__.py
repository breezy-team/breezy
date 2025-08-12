# Copyright (C) 2006-2017 Canonical Ltd
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

"""Launchpad.net integration plugin for Bazaar.

This plugin provides facilities for working with Bazaar branches that are
hosted on Launchpad (http://launchpad.net).  It provides a directory service
for referring to Launchpad branches using the "lp:" prefix.  For example,
lp:bzr refers to the Bazaar's main development branch and
lp:~username/project/branch-name can be used to refer to a specific branch.

This plugin provides a bug tracker so that "bzr commit --fixes lp:1234" will
record that revision as fixing Launchpad's bug 1234.

The plugin also provides the following commands:

    launchpad-login: Show or set the Launchpad user ID
    launchpad-open: Open a Launchpad branch page in your web browser

"""

from ... import version_info  # noqa: F401
from ...commands import plugin_cmds
from ...directory_service import directories
from ...help_topics import topic_registry

for klsname, aliases in [
    ("cmd_launchpad_open", ["lp-open"]),
    ("cmd_launchpad_login", ["lp-login"]),
    ("cmd_launchpad_logout", ["lp-logout"]),
    ("cmd_lp_find_proposal", []),
]:
    plugin_cmds.register_lazy(klsname, aliases, "breezy.plugins.launchpad.cmds")


def _register_directory():
    directories.register_lazy(
        "lp:",
        "breezy.plugins.launchpad.lp_directory",
        "LaunchpadDirectory",
        "Launchpad-based directory service",
    )
    directories.register_lazy(
        "lp+bzr:",
        "breezy.plugins.launchpad.lp_directory",
        "LaunchpadDirectory",
        "Bazaar-specific Launchpad directory service",
    )


_register_directory()


def load_tests(loader, basic_tests, pattern):
    """Load test suite for the launchpad plugin.

    This function is used by the unittest framework for test discovery.
    It loads all test modules for the launchpad plugin.

    Args:
        loader: The test loader instance used to load tests.
        basic_tests: The test suite to add tests to.
        pattern: The pattern used to match test files (unused).

    Returns:
        The test suite with all launchpad plugin tests added.
    """
    testmod_names = [
        "test_account",
        "test_lp_api",
        "test_lp_directory",
        "test_lp_login",
        "test_uris",
    ]
    for tmn in testmod_names:
        basic_tests.addTest(loader.loadTestsFromName(f"{__name__}.{tmn}"))
    return basic_tests


_launchpad_help = """Integration with Launchpad.net

Launchpad.net provides free Bazaar branch hosting with integrated bug and
specification tracking.

The bzr client (through the plugin called 'launchpad') has special
features to communicate with Launchpad:

    * The launchpad-login command tells Bazaar your Launchpad user name. This
      is then used by the 'lp:' transport to download your branches using
      bzr+ssh://.

    * The 'lp:' transport uses Launchpad as a directory service: for example
      'lp:bzr' and 'lp:python' refer to the main branches of the relevant
      projects and may be branched, logged, etc. You can also use the 'lp:'
      transport to refer to specific branches, e.g. lp:~bzr/bzr/trunk.

    * The 'lp:' bug tracker alias can expand launchpad bug numbers to their
      URLs for use with 'bzr commit --fixes', e.g. 'bzr commit --fixes lp:12345'
      will record a revision property that marks that revision as fixing
      Launchpad bug 12345. When you push that branch to Launchpad it will
      automatically be linked to the bug report.

For more information see http://help.launchpad.net/
"""
topic_registry.register("launchpad", _launchpad_help, "Using Bazaar with Launchpad.net")


from ...forge import forges

forges.register_lazy("launchpad", __name__ + ".forge", "Launchpad")
