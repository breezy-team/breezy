#!/usr/bin/env python
"""\
This is an attempt to take the internal delta object, and represent
it as a single-file text-only changeset.
This should have commands for both generating a changeset,
and for applying a changeset.
"""

import sys
from bzrlib.commands import Command, register_command
from bzrlib.branch import Branch
from bzrlib.revisionspec import RevisionSpec
from bzrlib.option import Option
from bzrlib.revision import (common_ancestor, MultipleRevisionSources,
                             get_intervening_revisions, NULL_REVISION)
import bzrlib.errors as errors

class cmd_send_changeset(Command):
    """Send a bundled up changset via mail.

    If no revision has been specified, the last commited change will
    be sent.

    Subject of the mail can be specified by the --message option,
    otherwise information from the changeset log will be used.

    A editor will be spawned where the user may enter a description
    of the changeset.  The description can be read from a file with
    the --file FILE option.
    """
    takes_options = ['revision', 'message', 'file']
    takes_args = ['to?']

    def run(self, to=None, message=None, revision=None, file=None):
        from bzrlib.errors import BzrCommandError
        from send_changeset import send_changeset
        
        if isinstance(revision, (list, tuple)):
            if len(revision) > 1:
                raise BzrCommandError('We do not support rollup-changesets yet.')
            revision = revision[0]

        b = Branch.open_containing('.')

        if not to:
            try:
                to = b.controlfile('x-send-address', 'rb').read().strip('\n')
            except:
                raise BzrCommandError('destination address is not known')

        if not isinstance(revision, (list, tuple)):
            revision = [revision]

        send_changeset(b, revision, to, message, file)


class cmd_changeset(Command):
    """Generate a bundled up changeset.

    This changeset contains all of the meta-information of a
    diff, rather than just containing the patch information.

    bzr cset
        - Changeset for the last commit
    bzr cset BASE
        - Changeset to apply the current tree into BASE
    bzr cset --revision A
        - Changeset for revision A
    bzr cset --revision A..B
        - Changeset to transform A into B
    bzr cset --revision A..B BASE
        - Changeset to transform revision A of BASE into revision B
          of the local tree
    """
    takes_options = ['verbose', 'revision']
    takes_args = ['base?']
    aliases = ['cset']

    def run(self, base=None, revision=None):
        from bzrlib import user_encoding
        from bzrlib.changeset.serializer import write
        from bzrlib.fetch import fetch

        if base is None:
            base_branch = None
        else:
            base_branch = Branch.open(base)

        # We don't want to lock the same branch across
        # 2 different branches
        target_branch = Branch.open_containing(u'.')[0]
        if base_branch is not None and target_branch.base == base_branch.base:
            base_branch = None

        base_revision = None
        if revision is None:
            target_revision = target_branch.last_revision()
            if base_branch is not None:
                base_revision = base_branch.last_revision()
        elif len(revision) == 1:
            target_revision = revision[0].in_history(target_branch).rev_id
            if base_branch is not None:
                base_revision = base_branch.last_revision()
        elif len(revision) == 2:
            target_revision = revision[0].in_history(target_branch).rev_id
            if base_branch is not None:
                base_revision = revision[1].in_history(base_branch).rev_id
            else:
                base_revision = revision[1].in_history(target_branch).rev_id
        else:
            raise errors.BzrCommandError('--revision takes 1 or 2 parameters')

        if base_revision is None:
            rev = target_branch.get_revision(target_revision)
            if rev.parent_ids:
                base_revision = rev.parent_ids[0]
            else:
                base_revision = NULL_REVISION

        if base_branch is not None:
            fetch(target_branch, base_branch, base_revision)
            del base_branch
        revision_id_list = get_intervening_revisions(target_revision, base_revision,
                target_branch, target_branch.revision_history())
                
        write(target_branch, revision_id_list, sys.stdout)


class cmd_verify_changeset(Command):
    """Read a written changeset, and make sure it is valid.

    """
    takes_args = ['filename?']

    def run(self, filename=None):
        from read_changeset import read_changeset
        #from bzrlib.xml import serializer_v4

        b, relpath = Branch.open_containing('.')

        if filename is None or filename == '-':
            f = sys.stdin
        else:
            f = open(filename, 'U')

        cset_info, cset_tree = read_changeset(f, b)
        # print cset_info
        # print cset_tree
        #serializer_v4.write(cset_tree.inventory, sys.stdout)



class cmd_apply_changeset(Command):
    """Read in the given changeset, and apply it to the
    current tree.

    """
    takes_args = ['filename?']
    takes_options = [Option('reverse'), Option('auto-commit')]

    def run(self, filename=None, reverse=False, auto_commit=False):
        import apply_changeset

        b, relpath = Branch.open_containing('.') # Make sure we are in a branch
        if filename is None or filename == '-':
            f = sys.stdin
        else:
            # Actually, we should not use Universal newlines
            # as this potentially modifies the patch.
            # though it seems mailers save attachments with their
            # own format of the files.
            f = open(filename, 'rb')

        apply_changeset.apply_changeset(b, f, reverse=reverse,
                auto_commit=auto_commit)


register_command(cmd_changeset)
register_command(cmd_verify_changeset)
register_command(cmd_apply_changeset)
register_command(cmd_send_changeset)

#OPTIONS['reverse'] = None
#OPTIONS['auto-commit'] = None

def test_suite():
    from doctest import DocTestSuite
    from unittest import TestSuite, TestLoader
    import test_changeset
    import common
    import patches

    suite = TestSuite()

    suite.addTest(TestLoader().loadTestsFromModule(test_changeset))
    suite.addTest(TestLoader().loadTestsFromModule(patches))
    suite.addTest(DocTestSuite(common))

    return suite


