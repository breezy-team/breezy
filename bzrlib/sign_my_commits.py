# Copyright (C) 2005, 2006 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""Command which looks for unsigned commits by the current user, and signs them.
"""

from bzrlib.commands import Command
import bzrlib.config
import bzrlib.errors as errors
import bzrlib.gpg
from bzrlib.option import Option


class cmd_sign_my_commits(Command):
    """Sign all commits by a given committer.

    If location is not specified the local tree is used.
    If committer is not specified the default committer is used.

    This does not sign commits that already have signatures.
    """

    takes_options = [Option('dry-run'
                            , help='Don\'t actually sign anything, just print'
                                   ' the revisions that would be signed')
                    ]
    takes_args = ['location?', 'committer?']

    def run(self, location=None, committer=None, dry_run=False):
        if location is None:
            from bzrlib.workingtree import WorkingTree
            # Open the containing directory
            wt = WorkingTree.open_containing('.')[0]
            b = wt.branch
        else:
            # Passed in locations should be exact
            from bzrlib.branch import Branch
            b = Branch.open(location)
        repo = getattr(b, 'repository', b)

        config = bzrlib.config.BranchConfig(b)

        if committer is None:
            committer = config.username()

        gpg_strategy = bzrlib.gpg.GPGStrategy(config)

        count = 0
        # return in partial topological order for the sake of reproducibility
        for rev_id in repo.all_revision_ids():
            if repo.has_signature_for_revision_id(rev_id):
                continue
            
            rev = repo.get_revision(rev_id)
            if rev.committer != committer:
                continue

            # We have a revision without a signature who has a 
            # matching committer, start signing
            print rev_id
            count += 1
            if not dry_run:
                repo.sign_revision(rev_id, gpg_strategy)
        print 'Signed %d revisions' % (count,)


