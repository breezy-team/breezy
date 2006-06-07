#!/usr/bin/env python
"""\
This is an attempt to take the internal delta object, and represent
it as a single-file text-only changeset.
This should have commands for both generating a changeset,
and for applying a changeset.
"""

import sys

from bzrlib.branch import Branch
from bzrlib.commands import Command, register_command
import bzrlib.errors as errors
from bzrlib.option import Option
from bzrlib.revision import (common_ancestor, MultipleRevisionSources,
                             NULL_REVISION)
from bzrlib.revisionspec import RevisionSpec


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


class cmd_bundle_revisions(Command):
    """Generate a revision bundle.

    This bundle contains all of the meta-information of a
    diff, rather than just containing the patch information.

    You can apply it to another tree using 'bzr merge'.

    bzr bundle-revisions
        - Bundle for the last commit
    bzr bundle-revisions BASE
        - Bundle to apply the current tree into BASE
    bzr bundle-revisions --revision A
        - Bundle for revision A
    bzr bundle-revisions --revision A..B
        - Bundle to transform A into B
    bzr bundle-revisions --revision A..B BASE
        - Bundle to transform revision A of BASE into revision B
          of the local tree
    """
    takes_options = ['verbose', 'revision',
                     Option("output", help="write bundle to specified file",
                            type=unicode)]
    takes_args = ['base?']
    aliases = ['bundle']

    def run(self, base=None, revision=None, output=None):
        from bzrlib import user_encoding
        from bzrlib.bundle.serializer import write_bundle

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
        elif len(revision) == 1:
            target_revision = revision[0].in_history(target_branch).rev_id
            if base_branch is not None:
                base_revision = base_branch.last_revision()
        elif len(revision) == 2:
            target_revision = revision[1].in_history(target_branch).rev_id
            if base_branch is not None:
                base_revision = revision[0].in_history(base_branch).rev_id
            else:
                base_revision = revision[0].in_history(target_branch).rev_id
        else:
            raise errors.BzrCommandError('--revision takes 1 or 2 parameters')

        if revision is None or len(revision) == 1:
            if base_branch is not None:
                target_branch.repository.fetch(base_branch.repository, 
                                               base_branch.last_revision())
                base_revision = common_ancestor(base_branch.last_revision(),
                                                target_revision,
                                                target_branch.repository)
                if base_revision is None:
                    base_revision = NULL_REVISION

        if base_revision is None:
            rev = target_branch.repository.get_revision(target_revision)
            if rev.parent_ids:
                base_revision = rev.parent_ids[0]
            else:
                base_revision = NULL_REVISION

        if base_branch is not None:
            target_branch.repository.fetch(base_branch.repository, 
                                           revision_id=base_revision)
            del base_branch

        if output is not None:
            fileobj = file(output, 'wb')
        else:
            fileobj = sys.stdout
        write_bundle(target_branch.repository, target_revision, base_revision,
                     fileobj)


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
