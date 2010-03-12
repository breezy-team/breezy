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

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import os
import re
import cStringIO

from bzrlib import (
    errors,
    lazy_regex,
    osutils,
    textfile,
    trace,
    )
""")

def compile_pattern(pattern, flags=0):
    patternc = None
    try:
        # use python's re.compile as we need to catch re.error in case of bad pattern
        lazy_regex.reset_compile()
        patternc = re.compile(pattern, flags)
    except re.error, e:
        raise errors.BzrError("Invalid pattern: '%s'" % pattern)
    return patternc

def dir_grep(tree, path, relpath, recursive, line_number, compiled_pattern,
    from_root, eol_marker, revno, print_revno, outf, path_prefix):
        # setup relpath to open files relative to cwd
        rpath = relpath
        if relpath:
            rpath = osutils.pathjoin('..',relpath)

        tree.lock_read()
        try:
            from_dir = osutils.pathjoin(relpath, path)
            if from_root:
                # start searching recursively from root
                from_dir=None
                recursive=True

            for fp, fc, fkind, fid, entry in tree.list_files(include_root=False,
                from_dir=from_dir, recursive=recursive):
                if fc == 'V' and fkind == 'file':
                    versioned_file_grep(tree, fid, rpath, fp,
                        compiled_pattern, eol_marker, line_number,
                        revno, print_revno, outf, path_prefix)
        finally:
            tree.unlock()


def _make_display_path(relpath, path):
    """Return path string relative to user cwd.

    Take tree's 'relpath' and user supplied 'path', and return path
    that can be displayed to the user.
    """
    if relpath:
        # update path so to display it w.r.t cwd
        # handle windows slash separator
        path = osutils.normpath(osutils.pathjoin(relpath, path))
        path = path.replace('\\', '/')
        path = path.replace(relpath + '/', '', 1)
    return path


def versioned_file_grep(tree, id, relpath, path, patternc, eol_marker,
        line_number, revno, print_revno, outf, path_prefix = None):
    """Create a file object for the specified id and pass it on to _file_grep.
    """

    path = _make_display_path(relpath, path)

    # test and skip binary files
    str_file = cStringIO.StringIO(tree.get_file_text(id))
    try:
        file_iter = textfile.text_file(str_file)
    except errors.BinaryFile, e:
        trace.warning("Binary file '%s' skipped." % path)
        return

    _file_grep(file_iter, relpath, path, patternc, eol_marker,
        line_number, revno, print_revno, outf, path_prefix)

def _file_grep(file_iter, relpath, path, patternc, eol_marker,
        line_number, revno, print_revno, outf, path_prefix):

    if path_prefix and path_prefix != '.':
        # user has passed a dir arg, show that as result prefix
        path = osutils.pathjoin(path_prefix, path)

    revfmt = ''
    if print_revno:
        revfmt = "~%s"

    fmt_with_n = path + revfmt + ":%d:%s" + eol_marker
    fmt_without_n = path + revfmt + ":%s" + eol_marker

    # grep through iterable file object and print out the lines
    # matching the compiled pattern in the specified format.
    index = 1
    for line in file_iter:
        res = patternc.search(line)
        if res:
            if line_number:
                if print_revno:
                    out = (revno, index, line.strip())
                else:
                    out = (index, line.strip())
                outf.write(fmt_with_n % out)
            else:
                if print_revno:
                    out = (revno, line.strip())
                else:
                    out = (line.strip(),)
                outf.write(fmt_without_n % out)

        index += 1


