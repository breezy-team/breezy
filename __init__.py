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

        pb = bzrlib.ui.ui_factory.nested_progress_bar()
        committers = {}
        b.lock_read()
        try:
            pb.note('getting ancestry')
            ancestry = b.repository.get_ancestry(last_rev)[1:]
            pb.note('getting revisions')
            revisions = b.repository.get_revisions(ancestry)

            for count, rev in enumerate(revisions):
                pb.update('checking', count, len(ancestry))
                try:
                    email = extract_email_address(rev.committer)
                except errors.BzrError:
                    email = rev.committer
                committers.setdefault(email, []).append(rev)
        finally:
            b.unlock()
        pb.clear()

        committer_list = sorted(((len(v), k, v) for k,v in committers.iteritems()), reverse=True)
        for count, k, v in committer_list:
            name = v[0].committer
            print '%4d %s' % (count, name)


bzrlib.commands.register_command(cmd_statistics)
