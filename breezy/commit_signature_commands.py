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

"""Command that signs unsigned commits by the current user."""

from . import controldir, errors, gpg
from . import repository as _mod_repository
from . import revision as _mod_revision
from .commands import Command
from .i18n import gettext, ngettext
from .option import Option


class cmd_sign_my_commits(Command):
    """Sign all commits by a given committer.

    If location is not specified the local tree is used.
    If committer is not specified the default committer is used.

    This does not sign commits that already have signatures.
    """

    # Note that this signs everything on the branch's ancestry
    # (both mainline and merged), but not other revisions that may be in the
    # repository

    takes_options = [
        Option(
            "dry-run",
            help="Don't actually sign anything, just print"
            " the revisions that would be signed.",
        ),
    ]
    takes_args = ["location?", "committer?"]

    def run(self, location=None, committer=None, dry_run=False):
        """Sign all commits by the specified committer.

        Args:
            location: The location of the branch to sign commits in. If None,
                uses the current directory.
            committer: The email address of the committer whose commits should
                be signed. If None, uses the email from branch config.
            dry_run: If True, only print which revisions would be signed
                without actually signing them.

        Returns:
            None
        """
        if location is None:
            bzrdir = controldir.ControlDir.open_containing(".")[0]
        else:
            # Passed in locations should be exact
            bzrdir = controldir.ControlDir.open(location)
        branch = bzrdir.open_branch()
        repo = branch.repository
        branch_config = branch.get_config_stack()

        if committer is None:
            committer = branch_config.get("email")
        gpg_strategy = gpg.GPGStrategy(branch_config)

        count = 0
        with repo.lock_write():
            graph = repo.get_graph()
            with _mod_repository.WriteGroup(repo):
                for rev_id, parents in graph.iter_ancestry([branch.last_revision()]):
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
                    self.outf.write(f"{rev_id}\n")
                    count += 1
                    if not dry_run:
                        repo.sign_revision(rev_id, gpg_strategy)
        self.outf.write(
            ngettext("Signed %d revision.\n", "Signed %d revisions.\n", count) % count
        )


class cmd_verify_signatures(Command):
    """Verify all commit signatures.

    Verifies that all commits in the branch are signed by known GnuPG keys.
    """

    takes_options = [
        Option(
            "acceptable-keys",
            help="Comma separated list of GPG key patterns which are"
            " acceptable for verification.",
            short_name="k",
            type=str,
        ),
        "revision",
        "verbose",
    ]
    takes_args = ["location?"]

    def run(self, acceptable_keys=None, revision=None, verbose=None, location="."):
        """Verify signatures on commits in the branch.

        Args:
            acceptable_keys: Comma separated list of GPG key patterns which are
                acceptable for verification. If None, all keys are acceptable.
            revision: Specific revision or revision range to verify. If None,
                verifies all revisions in the branch.
            verbose: If True, show detailed information about each signature.
            location: The location of the branch to verify. Defaults to current
                directory.

        Returns:
            int: 0 if all commits are signed with verifiable keys, 1 otherwise.
        """
        bzrdir = controldir.ControlDir.open_containing(location)[0]
        branch = bzrdir.open_branch()
        repo = branch.repository
        branch_config = branch.get_config_stack()
        gpg_strategy = gpg.GPGStrategy(branch_config)

        gpg_strategy.set_acceptable_keys(acceptable_keys)

        def write(string):
            """Write a line to stdout.

            Args:
                string: The string to write.
            """
            self.outf.write(string + "\n")

        def write_verbose(string):
            """Write an indented verbose line to stdout.

            Args:
                string: The string to write with indentation.
            """
            self.outf.write("  " + string + "\n")

        self.add_cleanup(repo.lock_read().unlock)
        # get our list of revisions
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
                    raise errors.CommandError(
                        gettext(
                            "Cannot verify a range of non-revision-history revisions"
                        )
                    )
                for revno in range(from_revno, to_revno + 1):
                    revisions.append(branch.get_rev_id(revno))
        else:
            # all revisions by default including merges
            graph = repo.get_graph()
            revisions = []
            for rev_id, parents in graph.iter_ancestry([branch.last_revision()]):
                if _mod_revision.is_null(rev_id):
                    continue
                if parents is None:
                    # Ignore ghosts
                    continue
                revisions.append(rev_id)
        count, result, all_verifiable = gpg.bulk_verify_signatures(
            repo, revisions, gpg_strategy
        )
        if all_verifiable:
            write(gettext("All commits signed with verifiable keys"))
            if verbose:
                for message in gpg.verbose_valid_message(result):
                    write_verbose(message)
            return 0
        else:
            write(gpg.valid_commits_message(count))
            if verbose:
                for message in gpg.verbose_valid_message(result):
                    write_verbose(message)
            write(gpg.expired_commit_message(count))
            if verbose:
                for message in gpg.verbose_expired_key_message(result, repo):
                    write_verbose(message)
            write(gpg.unknown_key_message(count))
            if verbose:
                for message in gpg.verbose_missing_key_message(result):
                    write_verbose(message)
            write(gpg.commit_not_valid_message(count))
            if verbose:
                for message in gpg.verbose_not_valid_message(result, repo):
                    write_verbose(message)
            write(gpg.commit_not_signed_message(count))
            if verbose:
                for message in gpg.verbose_not_signed_message(result, repo):
                    write_verbose(message)
            return 1
