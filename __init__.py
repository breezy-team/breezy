from bzrlib.commands import Command, register_command

class cmd_bash_completion(Command):
    """Generate a shell function for bash command line completion.

    This command generates a shell function which can be used by bash to
    automatically complete the currently typed command when the user presses
    the completion key (usually tab).
    
    Commonly used like this:
        eval "`bzr bash-completion`"
    """
    def run(self):
        import sys
        from bashcomp import bash_completion_function
        bash_completion_function(sys.stdout)

register_command(cmd_bash_completion)
