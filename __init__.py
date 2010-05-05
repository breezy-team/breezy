# Copyright (C) 2009, 2010  Martin von Gagern
#
# This file is part of bzr-bash-completion
#
# bzr-bash-completion free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation, either version 2 of the
# License, or (at your option) any later version.
#
# bzr-bash-completion is distributed in the hope that it will be
# useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Generate a shell function for bash command line completion.

This plugin provides a command called bash-completion that generates a
bash completion function for bzr. See its documentation for details.
"""

from meta import *
from meta import __version__

from bzrlib import commands, option


class cmd_bash_completion(commands.Command):
    """Generate a shell function for bash command line completion.

    This command generates a shell function which can be used by bash to
    automatically complete the currently typed command when the user presses
    the completion key (usually tab).
    
    Commonly used like this:
        eval "`bzr bash-completion`"
    """

    takes_options = [
        option.Option("function-name", short_name="f", type=str, argname="name",
               help="Name of the generated function (default: _bzr)"),
        option.Option("function-only", short_name="o", type=None,
               help="Generate only the shell function, don't enable it"),
        option.Option("debug", type=None, hidden=True,
               help="Enable shell code useful for debugging"),
        option.ListOption("plugin", type=str, argname="name",
                # param_name="selected_plugins", # doesn't work, bug #387117
                help="Enable completions for the selected plugin"
                + " (default: all plugins)"),
        ]

    def run(self, **kwargs):
        import sys
        from bashcomp import bash_completion_function
        if 'plugin' in kwargs:
            # work around bug #387117 which prevents us from using param_name
            if len(kwargs['plugin']) > 0:
                kwargs['selected_plugins'] = kwargs['plugin']
            del kwargs['plugin']
        bash_completion_function(sys.stdout, **kwargs)


commands.register_command(cmd_bash_completion)


def load_tests(basic_tests, module, loader):
    testmod_names = [
        'tests',
        ]
    basic_tests.addTest(loader.loadTestsFromModuleNames(
            ["%s.%s" % (__name__, tmn) for tmn in testmod_names]))
    return basic_tests
