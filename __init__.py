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
from bzrlib.revisionspec import RevisionSpec, RevisionInfo
from bzrlib.workingtree import WorkingTree
from bzrlib import (
    osutils,
    bzrdir,
    trace,
    )
""")

version_info = (0, 1)

class cmd_grep(Command):
    """Print lines matching PATTERN for specified files.
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
        ]


    @display_command
    def run(self, verbose=False, ignore_case=False, recursive=False, from_root=False,
            null=False, line_number=False, path_list=None, revision=None, pattern=None):
        if path_list == None:
            path_list = ['.']
        else:
            if from_root:
                raise errors.BzrCommandError('cannot specify both --from-root and PATH.')

        print_revno = False
        if revision == None:
            revision = [RevisionSpec.from_string("last:1")]
        else:
            print_revno = True # used to print revno in output.

        start_rev = revision[0]
        end_rev = None
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
        id_to_revno = wt.branch.get_revision_id_to_revno_map()

        rev = start_rev

        wt.lock_read()
        try:
            for path in path_list:
                tree = rev.as_tree(wt.branch)
                revid = rev.as_revision_id(wt.branch)
                try:
                    revno = ".".join([str(n) for n in id_to_revno[revid]])
                except KeyError, e:
                    self._skip_file(path)
                    continue

                if osutils.isdir(path):
                    self._grep_dir(tree, relpath, recursive, line_number,
                        patternc, from_root, eol_marker, revno, print_revno)
                else:
                    id = tree.path2id(path)
                    if not id:
                        self._skip_file(path)
                        continue
                    tree.lock_read()
                    try:
                        grep.file_grep(tree, id, '.', path, patternc, eol_marker,
                            self.outf, line_number, revno, print_revno)
                    finally:
                        tree.unlock()
        finally:
            wt.unlock()

    def _skip_file(self, path):
        trace.warning("warning: skipped unversioned file '%s'." % path)

    def _grep_dir(self, tree, relpath, recursive, line_number, compiled_pattern,
        from_root, eol_marker, revno, print_revno):
            # setup relpath to open files relative to cwd
            rpath = relpath
            if relpath:
                rpath = osutils.pathjoin('..',relpath)

            tree.lock_read()
            try:
                if from_root:
                    # start searching recursively from root
                    relpath=None
                    recursive=True

                for fp, fc, fkind, fid, entry in tree.list_files(include_root=False,
                    from_dir=relpath, recursive=recursive):
                    if fc == 'V' and fkind == 'file':
                        grep.file_grep(tree, fid, rpath, fp, compiled_pattern,
                            eol_marker, self.outf, line_number, revno, print_revno)
            finally:
                tree.unlock()


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

