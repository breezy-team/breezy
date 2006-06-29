"""A Simple bzr plugin to generate statistics about the history."""

from bzrlib.branch import Branch
import bzrlib.commands
from bzrlib.config import extract_email_address
from bzrlib import errors
from bzrlib.workingtree import WorkingTree


class cmd_statistics(bzrlib.commands.Command):
    """Generate statistics for LOCATION."""

    aliases = ['stats']
    takes_args = ['location?']

    def run(self, location='.'):
        try:
            wt = WorkingTree.open_containing(location)[0]
        except errors.NoWorkingTree:
            b = Branch.open(location)
            last_rev = b.last_revision()
        else:
            b = wt.branch
            last_rev = wt.last_revision()

        committers = {}
        b.lock_read()
        try:
            ancestry = b.repository.get_ancestry(last_rev)
            revisions = b.repository.get_revisions(ancestry[1:])

            for rev in revisions:
                try:
                    email = extract_email_address(rev.committer)
                except errors.BzrError:
                    email = rev.committer
                committers.setdefault(email, []).append(rev)
        finally:
            b.unlock()

        committer_list = sorted(((len(v), k, v) for k,v in committers.iteritems()), reverse=True)
        for count, k, v in committer_list:
            name = v[0].committer
            print '%4d %s' % (count, name)


bzrlib.commands.register_command(cmd_statistics)
