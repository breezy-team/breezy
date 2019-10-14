# Copyright (C) 2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Management of hosted branches."""

from __future__ import absolute_import

from ... import version_info  # noqa: F401
from ...commands import plugin_cmds

plugin_cmds.register_lazy("cmd_propose_merge", ["propose"], __name__ + ".cmds")
plugin_cmds.register_lazy("cmd_publish_derived", ['publish'], __name__ + ".cmds")
plugin_cmds.register_lazy("cmd_find_merge_proposal", ['find-proposal'], __name__ + ".cmds")
plugin_cmds.register_lazy("cmd_github_login", ["gh-login"], __name__ + ".cmds")
plugin_cmds.register_lazy("cmd_gitlab_login", ["gl-login"], __name__ + ".cmds")
plugin_cmds.register_lazy(
    "cmd_my_merge_proposals", ["my-proposals"],
    __name__ + ".cmds")
