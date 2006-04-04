# Copyright (C) 2006 by Canonical Ltd

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

"""builtin bzr commands relating to individual weave files

These should never normally need to be used by end users, but might be
of interest in debugging or data recovery.
"""

import sys

from bzrlib.commands import Command
from bzrlib.trace import mutter, warning

class cmd_weave_list(Command):
    """List the revision ids present in a weave, in alphabetical order"""

    hidden = True
    takes_args = ['weave_filename']

    def run(self, weave_filename):
        from bzrlib.weavefile import read_weave
        weave = read_weave(file(weave_filename, 'rb'))
        names = weave.versions()
        names.sort()
        print '\n'.join(names)


class cmd_weave_join(Command):
    """Join the contents of two weave files.

    The resulting weave is sent to stdout.

    This command is only intended for bzr developer use.
    """

    hidden = True
    takes_args = ['weave1', 'weave2']

    def run(self, weave1, weave2):
        from bzrlib.weavefile import read_weave, write_weave
        w1 = read_weave(file(weave1, 'rb'))
        w2 = read_weave(file(weave2, 'rb'))
        w1.join(w2)
        write_weave(w1, sys.stdout)


class cmd_weave_plan_merge(Command):
    """Show the plan for merging two versions within a weave"""
    hidden = True
    takes_args = ['weave_file', 'revision_a', 'revision_b']

    def run(self, weave_file, revision_a, revision_b):
        from bzrlib.weavefile import read_weave, write_weave
        w = read_weave(file(weave_file, 'rb'))
        for state, line in w.plan_merge(revision_a, revision_b):
            # make sure to print every line with a newline, even if it doesn't
            # really have one
            if not line:
                continue
            if line[-1] != '\n':
                state += '!eol'
                line += '\n'
            if '\n' in line[:-1]:
                warning("line in weave contains embedded newline: %r" % line)
            print '%15s | %s' % (state, line),

class cmd_weave_merge_text(Command):
    """Debugging command to merge two texts of a weave"""
    hidden = True
    takes_args = ['weave_file', 'revision_a', 'revision_b']

    def run(self, weave_file, revision_a, revision_b):
        from bzrlib.weavefile import read_weave, write_weave
        w = read_weave(file(weave_file, 'rb'))
        p = w.plan_merge(revision_a, revision_b)
        sys.stdout.writelines(w.weave_merge(p))
