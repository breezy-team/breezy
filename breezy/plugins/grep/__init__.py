# Copyright (C) 2010 Canonical Ltd
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

"""Print lines matching PATTERN for specified files and revisions."""

from __future__ import absolute_import

from ... import version_info  # noqa: F401
from ...commands import plugin_cmds

plugin_cmds.register_lazy("cmd_grep", [], "breezy.plugins.grep.cmds")


def test_suite():
    from ...tests import TestUtil

    suite = TestUtil.TestSuite()
    loader = TestUtil.TestLoader()
    testmod_names = [
        'test_grep',
        ]

    suite.addTest(loader.loadTestsFromModuleNames(
        ["%s.%s" % (__name__, tmn) for tmn in testmod_names]))
    return suite
