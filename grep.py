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
from fnmatch import fnmatch

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

def compile_pattern(pattern, flags=0):
    patternc = None
    try:
        # use python's re.compile as we need to catch re.error in case of bad pattern
        lazy_regex.reset_compile()
        patternc = re.compile(pattern, flags)
    except re.error, e:
        raise errors.BzrError("Invalid pattern: '%s'" % pattern)
    return patternc


def versioned_grep(revision, compiled_pattern, path_list, recursive,
        line_number, from_root, eol_marker, print_revno, levels,
        include, exclude, verbose, outf):

    wt, relpath = WorkingTree.open_containing('.')

    start_rev = revision[0]
    end_rev = revision[0]
    if len(revision) == 2:
        end_rev = revision[1]

    start_revid = start_rev.as_revision_id(wt.branch)
    end_revid   = end_rev.as_revision_id(wt.branch)

    given_revs = logcmd._graph_view_revisions(wt.branch, start_revid, end_revid)
    given_revs = list(given_revs)

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
                        compiled_pattern, from_root, eol_marker, revno, print_revno,
                        include, exclude, verbose, outf, path_prefix)
                else:
                    tree.lock_read()
                    try:
                        versioned_file_grep(tree, id, '.', path,
                            compiled_pattern, eol_marker, line_number, revno,
                            print_revno, include, exclude, verbose, outf)
                    finally:
                        tree.unlock()
        finally:
            wt.unlock()

def workingtree_grep(compiled_pattern, path_list, recursive,
        line_number, from_root, eol_marker, include, exclude, verbose, outf):
    revno = print_revno = None # for working tree set revno to None
    for path in path_list:
        tree, branch, relpath = \
            bzrdir.BzrDir.open_containing_tree_or_branch('.')
        if osutils.isdir(path):
            path_prefix = path
            dir_grep(tree, path, relpath, recursive, line_number,
                compiled_pattern, from_root, eol_marker, revno, print_revno,
                include, exclude, verbose, outf, path_prefix)
        else:
            _file_grep(open(path).read(), '.', path, compiled_pattern,
                eol_marker, line_number, revno, print_revno, include,
                exclude, verbose, outf)

def dir_grep(tree, path, relpath, recursive, line_number, compiled_pattern,
        from_root, eol_marker, revno, print_revno, include, exclude, verbose,
        outf, path_prefix):
    # setup relpath to open files relative to cwd
    rpath = relpath
    if relpath:
        rpath = osutils.pathjoin('..',relpath)

    from_dir = osutils.pathjoin(relpath, path)
    if from_root:
        # start searching recursively from root
        from_dir=None
        recursive=True

    tree.lock_read()
    try:
        for fp, fc, fkind, fid, entry in tree.list_files(include_root=False,
            from_dir=from_dir, recursive=recursive):

            if fc == 'V' and fkind == 'file':
                if revno != None:
                    versioned_file_grep(tree, fid, rpath, fp,
                        compiled_pattern, eol_marker, line_number,
                        revno, print_revno, include, exclude, verbose,
                        outf, path_prefix)
                else:
                    # we are grepping working tree.
                    if from_dir == None:
                        from_dir = '.'

                    path_for_file = osutils.pathjoin(tree.basedir, from_dir, fp)
                    _file_grep(open(path_for_file).read(), rpath, fp,
                        compiled_pattern, eol_marker, line_number, revno,
                        print_revno, include, exclude, verbose, outf, path_prefix)
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
        line_number, revno, print_revno, include, exclude, verbose, outf,
        path_prefix = None):
    """Create a file object for the specified id and pass it on to _file_grep.
    """

    path = _make_display_path(relpath, path)
    file_text = tree.get_file_text(id)
    _file_grep(file_text, relpath, path, patternc, eol_marker,
        line_number, revno, print_revno, include, exclude, verbose,
        outf, path_prefix)

def _path_in_glob_list(path, glob_list):
    present = False
    for glob in glob_list:
        if fnmatch(path, glob):
            present = True
            break
    return present

def _file_grep(file_text, relpath, path, patternc, eol_marker, line_number,
        revno, print_revno, include, exclude, verbose, outf, path_prefix=None):

    # test and skip binary files
    if '\x00' in file_text[:1024]:
        if verbose:
            trace.warning("Binary file '%s' skipped." % path)
        return

    if include and not _path_in_glob_list(path, include):
        return

    if exclude and _path_in_glob_list(path, exclude):
        return

    if path_prefix and path_prefix != '.':
        # user has passed a dir arg, show that as result prefix
        path = osutils.pathjoin(path_prefix, path)

    fmt = path + ":%s" + eol_marker
    fmt_n = path + ":%d:%s" + eol_marker
    fmt_rev = path + "~%s:%s" + eol_marker
    fmt_rev_n = path + "~%s:%d:%s" + eol_marker

    # for better performance we moved formatting conditionals out
    # of the core loop. hence, the core loop is somewhat duplicated
    # for various combinations of formatting options.

    if print_revno and line_number:

        pfmt = fmt_rev_n
        for index, line in enumerate(file_text.split("\n")):
            if patternc.search(line):
                outf.write(pfmt % (revno, index+1, line))

    elif print_revno and not line_number:

        pfmt = fmt_rev
        for line in file_text.split("\n"):
            if patternc.search(line):
                outf.write(pfmt % (revno, line))

    elif not print_revno and line_number:

        pfmt = fmt_n
        for index, line in enumerate(file_text.split("\n")):
            if patternc.search(line):
                outf.write(pfmt % (index+1, line))

    else:

        pfmt = fmt
        for line in file_text.split("\n"):
            if patternc.search(line):
                outf.write(pfmt % (line,))


