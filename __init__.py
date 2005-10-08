"""\
Push to and pull from SVN repositories
"""
import bzrlib.commands
import push
import annotate
import shelf
import sys
import os.path
sys.path.append(os.path.dirname(__file__))

class cmd_svnpush(bzrlib.commands.Command):
    """Push to a SVN repository
    """
    takes_args = ['repository']
    def run(self, repository):
        pass #FIXME

class cmd_svnpull(bzrlib.commands.Command):
    """Pull from a SVN repository
    """
    takes_args = ['repository']
    def run(self, repository):
        pass #FIXME

commands = [cmd_svnpush, cmd_svnpull]

if hasattr(bzrlib.commands, 'register_command'):
    for command in commands:
        bzrlib.commands.register_command(command)
