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

import bzrlib
import bzrlib.api
from bzrlib.commands import plugin_cmds

version_info = (0, 4, 5, 'dev', 0)
if version_info[3] == 'final':
    version_string = '%d.%d.%d' % version_info[:3]
else:
    version_string = '%d.%d.%d%s%d' % version_info
__version__ = version_string
__author__ = 'Jelmer Vernooij <jelmer@samba.org>'

COMPATIBLE_BZR_VERSIONS = [(1, 13, 0), (1, 15, 0)]

bzrlib.api.require_any_api(bzrlib, COMPATIBLE_BZR_VERSIONS)

for cmd in ["replay", "rebase", "rebase_abort", "rebase_continue",
            "rebase_todo"]:
    plugin_cmds.register_lazy("cmd_%s" % cmd, [], 
        "bzrlib.plugins.rebase.commands")


def test_suite():
    """Determine the testsuite for bzr-rebase."""
    from unittest import TestSuite
    from bzrlib.tests import TestUtil

    loader = TestUtil.TestLoader()
    suite = TestSuite()
    testmod_names = ['test_blackbox', 'test_rebase', 'test_maptree']
    suite.addTest(loader.loadTestsFromModuleNames(
                              ["%s.%s" % (__name__, i) for i in testmod_names]))

    return suite
