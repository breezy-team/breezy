# Copyright (C) 2005 Canonical Ltd
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

"""Tests for some coding style conventions of the bazaar code base."""

import re
import sys
from StringIO import StringIO
import warnings

from bzrlib import (
    diff,
    osutils,
    patiencediff,
    textfile,
    )
from bzrlib.tests import TestCase
from bzrlib.workingtree import WorkingTree


def internal_diff(old_filename, oldlines, new_filename, newlines, to_file,
                  allow_binary=False, sequence_matcher=None,
                  path_encoding='utf8'):
    # Special workaround for Python2.3, where difflib fails if
    # both sequences are empty.
    if not oldlines and not newlines:
        return

    if allow_binary is False:
        textfile.check_text_lines(oldlines)
        textfile.check_text_lines(newlines)

    if sequence_matcher is None:
        sequence_matcher = patiencediff.PatienceSequenceMatcher

    started = [False] #trick to access parent scoped variable
    def start_if_needed():
        if not started[0]:
            to_file.write('+++ %s\n' % new_filename)
            started[0] = True

    def check_newlines(j1, j2):
        for i, line in enumerate(newlines[j1:j2]):
            bad_ws_match = re.match(r'^(([\t]*)(.*?)([\t ]*))(\r?\n)?$', line)
            if bad_ws_match:
                line_content = bad_ws_match.group(1)
                has_leading_tabs = bool(bad_ws_match.group(2))
                has_trailing_whitespace = bool(bad_ws_match.group(4))
                if has_leading_tabs:
                    start_if_needed()
                    to_file.write('line %i has leading tabs: "%s"\n'% (
                        i+1+j1, line_content))
                if has_trailing_whitespace:
                    start_if_needed()
                    to_file.write('line %i has trailing whitespace: "%s"\n'% (
                        i+1+j1, line_content))
                if len(line_content) > 79:
                    warnings.warn(
                        '\nFile %s\nline %i is longer than 79 characters:'
                        ' "%s"\n'% (new_filename, i+1+j1, line_content))

    for group in sequence_matcher(None, oldlines, newlines
            ).get_grouped_opcodes(0):
        for tag, i1, i2, j1, j2 in group:
            if tag == 'replace' or tag == 'insert':
                check_newlines(j1, j2)

    if len(newlines) == j2 and not newlines[j2-1].endswith('\n'):
        start_if_needed()
        to_file.write("\\ No newline at end of file\n")

class TestCodingStyle(TestCase):

    def test_coding_style(self):
        """ Check if bazaar code conforms to some coding style conventions.

            Currently we check all .py files for:
            * new trailing white space
            * new leading tabs
            * new long lines (give warning only)
            * no newline at end of files
        """
        bzr_dir = osutils.dirname(osutils.realpath(sys.argv[0]))
        wt = WorkingTree.open(bzr_dir)
        diff_output = StringIO()
        wt.lock_read()
        try:
            new_tree = wt
            old_tree = new_tree.basis_tree()

            old_tree.lock_read()
            new_tree.lock_read()
            try:
                iterator = new_tree.iter_changes(old_tree, specific_files=None,
                    extra_trees=None, require_versioned=False)
                for (file_id, paths, changed_content, versioned, parent,
                    name, kind, executable) in iterator:
                    if (changed_content and kind[1] == 'file'
                        and paths[1].endswith('.py')):
                        diff_text = diff.DiffText(old_tree, new_tree,
                            to_file=diff_output, text_differ=internal_diff)
                        diff_text.diff(file_id, paths[0], paths[1],
                            kind[0], kind[1])
            finally:
                old_tree.unlock()
                new_tree.unlock()
        finally:
            wt.unlock()
        if len(diff_output.getvalue()) > 0:
            self.fail("Unacceptable coding style:\n" + diff_output.getvalue())
