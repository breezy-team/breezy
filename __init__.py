# Copyright (C) 2010 Canonical Ltd
# Copyright (C) 2010 Parth Malwankar <parth.malwankar@gmail.com>
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""bzr grep"""

import os
import sys

from bzrlib import errors
from bzrlib.commands import Command, register_command, display_command
from bzrlib.option import (
    Option,
    )

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import re

import grep

import bzrlib
from bzrlib.builtins import _get_revision_range
from bzrlib.revisionspec import RevisionSpec, RevisionSpec_revid
from bzrlib.workingtree import WorkingTree
from bzrlib import log as logcmd
from bzrlib import (
    osutils,
    bzrdir,
    trace,
    )
""")

version_info = (0, 1)

# FIXME: _parse_levels should be shared with bzrlib.builtins. this is a copy
# to avoid the error
#   "IllegalUseOfScopeReplacer: ScopeReplacer object '_parse_levels' was used
#   incorrectly: Object already cleaned up, did you assign it to another
#   variable?: _factory
# with lazy import
def _parse_levels(s):
    try:
        return int(s)
    except ValueError:
        msg = "The levels argument must be an integer."
        raise errors.BzrCommandError(msg)


class cmd_grep(Command):
    """Print lines matching PATTERN for specified files and revisions.

    This command searches the specified files and revisions for a given pattern.
    The pattern is specified as a Python regular expressions[1].
    If the file name is not specified the file revisions in the current directory
    are searched. If the revision number is not specified, the latest revision is
    searched.

    Note that this command is different from POSIX grep in that it searches the
    revisions of the branch and not the working copy. Unversioned files and
    uncommitted changes are not seen.

    When searching a pattern, the output is shown in the 'filepath:string' format.
    If a revision is explicitly searched, the output is shown as 'filepath~N:string',
    where N is the revision number.

    [1] http://docs.python.org/library/re.html#regular-expression-syntax
    """

    takes_args = ['pattern', 'path*']
    takes_options = [
        'verbose',
        'revision',
        Option('line-number', short_name='n',
               help='show 1-based line number.'),
        Option('ignore-case', short_name='i',
               help='ignore case distinctions while matching.'),
        Option('recursive', short_name='R',
               help='Recurse into subdirectories.'),
        Option('from-root',
               help='Search for pattern starting from the root of the branch. '
               '(implies --recursive)'),
        Option('null', short_name='Z',
               help='Write an ascii NUL (\\0) separator '
               'between output lines rather than a newline.'),
        Option('levels',
           help='Number of levels to display - 0 for all, 1 for collapsed (default).',
           argname='N',
           type=_parse_levels),
        ]


    @display_command
    def run(self, verbose=False, ignore_case=False, recursive=False, from_root=False,
            null=False, levels=None, line_number=False, path_list=None, revision=None, pattern=None):

        if levels==None:
            levels=1

        if path_list == None:
            path_list = ['.']
        else:
            if from_root:
                raise errors.BzrCommandError('cannot specify both --from-root and PATH.')

        print_revno = False
        if revision != None or levels == 0:
            # print revision numbers as we may be showing multiple revisions
            print_revno = True

        if revision == None:
            # grep on latest revision by default
            revision = [RevisionSpec.from_string("last:1")]

        start_rev = revision[0]
        end_rev = revision[0]
        if len(revision) == 2:
            end_rev = revision[1]

        eol_marker = '\n'
        if null:
            eol_marker = '\0'

        re_flags = 0
        if ignore_case:
            re_flags = re.IGNORECASE
        patternc = grep.compile_pattern(pattern, re_flags)

        wt, relpath = WorkingTree.open_containing('.')

        start_revid = start_rev.as_revision_id(wt.branch)
        end_revid   = end_rev.as_revision_id(wt.branch)

        given_revs = logcmd._graph_view_revisions(wt.branch, start_revid, end_revid)

        # edge case: we have a repo created with 'bzr init' and it has no
        # revisions (revno: 0)
        try:
            given_revs = list(given_revs)
        except errors.NoSuchRevision, e:
            raise errors.BzrCommandError('No revisions found for grep.')

        for revid, revno, merge_depth in given_revs:
            if levels == 1 and merge_depth != 0:
                # with level=1 show only top level
                continue

            wt.lock_read()
            rev = RevisionSpec_revid.from_string("revid:"+revid)
            try:
                for path in path_list:
                    tree = rev.as_tree(wt.branch)
                    path_for_id = osutils.pathjoin(relpath, path)
                    id = tree.path2id(path_for_id)
                    if not id:
                        self._skip_file(path)
                        continue

                    if osutils.isdir(path):
                        path_prefix = path
                        grep.dir_grep(tree, path, relpath, recursive, line_number,
                            patternc, from_root, eol_marker, revno, print_revno,
                            self.outf, path_prefix)
                    else:
                        tree.lock_read()
                        try:
                            grep.file_grep(tree, id, '.', path, patternc, eol_marker,
                                line_number, revno, print_revno, self.outf)
                        finally:
                            tree.unlock()
            finally:
                wt.unlock()

    def _skip_file(self, path):
        trace.warning("warning: skipped unknown file '%s'." % path)


register_command(cmd_grep)

def test_suite():
    from bzrlib.tests import TestUtil

    suite = TestUtil.TestSuite()
    loader = TestUtil.TestLoader()
    testmod_names = [
        'test_grep',
        ]

    suite.addTest(loader.loadTestsFromModuleNames(
            ["%s.%s" % (__name__, tmn) for tmn in testmod_names]))
    return suite

