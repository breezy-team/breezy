# Copyright (C) 2006, 2007, 2009, 2010, 2011 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Command which looks for unsigned commits by the current user, and signs them.
"""

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    bzrdir as _mod_bzrdir,
    errors,
    gpg,
    revision as _mod_revision,
    )
""")
from bzrlib.commands import Command
from bzrlib.option import Option
from bzrlib.i18n import gettext, ngettext

class cmd_sign_my_commits(Command):
    __doc__ = """Sign all commits by a given committer.

    If location is not specified the local tree is used.
    If committer is not specified the default committer is used.

    This does not sign commits that already have signatures.
    """
    # Note that this signs everything on the branch's ancestry
    # (both mainline and merged), but not other revisions that may be in the
    # repository

    takes_options = [
            Option('dry-run',
                   help='Don\'t actually sign anything, just print'
                        ' the revisions that would be signed.'),
            ]
    takes_args = ['location?', 'committer?']

    def run(self, location=None, committer=None, dry_run=False):
        if location is None:
            bzrdir = _mod_bzrdir.BzrDir.open_containing('.')[0]
        else:
            # Passed in locations should be exact
            bzrdir = _mod_bzrdir.BzrDir.open(location)
        branch = bzrdir.open_branch()
        repo = branch.repository
        branch_config = branch.get_config()

        if committer is None:
            committer = branch_config.username()
        gpg_strategy = gpg.GPGStrategy(branch_config)

        count = 0
        repo.lock_write()
        try:
            graph = repo.get_graph()
            repo.start_write_group()
            try:
                for rev_id, parents in graph.iter_ancestry(
                        [branch.last_revision()]):
                    if _mod_revision.is_null(rev_id):
                        continue
                    if parents is None:
                        # Ignore ghosts
                        continue
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
            except:
                repo.abort_write_group()
                raise
            else:
                repo.commit_write_group()
        finally:
            repo.unlock()
        print 'Signed %d revisions' % (count,)


class cmd_verify_signatures(Command):
    __doc__ = """Verify all commit signatures.

    Verifies that all commits in the branch are signed by known GnuPG keys.
    """

    takes_options = [
            Option('acceptable-keys',
                   help='Comma separated list of GPG key patterns which are'
                        ' acceptable for verification.',
                   short_name='k',
                   type=str,),
            'revision', 
            'verbose',
          ]
    takes_args = ['location?']

    def run(self, acceptable_keys=None, revision=None, verbose=None,
                                                            location=u'.'):
        bzrdir = _mod_bzrdir.BzrDir.open_containing(location)[0]
        branch = bzrdir.open_branch()
        repo = branch.repository
        branch_config = branch.get_config()
        gpg_strategy = gpg.GPGStrategy(branch_config)

        gpg_strategy.set_acceptable_keys(acceptable_keys)

        def write(string):
            self.outf.write(string + "\n")
        def write_verbose(string):
            self.outf.write("  " + string + "\n")

        #get our list of revisions
        revisions = []
        if revision is not None:
            if len(revision) == 1:
                revno, rev_id = revision[0].in_history(branch)
                revisions.append(rev_id)
            elif len(revision) == 2:
                from_revno, from_revid = revision[0].in_history(branch)
                to_revno, to_revid = revision[1].in_history(branch)
                if to_revid is None:
                    to_revno = branch.revno()
                if from_revno is None or to_revno is None:
                    raise errors.BzrCommandError('Cannot verify a range of '\
                                               'non-revision-history revisions')
                for revno in range(from_revno, to_revno + 1):
                    revisions.append(branch.get_rev_id(revno))
        else:
            #all revisions by default including merges
            graph = repo.get_graph()
            revisions = []
            repo.lock_read()
            for rev_id, parents in graph.iter_ancestry(
                    [branch.last_revision()]):
                if _mod_revision.is_null(rev_id):
                    continue
                if parents is None:
                    # Ignore ghosts
                    continue
                revisions.append(rev_id)
            repo.unlock()
        count, result, all_verifiable =\
                                gpg_strategy.do_verifications(revisions, repo)
        if all_verifiable:
               write(gettext(
                            "All commits signed with verifiable keys"))
               if verbose:
                   write(gpg_strategy.verbose_valid_message(result))
               return 0
        else:
            write(gpg_strategy.valid_commits_message(count))
            if verbose:
               for message in gpg_strategy.verbose_valid_message(result):
                   write_verbose(message)
            write(gpg_strategy.unknown_key_message(count))
            if verbose:
                for message in gpg_strategy.verbose_missing_key_message(result):
                    write_verbose(message)
            write(gpg_strategy.commit_not_valid_message(count))
            if verbose:
                for message in gpg_strategy.verbose_not_valid_message(result,
                                                                        repo):
                   write_verbose(message)
            write(gpg_strategy.commit_not_signed_message(count))
            if verbose:
                for message in gpg_strategy.verbose_not_signed_message(result,
                                                                          repo):
                    write_verbose(message)
            return 1
