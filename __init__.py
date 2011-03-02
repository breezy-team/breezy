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

from info import (
    bzr_commands,
    bzr_plugin_version as version_info,
    bzr_compatible_versions,
    )

if version_info[3] == 'final':
    version_string = '%d.%d.%d' % version_info[:3]
else:
    version_string = '%d.%d.%d%s%d' % version_info
__version__ = version_string
__author__ = 'Jelmer Vernooij <jelmer@samba.org>'

bzrlib.api.require_any_api(bzrlib, bzr_compatible_versions)

if __name__ == 'bzrlib.plugins.rebase':
    raise ImportError("The rebase plugin has been renamed to rewrite. Please rename the directory in ~/.bazaar/plugins")

for cmd in bzr_commands:
    plugin_cmds.register_lazy("cmd_%s" % cmd, [],
        "bzrlib.plugins.rewrite.commands")


def test_suite():
    """Returns the testsuite for bzr-rewrite."""
    from unittest import TestSuite
    from bzrlib.plugins.rewrite import tests
    suite = TestSuite()
    suite.addTest(tests.test_suite())
    return suite
