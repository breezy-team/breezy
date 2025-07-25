# Copyright (C) 2019 Jelmer Vernooij <jelmer@jelmer.uk>
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

__doc__ = """Generate a shell function for zsh command line completion.
"""

from ... import commands, version_info  # noqa: F401

bzr_plugin_name = "zsh_completion"
bzr_commands = ["zsh-completion"]

commands.plugin_cmds.register_lazy("cmd_zsh_completion", [], __name__ + ".zshcomp")


def load_tests(loader, basic_tests, pattern):
    testmod_names = [
        "tests",
    ]
    for tmn in testmod_names:
        basic_tests.addTest(loader.loadTestsFromName(f"{__name__}.{tmn}"))
    return basic_tests
