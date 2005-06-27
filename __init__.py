#!/usr/bin/env python
"""\
Remove the last committed revision.
Does not modify the working tree, use 'bzr revert' for that.
"""

import bzrlib, bzrlib.commands

class cmd_uncommit(bzrlib.commands.Command):
    """Remove the last committed revision.

    By supplying the --remove flag, it will not only remove the entry 
    from revision_history, but also remove all of the entries in the
    stores.

    --verbose will print out what is being removed.
    --dry-run will go through all the motions, but not actually
    remove anything.
    
    In the future, uncommit will create a changeset, which can then
    be re-applied.
    """
    takes_options = ['remove', 'dry-run', 'verbose']
    takes_args = ['location?']
    aliases = []

    def run(self, location=None, remove=False,
            dry_run=False, verbose=False):
        from bzrlib.branch import find_branch
        from bzrlib.log import log_formatter
        import uncommit, sys

        if location is None:
            location = '.'
        b = find_branch(location)

        revno = b.revno()
        rev_id = b.last_patch()
        if rev_id is None:
            print 'No revisions to uncommit.'

        lf = log_formatter('short', to_file=sys.stdout,timezone='original')
        lf.show(revno, b.get_revision(rev_id), None)

        print 'The above revision will be removed.'
        val = raw_input('Are you sure [y/N]? ')
        if val.lower() not in ('y', 'yes'):
            print 'Canceled'
            return 0

        uncommit.uncommit(b, remove_files=remove,
                dry_run=dry_run, verbose=verbose)

bzrlib.commands.register_command(cmd_uncommit)
bzrlib.commands.OPTIONS['remove'] = None
bzrlib.commands.OPTIONS['dry-run'] = None
