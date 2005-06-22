#!/usr/bin/env python
"""\
This is an attempt to take the internal delta object, and represent
it as a single-file text-only changeset.
This should have commands for both generating a changeset,
and for applying a changeset.
"""

import bzrlib, bzrlib.commands

class cmd_changeset(bzrlib.commands.Command):
    """Generate a bundled up changeset.

    This changeset contains all of the meta-information of a
    diff, rather than just containing the patch information.

    Right now, rollup changesets, or working tree changesets are
    not supported. This will only generate a changeset that has been
    committed. You can use "--revision" to specify a certain change
    to display.
    """
    takes_options = ['revision', 'diff-options']
    takes_args = ['file*']
    aliases = ['cset']

    def run(self, revision=None, file_list=None, diff_options=None):
        from bzrlib import find_branch
        import gen_changeset
        import sys

        if isinstance(revision, (list, tuple)):
            if len(revision) > 1:
                raise BzrCommandError('We do not support rollup-changesets yet.')
            revision = revision[0]
        if file_list:
            b = find_branch(file_list[0])
            file_list = [b.relpath(f) for f in file_list]
            if file_list == ['']:
                # just pointing to top-of-tree
                file_list = None
        else:
            b = find_branch('.')

        gen_changeset.show_changeset(b, revision,
                specific_files=file_list,
                external_diff_options=diff_options,
                to_file=sys.stdout)

class cmd_verify_changeset(bzrlib.commands.Command):
    """Read a written changeset, and make sure it is valid.

    """
    takes_args = ['filename?']

    def run(self, filename=None):
        import sys, read_changeset
        if filename is None or filename == '-':
            f = sys.stdin
        else:
            f = open(filename, 'rb')

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
            f = open(filename, 'rb')

        apply_changeset.apply_changeset(b, f, reverse=reverse,
                auto_commit=auto_commit)


if hasattr(bzrlib.commands, 'register_plugin_cmd'):
    bzrlib.commands.register_plugin_cmd(cmd_changeset)
    bzrlib.commands.register_plugin_cmd(cmd_verify_changeset)
    bzrlib.commands.register_plugin_cmd(cmd_apply_changeset)

    bzrlib.commands.OPTIONS['reverse'] = None
    bzrlib.commands.OPTIONS['auto-commit'] = None
    cmd_apply_changeset.takes_options.append('reverse')
    cmd_apply_changeset.takes_options.append('auto-commit')

