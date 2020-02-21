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

"""Some commands for debugging and repairing bzr repositories.

Some of these commands may be good candidates for adding to bzr itself, perhaps
as hidden commands.
"""

from ... import version_info  # noqa: F401
from ...commands import plugin_cmds


def test_suite():
    from unittest import TestSuite
    from .tests import test_suite
    result = TestSuite()
    result.addTest(test_suite())
    return result


plugin_cmds.register_lazy(
    'cmd_check_chk', [], __name__ + '.check_chk')
plugin_cmds.register_lazy(
    'cmd_chk_used_by', [], __name__ + '.chk_used_by')
plugin_cmds.register_lazy(
    'cmd_fetch_all_records', [], __name__ + '.fetch_all_records')
plugin_cmds.register_lazy(
    'cmd_file_refs', [], __name__ + '.file_refs')
plugin_cmds.register_lazy(
    'cmd_fix_missing_keys_for_stacking', [],
    __name__ + '.missing_keys_for_stacking_fixer')
plugin_cmds.register_lazy(
    'cmd_mirror_revs_into', [],
    __name__ + '.missing_keys_for_stacking_fixer')
plugin_cmds.register_lazy(
    'cmd_repo_has_key', [], __name__ + '.repo_has_key')
plugin_cmds.register_lazy(
    'cmd_repo_keys', [], __name__ + '.repo_keys')
