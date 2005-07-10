#!/usr/bin/env python
"""\
This is an attempt to take the internal delta object, and represent
it as a single-file text-only changeset.
This should have commands for both generating a changeset,
and for applying a changeset.
"""

import bzrlib, bzrlib.commands

class cmd_send_changeset(bzrlib.commands.Command):
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
        from bzrlib import find_branch
        from bzrlib.errors import BzrCommandError
        from send_changeset import send_changeset
        
        if isinstance(revision, (list, tuple)):
            if len(revision) > 1:
                raise BzrCommandError('We do not support rollup-changesets yet.')
            revision = revision[0]

        b = find_branch('.')

        if not to:
            try:
                to = b.controlfile('x-send-address', 'rb').read().strip('\n')
            except:
                raise BzrCommandError('destination address is not known')

        if not isinstance(revision, (list, tuple)):
            revision = [revision]

        send_changeset(b, revision, to, message, file)

class cmd_changeset(bzrlib.commands.Command):
    """Generate a bundled up changeset.

    This changeset contains all of the meta-information of a
    diff, rather than just containing the patch information.

    BASE - This is the target tree with which you want to merge.
           It will be used as the base for all patches. Anyone
           wanting to merge the changeset will be required to have BASE
    TARGET - This is the final revision which is desired to be in the
             changeset. It defaults to the last committed revision. './@'
    STARTING-REV-ID - All revisions between STARTING-REV and TARGET will
                      be bundled up in the changeset. By default this is
                      chosen as the merge root.
                      (NOT Implemented yet)


    If --verbose, renames will be given as an 'add + delete' style patch.
    """
    takes_options = ['verbose']
    takes_args = ['base?', 'target?', 'starting-rev-id?']
    aliases = ['cset']

    def run(self, base=None, target=None, starting_rev_id=None, verbose=False):
        from bzrlib import find_branch
        from bzrlib.commands import parse_spec
        from bzrlib.errors import BzrCommandError
        import gen_changeset
        import sys
        import codecs

        if target is None:
            target = './@'
        b_target_path, target_revno = parse_spec(target)
        target_branch = find_branch(b_target_path)
        if target_revno is None or target_revno == -1:
            target_rev_id = target_branch.last_patch()
        else:
            target_rev_id = target_branch.lookup_revision(target_revno)

        if base is None:
            base_branch = target_branch
            target_rev = target_branch.get_revision(target_rev_id)
            base_rev_id = target_rev.parents[0].revision_id
        else:
            base_path, base_revno = parse_spec(base)
            base_branch = find_branch(base_path)
            if base_revno is None or base_revno == -1:
                base_rev_id = base_branch.last_patch()
            else:
                base_rev_id = base_branch.last_patch()

        outf = codecs.getwriter(bzrlib.user_encoding)(sys.stdout,
                errors='replace')

        if starting_rev_id is not None:
            raise BzrCommandError('Specifying the STARTING-REV-ID'
                    ' not yet supported')

        gen_changeset.show_changeset(base_branch, base_rev_id,
                target_branch, target_rev_id,
                starting_rev_id,
                to_file=outf, include_full_diff=verbose)

class cmd_verify_changeset(bzrlib.commands.Command):
    """Read a written changeset, and make sure it is valid.

    """
    takes_args = ['filename?']

    def run(self, filename=None):
        import sys, read_changeset
        from cStringIO import StringIO
        from bzrlib.xml import pack_xml
        from bzrlib.branch import find_branch
        from bzrlib.osutils import sha_file, pumpfile

        b = find_branch('.')

        if filename is None or filename == '-':
            f = sys.stdin
        else:
            f = open(filename, 'U')

        cset_info, cset_tree, cset_inv = read_changeset.read_changeset(f, b)
        print cset_info
        print cset_tree
        pack_xml(cset_inv, sys.stdout)



class cmd_apply_changeset(bzrlib.commands.Command):
    """Read in the given changeset, and apply it to the
    current tree.

    """
    takes_args = ['filename?']
    takes_options = ['reverse', 'auto-commit']

    def run(self, filename=None, reverse=False, auto_commit=False):
        from bzrlib import find_branch
        import sys
        import apply_changeset

        b = find_branch('.') # Make sure we are in a branch
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

class cmd_test_plugins(bzrlib.commands.Command):
    """Test every plugin that supports tests.

    """
    takes_args = []
    takes_options = []

    def run(self):
        import test
        test.test()

bzrlib.commands.register_command(cmd_changeset)
bzrlib.commands.register_command(cmd_verify_changeset)
bzrlib.commands.register_command(cmd_apply_changeset)
bzrlib.commands.register_command(cmd_send_changeset)
bzrlib.commands.register_command(cmd_test_plugins)

bzrlib.commands.OPTIONS['reverse'] = None
bzrlib.commands.OPTIONS['auto-commit'] = None
