# Copyright (C) 2009, 2010 Canonical Ltd
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

__doc__ = """Generate a shell function for bash command line completion.

This plugin provides a command called bash-completion that generates a
bash completion function for bzr. See its documentation for details.
"""

from ... import commands, version_info  # noqa: F401


bzr_plugin_name = 'bash_completion'
bzr_commands = ['bash-completion']

commands.plugin_cmds.register_lazy('cmd_bash_completion', [],
                                   'breezy.plugins.bash_completion.bashcomp')


def load_tests(loader, basic_tests, pattern):
    testmod_names = [
        'tests',
        ]
    basic_tests.addTest(loader.loadTestsFromModuleNames(
        ["%s.%s" % (__name__, tmn) for tmn in testmod_names]))
    return basic_tests
