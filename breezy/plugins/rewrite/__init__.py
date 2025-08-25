# Copyright (C) 2007 by Jelmer Vernooij <jelmer@samba.org>
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
"""Rebase support.

The Bazaar rebase plugin adds support for rebasing branches to Bazaar.
It adds the command 'rebase' to Bazaar. When conflicts occur when replaying
patches, the user can resolve the conflict and continue the rebase using the
'rebase-continue' command or abort using the 'rebase-abort' command.
"""

from ... import transport as _mod_transport
from ...bzr.bzrdir import BzrFormat
from ...commands import plugin_cmds

BzrFormat.register_feature(b"rebase-v1")

from ...i18n import load_plugin_translations

translation = load_plugin_translations("bzr-rewrite")
gettext = translation.gettext

for cmd in [
    "rebase",
    "rebase_abort",
    "rebase_continue",
    "rebase_todo",
    "replay",
    "pseudonyms",
    "rebase_foreign",
]:
    plugin_cmds.register_lazy(f"cmd_{cmd}", [], __name__ + ".commands")


def show_rebase_summary(params):
    """Show rebase status summary in the status output.

    This function is called as a post_status hook to display information
    about any ongoing rebase operation when running 'brz status'.

    Args:
        params: Status hook parameters containing new_tree and to_file attributes.
            The new_tree is the working tree being examined, and to_file is
            where status output should be written.
    """
    if getattr(params.new_tree, "_format", None) is None:
        return
    features = getattr(params.new_tree._format, "features", None)
    if features is None:
        return
    if "rebase-v1" not in features:
        return
    from .rebase import RebaseState1, rebase_todo

    state = RebaseState1(params.new_tree)
    try:
        replace_map = state.read_plan()[1]
    except _mod_transport.NoSuchFile:
        return
    todo = list(rebase_todo(params.new_tree.branch.repository, replace_map))
    params.to_file.write(f"Rebase in progress. ({len(todo)} revisions left)\n")


from ...hooks import install_lazy_named_hook

install_lazy_named_hook(
    "breezy.status", "hooks", "post_status", show_rebase_summary, "rewrite status"
)


def load_tests(loader, basic_tests, pattern):
    """Load test suite for the rewrite plugin.

    This function is called by the test framework to discover and load
    all tests for this plugin.

    Args:
        loader: The test loader instance used to load test modules.
        basic_tests: The test suite to which discovered tests should be added.
        pattern: Pattern for matching test files (unused in this implementation).

    Returns:
        TestSuite: The test suite containing all tests for this plugin.
    """
    testmod_names = [
        "tests",
    ]
    for tmn in testmod_names:
        basic_tests.addTest(loader.loadTestsFromName(f"{__name__}.{tmn}"))
    return basic_tests
