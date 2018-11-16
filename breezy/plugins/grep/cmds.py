# Copyright (C) 2010 Canonical Ltd
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

"""Print lines matching PATTERN for specified files and revisions."""

from __future__ import absolute_import

from ... import errors
from ...commands import Command, display_command
from ...option import Option, ListOption
from ...config import GlobalConfig

from ...sixish import (
    text_type,
    )

# FIXME: _parse_levels should be shared with breezy.builtins. this is a copy
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


class GrepOptions(object):
    """Container to pass around grep options.

    This class is used as a container to pass around user option and
    some other params (like outf) to processing functions. This makes
    it easier to add more options as grep evolves.
    """
    verbose = False
    ignore_case = False
    no_recursive = False
    from_root = False
    null = False
    levels = None
    line_number = False
    path_list = None
    revision = None
    pattern = None
    include = None
    exclude = None
    fixed_string = False
    files_with_matches = False
    files_without_match = False
    color = None
    diff = False

    # derived options
    recursive = None
    eol_marker = None
    patternc = None
    sub_patternc = None
    print_revno = None
    fixed_string = None
    outf = None
    show_color = False


class cmd_grep(Command):
    """Print lines matching PATTERN for specified files and revisions.

    This command searches the specified files and revisions for a given
    pattern.  The pattern is specified as a Python regular expressions[1].

    If the file name is not specified, the revisions starting with the
    current directory are searched recursively. If the revision number is
    not specified, the working copy is searched. To search the last committed
    revision, use the '-r -1' or '-r last:1' option.

    Unversioned files are not searched unless explicitly specified on the
    command line. Unversioned directores are not searched.

    When searching a pattern, the output is shown in the 'filepath:string'
    format. If a revision is explicitly searched, the output is shown as
    'filepath~N:string', where N is the revision number.

    --include and --exclude options can be used to search only (or exclude
    from search) files with base name matches the specified Unix style GLOB
    pattern.  The GLOB pattern an use *, ?, and [...] as wildcards, and \\
    to quote wildcard or backslash character literally. Note that the glob
    pattern is not a regular expression.

    [1] http://docs.python.org/library/re.html#regular-expression-syntax
    """

    encoding_type = 'replace'
    takes_args = ['pattern', 'path*']
    takes_options = [
        'verbose',
        'revision',
        Option('color', type=text_type, argname='when',
               help='Show match in color. WHEN is never, always or auto.'),
        Option('diff', short_name='p',
               help='Grep for pattern in changeset for each revision.'),
        ListOption('exclude', type=text_type, argname='glob', short_name='X',
                   help="Skip files whose base name matches GLOB."),
        ListOption('include', type=text_type, argname='glob', short_name='I',
                   help="Search only files whose base name matches GLOB."),
        Option('files-with-matches', short_name='l',
               help='Print only the name of each input file in '
               'which PATTERN is found.'),
        Option('files-without-match', short_name='L',
               help='Print only the name of each input file in '
               'which PATTERN is not found.'),
        Option('fixed-string', short_name='F',
               help='Interpret PATTERN is a single fixed string (not regex).'),
        Option('from-root',
               help='Search for pattern starting from the root of the branch. '
               '(implies --recursive)'),
        Option('ignore-case', short_name='i',
               help='ignore case distinctions while matching.'),
        Option('levels',
               help='Number of levels to display - 0 for all, 1 for collapsed '
               '(1 is default).',
               argname='N',
               type=_parse_levels),
        Option('line-number', short_name='n',
               help='show 1-based line number.'),
        Option('no-recursive',
               help="Don't recurse into subdirectories. (default is --recursive)"),
        Option('null', short_name='Z',
               help='Write an ASCII NUL (\\0) separator '
               'between output lines rather than a newline.'),
        ]

    @display_command
    def run(self, verbose=False, ignore_case=False, no_recursive=False,
            from_root=False, null=False, levels=None, line_number=False,
            path_list=None, revision=None, pattern=None, include=None,
            exclude=None, fixed_string=False, files_with_matches=False,
            files_without_match=False, color=None, diff=False):
        from breezy import _termcolor
        from . import grep
        import re
        if path_list is None:
            path_list = ['.']
        else:
            if from_root:
                raise errors.BzrCommandError(
                    'cannot specify both --from-root and PATH.')

        if files_with_matches and files_without_match:
            raise errors.BzrCommandError('cannot specify both '
                                         '-l/--files-with-matches and -L/--files-without-matches.')

        global_config = GlobalConfig()

        if color is None:
            color = global_config.get_user_option('grep_color')

        if color is None:
            color = 'never'

        if color not in ['always', 'never', 'auto']:
            raise errors.BzrCommandError('Valid values for --color are '
                                         '"always", "never" or "auto".')

        if levels == None:
            levels = 1

        print_revno = False
        if revision != None or levels == 0:
            # print revision numbers as we may be showing multiple revisions
            print_revno = True

        eol_marker = '\n'
        if null:
            eol_marker = '\0'

        if not ignore_case and grep.is_fixed_string(pattern):
            # if the pattern isalnum, implicitly use to -F for faster grep
            fixed_string = True
        elif ignore_case and fixed_string:
            # GZ 2010-06-02: Fall back to regexp rather than lowercasing
            #                pattern and text which will cause pain later
            fixed_string = False
            pattern = re.escape(pattern)

        patternc = None
        re_flags = re.MULTILINE
        if ignore_case:
            re_flags |= re.IGNORECASE

        if not fixed_string:
            patternc = grep.compile_pattern(
                pattern.encode(grep._user_encoding), re_flags)

        if color == 'always':
            show_color = True
        elif color == 'never':
            show_color = False
        elif color == 'auto':
            show_color = _termcolor.allow_color()

        GrepOptions.verbose = verbose
        GrepOptions.ignore_case = ignore_case
        GrepOptions.no_recursive = no_recursive
        GrepOptions.from_root = from_root
        GrepOptions.null = null
        GrepOptions.levels = levels
        GrepOptions.line_number = line_number
        GrepOptions.path_list = path_list
        GrepOptions.revision = revision
        GrepOptions.pattern = pattern
        GrepOptions.include = include
        GrepOptions.exclude = exclude
        GrepOptions.fixed_string = fixed_string
        GrepOptions.files_with_matches = files_with_matches
        GrepOptions.files_without_match = files_without_match
        GrepOptions.color = color
        GrepOptions.diff = False

        GrepOptions.eol_marker = eol_marker
        GrepOptions.print_revno = print_revno
        GrepOptions.patternc = patternc
        GrepOptions.recursive = not no_recursive
        GrepOptions.fixed_string = fixed_string
        GrepOptions.outf = self.outf
        GrepOptions.show_color = show_color

        if diff:
            # options not used:
            # files_with_matches, files_without_match
            # levels(?), line_number, from_root
            # include, exclude
            # These are silently ignored.
            grep.grep_diff(GrepOptions)
        elif revision is None:
            grep.workingtree_grep(GrepOptions)
        else:
            grep.versioned_grep(GrepOptions)
