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
import codecs
import cStringIO
from fnmatch import fnmatch
import os
import re

from bzrlib import log as logcmd
from bzrlib import bzrdir
from bzrlib.workingtree import WorkingTree
from bzrlib.revisionspec import RevisionSpec, RevisionSpec_revid
from bzrlib import (
    errors,
    lazy_regex,
    osutils,
    textfile,
    trace,
    )
""")

_terminal_encoding = osutils.get_terminal_encoding()
_user_encoding = osutils.get_user_encoding()

def compile_pattern(pattern, flags=0):
    patternc = None
    try:
        # use python's re.compile as we need to catch re.error in case of bad pattern
        lazy_regex.reset_compile()
        patternc = re.compile(pattern, flags)
    except re.error, e:
        raise errors.BzrError("Invalid pattern: '%s'" % pattern)
    return patternc

def is_fixed_string(s):
    if re.match("^([A-Za-z0-9]|\s)*$", s):
        return True
    return False

def versioned_grep(revision, pattern, compiled_pattern, path_list, recursive,
        line_number, from_root, eol_marker, print_revno, levels,
        include, exclude, verbose, fixed_string, ignore_case, outf):

    wt, relpath = WorkingTree.open_containing('.')

    # We do an optimization below. For grepping a specific revison
    # We don't need to call _graph_view_revisions which is slow.
    # We create the start_rev_tuple for only that specific revision.
    # _graph_view_revisions is used only for revision range.
    start_rev = revision[0]
    start_revid = start_rev.as_revision_id(wt.branch)
    srevno_tuple = wt.branch.revision_id_to_dotted_revno(start_revid)
    start_revno = '.'.join(map(str, srevno_tuple))
    start_rev_tuple = (start_revid, start_revno, 0)

    if len(revision) == 2:
        end_rev = revision[1]
        end_revid   = end_rev.as_revision_id(wt.branch)
        given_revs = logcmd._graph_view_revisions(wt.branch, start_revid, end_revid)
    else:
        given_revs = [start_rev_tuple]

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
                    trace.warning("Skipped unknown file '%s'." % path)
                    continue

                if osutils.isdir(path):
                    path_prefix = path
                    dir_grep(tree, path, relpath, recursive, line_number,
                        pattern, compiled_pattern, from_root, eol_marker,
                        revno, print_revno, include, exclude, verbose,
                        fixed_string, ignore_case, outf, path_prefix)
                else:
                    versioned_file_grep(tree, id, '.', path,
                        pattern, compiled_pattern, eol_marker, line_number,
                        revno, print_revno, include, exclude, verbose,
                        fixed_string, ignore_case, outf)
        finally:
            wt.unlock()

def workingtree_grep(pattern, compiled_pattern, path_list, recursive,
        line_number, from_root, eol_marker, include, exclude, verbose,
        fixed_string, ignore_case, outf):
    revno = print_revno = None # for working tree set revno to None

    tree, branch, relpath = \
        bzrdir.BzrDir.open_containing_tree_or_branch('.')
    tree.lock_read()
    try:
        for path in path_list:
            if osutils.isdir(path):
                path_prefix = path
                dir_grep(tree, path, relpath, recursive, line_number,
                    pattern, compiled_pattern, from_root, eol_marker, revno,
                    print_revno, include, exclude, verbose, fixed_string,
                    ignore_case, outf, path_prefix)
            else:
                _file_grep(open(path).read(), '.', path, pattern,
                    compiled_pattern, eol_marker, line_number, revno,
                    print_revno, include, exclude, verbose,
                    fixed_string, ignore_case, outf)
    finally:
        tree.unlock()

def _skip_file(include, exclude, path):
    if include and not _path_in_glob_list(path, include):
        return True
    if exclude and _path_in_glob_list(path, exclude):
        return True
    return False


def dir_grep(tree, path, relpath, recursive, line_number, pattern,
        compiled_pattern, from_root, eol_marker, revno, print_revno,
        include, exclude, verbose, fixed_string, ignore_case, outf, path_prefix):
    # setup relpath to open files relative to cwd
    rpath = relpath
    if relpath:
        rpath = osutils.pathjoin('..',relpath)

    from_dir = osutils.pathjoin(relpath, path)
    if from_root:
        # start searching recursively from root
        from_dir=None
        recursive=True

    to_grep = []
    for fp, fc, fkind, fid, entry in tree.list_files(include_root=False,
        from_dir=from_dir, recursive=recursive):

        if _skip_file(include, exclude, fp):
            continue

        if fc == 'V' and fkind == 'file':
            if revno != None:
                to_grep.append((fid, fp))
            else:
                # we are grepping working tree.
                if from_dir == None:
                    from_dir = '.'

                path_for_file = osutils.pathjoin(tree.basedir, from_dir, fp)
                file_text = codecs.open(path_for_file, 'r').read()
                _file_grep(file_text, rpath, fp,
                    pattern, compiled_pattern, eol_marker, line_number, revno,
                    print_revno, include, exclude, verbose, fixed_string,
                    ignore_case, outf, path_prefix)

    if revno != None: # grep versioned files
        for path, chunks in tree.iter_files_bytes(to_grep):
            path = _make_display_path(relpath, path)
            _file_grep(chunks[0], rpath, path, pattern, compiled_pattern,
                eol_marker, line_number, revno, print_revno, include,
                exclude, verbose, fixed_string, ignore_case, outf,
                path_prefix)

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


def versioned_file_grep(tree, id, relpath, path, pattern, patternc,
        eol_marker, line_number, revno, print_revno, include, exclude,
        verbose, fixed_string, ignore_case, outf, path_prefix = None):
    """Create a file object for the specified id and pass it on to _file_grep.
    """

    path = _make_display_path(relpath, path)
    file_text = tree.get_file_text(id)
    _file_grep(file_text, relpath, path, pattern, patternc, eol_marker,
        line_number, revno, print_revno, include, exclude, verbose,
        fixed_string, ignore_case, outf, path_prefix)

def _path_in_glob_list(path, glob_list):
    present = False
    for glob in glob_list:
        if fnmatch(path, glob):
            present = True
            break
    return present


def _file_grep(file_text, relpath, path, pattern, patternc, eol_marker,
        line_number, revno, print_revno, include, exclude, verbose,
        fixed_string, ignore_case, outf, path_prefix=None):

    pattern = pattern.encode(_user_encoding, 'replace')
    if fixed_string and ignore_case:
        pattern = pattern.lower()

    # test and skip binary files
    if '\x00' in file_text[:1024]:
        if verbose:
            trace.warning("Binary file '%s' skipped." % path)
        return

    if path_prefix and path_prefix != '.':
        # user has passed a dir arg, show that as result prefix
        path = osutils.pathjoin(path_prefix, path)

    path = path.encode(_terminal_encoding, 'replace')

    # for better performance we moved formatting conditionals out
    # of the core loop. hence, the core loop is somewhat duplicated
    # for various combinations of formatting options.

    if print_revno and line_number:

        pfmt = "~%s:%d:%s".encode(_terminal_encoding)
        if fixed_string:
            for index, line in enumerate(file_text.splitlines()):
                if ignore_case:
                    line = line.lower()
                if pattern in line:
                    line = line.decode(_terminal_encoding, 'replace')
                    outf.write(path + (pfmt % (revno, index+1, line)) + eol_marker)
        else:
            for index, line in enumerate(file_text.splitlines()):
                if patternc.search(line):
                    line = line.decode(_terminal_encoding, 'replace')
                    outf.write(path + (pfmt % (revno, index+1, line)) + eol_marker)

    elif print_revno and not line_number:

        pfmt = "~%s:%s".encode(_terminal_encoding, 'replace')
        if fixed_string:
            for line in file_text.splitlines():
                if ignore_case:
                    line = line.lower()
                if pattern in line:
                    line = line.decode(_terminal_encoding, 'replace')
                    outf.write(path + (pfmt % (revno, line)) + eol_marker)
        else:
            for line in file_text.splitlines():
                if patternc.search(line):
                    line = line.decode(_terminal_encoding, 'replace')
                    outf.write(path + (pfmt % (revno, line)) + eol_marker)

    elif not print_revno and line_number:

        pfmt = ":%d:%s".encode(_terminal_encoding)
        if fixed_string:
            for index, line in enumerate(file_text.splitlines()):
                if ignore_case:
                    line = line.lower()
                if pattern in line:
                    line = line.decode(_terminal_encoding, 'replace')
                    outf.write(path + (pfmt % (index+1, line)) + eol_marker)
        else:
            for index, line in enumerate(file_text.splitlines()):
                if patternc.search(line):
                    line = line.decode(_terminal_encoding, 'replace')
                    outf.write(path + (pfmt % (index+1, line)) + eol_marker)

    else:

        pfmt = ":%s".encode(_terminal_encoding)
        if fixed_string:
            for line in file_text.splitlines():
                if ignore_case:
                    line = line.lower()
                if pattern in line:
                    line = line.decode(_terminal_encoding, 'replace')
                    outf.write(path + (pfmt % (line,)) + eol_marker)
        else:
            for line in file_text.splitlines():
                if patternc.search(line):
                    line = line.decode(_terminal_encoding, 'replace')
                    outf.write(path + (pfmt % (line,)) + eol_marker)

