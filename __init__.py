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
        from bzrlib.commands import BzrCommandError
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

    It will store it into FILENAME if supplied, otherwise it writes
    to stdout

    Right now, rollup changesets, or working tree changesets are
    not supported. This will only generate a changeset that has been
    committed. You can use "--revision" to specify a certain change
    to display.
    """
    takes_options = ['revision']
    takes_args = ['filename?']
    aliases = ['cset']

    def run(self, revision=None, filename=None):
        from bzrlib import find_branch
        import gen_changeset
        import sys
        import codecs

        if filename is None or filename == '-':
            outf = codecs.getwriter(bzrlib.user_encoding)(sys.stdout, errors='replace')
        else:
            f = open(filename, 'wb')
            outf = codecs.getwriter(bzrlib.user_encoding)(f, errors='replace')

        if not isinstance(revision, (list, tuple)):
            revision = [revision]
        b = find_branch('.')

        gen_changeset.show_changeset(b, revision, to_file=outf)

class cmd_verify_changeset(bzrlib.commands.Command):
    """Read a written changeset, and make sure it is valid.

    """
    takes_args = ['filename?']

    def run(self, filename=None):
        import sys, read_changeset
        if filename is None or filename == '-':
            f = sys.stdin
        else:
            f = open(filename, 'U')

        cset_info = read_changeset.read_changeset(f)
        print cset_info
        cset = cset_info.get_changeset()
        print cset.entries

class cmd_apply_changeset(bzrlib.commands.Command):
    """Read in the given changeset, and apply it to the
    current tree.

    """
    takes_args = ['filename?']
    takes_options = []

    def run(self, filename=None, reverse=False, auto_commit=False):
        from bzrlib import find_branch
        import sys
        import apply_changeset

        b = find_branch('.') # Make sure we are in a branch
        if filename is None or filename == '-':
            f = sys.stdin
        else:
            f = open(filename, 'U') # Universal newlines

        apply_changeset.apply_changeset(b, f, reverse=reverse,
                auto_commit=auto_commit)


bzrlib.commands.register_command(cmd_changeset)
bzrlib.commands.register_command(cmd_verify_changeset)
bzrlib.commands.register_command(cmd_apply_changeset)
bzrlib.commands.register_command(cmd_send_changeset)

bzrlib.commands.OPTIONS['reverse'] = None
bzrlib.commands.OPTIONS['auto-commit'] = None
cmd_apply_changeset.takes_options.append('reverse')
cmd_apply_changeset.takes_options.append('auto-commit')
