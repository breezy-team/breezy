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
        Option('ignore-case', short_name='i',
               help='ignore case distinctions while matching.'),
        Option('recursive', short_name='R',
               help='Recurse into subdirectories.'),
        Option('from-root',
               help='Search for pattern starting from the root of the branch.'),
        Option('null', short_name='z',
               help='Write an ascii NUL (\\0) separator '
               'between output lines rather than a newline.'),
        ]


    @display_command
    def run(self, verbose=False, ignore_case=False, recursive=False, from_root=False,
            null=False, path_list=None, pattern=None):
        if path_list == None:
            path_list = ['.']
        else:
            if from_root:
                raise errors.BzrCommandError('cannot specify both --from-root and PATH.')

        eol_marker = '\n'
        if null:
            eol_marker = '\0'

        re_flags = 0
        if ignore_case:
            re_flags = re.IGNORECASE
        patternc = grep.compile_pattern(pattern, re_flags)

        for path in path_list:
            tree, branch, relpath = bzrdir.BzrDir.open_containing_tree_or_branch(path)

            if osutils.isdir(path):
                # setup rpath to open files relative to cwd
                rpath = relpath
                if relpath:
                    rpath = os.path.join('..',relpath)

                tree.lock_read()
                try:
                    for fp, fc, fkind, fid, entry in tree.list_files(include_root=False,
                        from_dir=relpath, recursive=recursive):
                        if fc == 'V' and fkind == 'file':
                            grep.file_grep(rpath, fp, patternc, eol_marker, outf=self.outf)
                finally:
                    tree.unlock()
            else:
                # if user has explicitly specified a file
                # we don't care if its versioned
                if not tree.path2id(path):
                    trace.warning("warning: file '%s' is not versioned." % path)
                grep.file_grep('.', path, patternc, eol_marker, outf=self.outf)

register_command(cmd_grep)

