
from bzrlib.command import Command

class cmd_rebase(Command):
    """Re-base a branch.

    """
    takes_args = ['upstream']
    takes_options = [Option('onto', help='Different revision to replay onto')]
    
    @display_command
    def run(self, upstream, onto=None):
        pass

