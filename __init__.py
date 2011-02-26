# Copyright (C) 2006-2010 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""A Simple bzr plugin to generate statistics about the history."""

from bzrlib import _format_version_tuple

from info import (
    bzr_plugin_version  as version_info,
    )

__version__ = _format_version_tuple(version_info)


from bzrlib.commands import plugin_cmds

plugin_cmds.register_lazy("cmd_credits", [],
    "bzrlib.plugins.stats.cmds")
plugin_cmds.register_lazy("cmd_committer_statistics",
    ['stats', 'committer-stats'], "bzrlib.plugins.stats.cmds")
plugin_cmds.register_lazy("cmd_ancestor_growth", [],
    "bzrlib.plugins.stats.cmds")

def load_tests(basic_tests, module, loader):
    testmod_names = [__name__ + '.' + x for x in [
        'test_classify',
        'test_stats',
        ]]
    suite = loader.suiteClass()
    suite.addTest(loader.loadTestsFromModuleNames(testmod_names))
    return suite

