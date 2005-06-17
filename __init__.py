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
    """
    takes_options = ['revision', 'diff-options']
    takes_args = ['file*']
    aliases = ['cset']

    def run(self, revision=None, file_list=None, diff_options=None):
        from bzrlib import find_branch
        import gen_changeset
        import sys

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

        


