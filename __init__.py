"""Generate a shell function for bash command line completion.

This plugin provides a command called bash-completion that generates a
bash completion function for bzr. See its documentation for details.
"""

from bzrlib.commands import Command, register_command
from bzrlib.option import Option

class cmd_bash_completion(Command):
    """Generate a shell function for bash command line completion.

    This command generates a shell function which can be used by bash to
    automatically complete the currently typed command when the user presses
    the completion key (usually tab).
    
    Commonly used like this:
        eval "`bzr bash-completion`"
    """

    takes_options = [
        Option("function-name", short_name="f", type=str, argname="name",
               help="Name of the generated function (default: _bzr)"),
        Option("function-only", short_name="o", type=None,
               help="Generate only the shell function, don't enable it"),
        ]

    def run(self, **kwargs):
        import sys
        from bashcomp import bash_completion_function
        bash_completion_function(sys.stdout, **kwargs)

register_command(cmd_bash_completion)
