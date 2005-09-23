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
    takes_options = ['remove', 'dry-run', 'verbose', 'revision']
    takes_args = ['location?']
    aliases = []

    def run(self, location=None, remove=False,
            dry_run=False, verbose=False,
            revision=None):
        from bzrlib.branch import Branch
        from bzrlib.log import log_formatter
        import uncommit, sys

        if location is None:
            location = '.'
        b = Branch.open_containing(location)

        if revision is None:
            revno = b.revno()
            rev_id = b.last_patch()
        else:
            revno, rev_id = revision[0].in_history(b)
        if rev_id is None:
            print 'No revisions to uncommit.'

        for r in range(revno, b.revno()+1):
            rev_id = b.get_rev_id(revno)
            lf = log_formatter('short', to_file=sys.stdout,show_timezone='original')
            lf.show(r, b.get_revision(rev_id), None)

        if dry_run:
            print 'Dry-run, pretending to remove the above revisions.'
            val = raw_input('Press <enter> to continue')
        else:
            print 'The above revision(s) will be removed.'
            val = raw_input('Are you sure [y/N]? ')
            if val.lower() not in ('y', 'yes'):
                print 'Canceled'
                return 0

        uncommit.uncommit(b, remove_files=remove,
                dry_run=dry_run, verbose=verbose,
                revno=revno)

bzrlib.commands.register_command(cmd_uncommit)
bzrlib.commands.OPTIONS['remove'] = None
bzrlib.commands.OPTIONS['dry-run'] = None
