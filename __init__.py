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

from bzrlib import errors, lazy_regex
from bzrlib.commands import Command, register_command, display_command
from bzrlib.option import (
    Option,
    )

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import re

import bzrlib
from bzrlib import (
    bzrdir,
    )
""")

version_info = (0, 1)

class cmd_grep(Command):
    """Print lines matching PATTERN for specified files.
    """

    takes_args = ['pattern', 'path*']
    takes_options = [
        'verbose',
        Option('line-number', short_name='n',
               help='prefix each line of output with 1-based line number.'),
        Option('ignore-case', short_name='i',
               help='ignore case distinctions while matching.'),
        Option('recursive', short_name='R',
               help='Recurse into subdirectories.'),
        Option('from-root',
               help='Search for pattern starting from the root of the branch.'),
        ]


    @display_command
    def run(self, verbose=False, line_number=False, null=False,
            ignore_case=False, recursive=False, from_root=False,
            path_list=None, pattern=None):
        if path_list == None:
            path_list = ['.']
        else:
            if from_root:
                raise errors.BzrCommandError('cannot specify both --from-root and PATH.')

        print 'pattern:', pattern
        print 'path_list:', path_list
        print 'line-number:', line_number
        print 'null:', null
        print 'recursive:', recursive
        print 'from-root:', from_root
        print '=' * 20

        tree, branch, relpath = bzrdir.BzrDir.open_containing_tree_or_branch('.')

        re_flags = 0
        if ignore_case:
            re_flags = re.IGNORECASE

        patternc = None

        try:
            # use python's re.compile as we need to catch re.error in case of bad pattern
            lazy_regex.reset_compile()
            patternc = re.compile(pattern, re_flags)
        except re.error, e:
            raise errors.BzrError("Invalid pattern: '%s'" % pattern)

        tree.lock_read()
        self.add_cleanup(tree.unlock)
        for path in path_list:
            for fp, fc, fkind, fid, entry in tree.list_files(include_root=False,
                from_dir=relpath, recursive=recursive):
                print 'fp:', fp
                print 'fc:', fc
                print 'fkind:', fkind
                print 'fid:', fid
                print 'entry:', entry
                if fc == 'V' and fkind == 'file':
                    self.file_grep(fp, patternc)
                print '~' * 30

    def file_grep(self, path, patternc):
        index = 1
        for line in open(path):
            res = patternc.search(line)
            if res:
                self.outf.write("%s:%d:%s\n" % (path, index, line.strip()))
            index += 1

register_command(cmd_grep)

