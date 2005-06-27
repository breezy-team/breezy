#!/usr/bin/env python
"""\
This is a plugin for the Bazaar-NG revision control system.
"""

import os
import bzrlib, bzrlib.commands

class cmd_rsync_pull(bzrlib.commands.Command):
    """Update the current working tree using rsync.
    With no arguments, look for a .bzr/x-rsync-location file
    to determine which remote system to rsync from.
    Otherwise, you can specify a new location to rsync from.

    Normally the first time you use it, you would write:
        bzr rsync-pull . path/to/otherdirectory
    """
    takes_args = ['local?', 'remote?']
    takes_options = ['verbose']
    aliases = ['rpull']

    def run(self, local=None, remote=None, verbose=True):
        from rsync_update import get_branch_remote_update, \
            check_should_pull, set_default_remote_info, pull

        b, remote, last_revno, last_revision = \
            get_branch_remote_update(local=local, remote=remote)

        if not check_should_pull(b, last_revno, last_revision):
            return 1
        b = pull(b, remote, verbose=verbose)

        set_default_remote_info(b, remote)

class cmd_rsync_pull_bzr(cmd_rsync_pull):
    takes_args = ['remote?']
    def run(self, remote=None, verbose=True):
        from rsync_update import get_branch_remote_update, \
            check_should_pull, set_default_remote_info, pull

        bzr_path = os.path.dirname(bzrlib.__path__[0])
        b, remote, last_revno, last_revision = \
            get_branch_remote_update(local=bzr_path, remote=remote
                , alt_remote='bazaar-ng.org::bazaar-ng/bzr/bzr.dev/')

        if not check_should_pull(b, last_revno, last_revision):
            return 1
        b = pull(b, remote, verbose=verbose)

        set_default_remote_info(b, remote)

class cmd_rsync_push(bzrlib.commands.Command):
    """Update the remote tree using rsync.
    With no arguments, look for a .bzr/x-rsync-location file
    to determine which remote system to rsync to.
    Otherwise, you can specify a new location to rsync to.
    """
    takes_args = ['local?', 'remote?']
    takes_options = ['verbose']
    aliases = ['rpush']

    def run(self, local=None, remote=None, verbose=True):
        from rsync_update import get_branch_remote_update, \
            check_should_push, set_default_remote_info, push

        b, remote, last_revno, last_revision = \
            get_branch_remote_update(local=local, remote=remote)

        if not check_should_push(b, last_revno, last_revision):
            return 1

        push(b, remote, verbose=verbose)

        set_default_remote_info(b, remote)


if hasattr(bzrlib.commands, 'register_plugin_command'):
    bzrlib.commands.register_plugin_command(cmd_rsync_pull)
    bzrlib.commands.register_plugin_command(cmd_rsync_pull_bzr)
    bzrlib.commands.register_plugin_command(cmd_rsync_push)
elif hasattr(bzrlib.commands, 'register_command'):
    bzrlib.commands.register_command(cmd_rsync_pull)
    bzrlib.commands.register_command(cmd_rsync_pull_bzr)
    bzrlib.commands.register_command(cmd_rsync_push)

