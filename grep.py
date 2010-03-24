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
    wt.lock_read()
    try:
        # res_cache is used to cache results for dir grep based on fid.
        # If the fid is does not change between results, it means that
        # the result will be the same apart from revno. In such a case
        # we avoid getting file chunks from repo and grepping. The result
        # is just printed by replacing old revno with new one.
        res_cache = {}

        start_rev = revision[0]
        start_revid = start_rev.as_revision_id(wt.branch)

        if len(revision) == 2:
            end_rev = revision[1]
            end_revid   = end_rev.as_revision_id(wt.branch)
            given_revs = logcmd._graph_view_revisions(wt.branch, start_revid, end_revid)
        else:
            # We do an optimization below. For grepping a specific revison
            # We don't need to call _graph_view_revisions which is slow.
            # We create the start_rev_tuple for only that specific revision.
            # _graph_view_revisions is used only for revision range.
            srevno_tuple = wt.branch.revision_id_to_dotted_revno(start_revid)
            start_revno = '.'.join(map(str, srevno_tuple))
            start_rev_tuple = (start_revid, start_revno, 0)
            given_revs = [start_rev_tuple]

        for revid, revno, merge_depth in given_revs:
            if levels == 1 and merge_depth != 0:
                # with level=1 show only top level
                continue

            rev = RevisionSpec_revid.from_string("revid:"+revid)
            tree = rev.as_tree(wt.branch)
            for path in path_list:
                path_for_id = osutils.pathjoin(relpath, path)
                id = tree.path2id(path_for_id)
                if not id:
                    trace.warning("Skipped unknown file '%s'." % path)
                    continue

                if osutils.isdir(path):
                    path_prefix = path
                    res_cache = dir_grep(tree, path, relpath, recursive,
                        line_number, pattern, compiled_pattern,
                        from_root, eol_marker, revno, print_revno,
                        include, exclude, verbose, fixed_string,
                        ignore_case, outf, path_prefix, res_cache)
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
        include, exclude, verbose, fixed_string, ignore_case, outf,
        path_prefix, res_cache={}):
    _revno_pattern = re.compile("\~[0-9.]+:")
    dir_res = {}

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
    to_grep_append = to_grep.append
    outf_write = outf.write
    for fp, fc, fkind, fid, entry in tree.list_files(include_root=False,
        from_dir=from_dir, recursive=recursive):

        if _skip_file(include, exclude, fp):
            continue

        if fc == 'V' and fkind == 'file':
            if revno != None:
                # If old result is valid, print results immediately.
                # Otherwise, add file info to to_grep so that the
                # loop later will get chunks and grep them
                old_res = res_cache.get(fid)
                if old_res != None:
                    res = []
                    res_append = res.append
                    new_rev = ('~%s:' % (revno,))
                    for line in old_res:
                        s = _revno_pattern.sub(new_rev, line)
                        res_append(s)
                        outf_write(s)
                    dir_res[fid] = res
                else:
                    to_grep_append((fid, (fp, fid)))
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
        for (path, fid), chunks in tree.iter_files_bytes(to_grep):
            path = _make_display_path(relpath, path)
            res = _file_grep(chunks[0], rpath, path, pattern,
                compiled_pattern, eol_marker, line_number, revno,
                print_revno, include, exclude, verbose, fixed_string,
                ignore_case, outf, path_prefix)
            dir_res[fid] = res
    return dir_res

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
    res = []

    _te = _terminal_encoding
    _ue = _user_encoding

    pattern = pattern.encode(_ue, 'replace')
    if fixed_string and ignore_case:
        pattern = pattern.lower()

    # test and skip binary files
    if '\x00' in file_text[:1024]:
        if verbose:
            trace.warning("Binary file '%s' skipped." % path)
        return res

    if path_prefix and path_prefix != '.':
        # user has passed a dir arg, show that as result prefix
        path = osutils.pathjoin(path_prefix, path)

    path = path.encode(_te, 'replace')

    # for better performance we moved formatting conditionals out
    # of the core loop. hence, the core loop is somewhat duplicated
    # for various combinations of formatting options.

    if print_revno and line_number:

        pfmt = "~%s:%d:%s".encode(_te)
        if fixed_string:
            for index, line in enumerate(file_text.splitlines()):
                if ignore_case:
                    line = line.lower()
                if pattern in line:
                    line = line.decode(_te, 'replace')
                    s = path + (pfmt % (revno, index+1, line)) + eol_marker
                    res.append(s)
                    outf.write(s)
        else:
            for index, line in enumerate(file_text.splitlines()):
                if patternc.search(line):
                    line = line.decode(_te, 'replace')
                    s = path + (pfmt % (revno, index+1, line)) + eol_marker
                    res.append(s)
                    outf.write(s)

    elif print_revno and not line_number:

        pfmt = "~%s:%s".encode(_te, 'replace')
        if fixed_string:
            for line in file_text.splitlines():
                if ignore_case:
                    line = line.lower()
                if pattern in line:
                    line = line.decode(_te, 'replace')
                    s = path + (pfmt % (revno, line)) + eol_marker
                    res.append(s)
                    outf.write(s)
        else:
            for line in file_text.splitlines():
                if patternc.search(line):
                    line = line.decode(_te, 'replace')
                    s = path + (pfmt % (revno, line)) + eol_marker
                    res.append(s)
                    outf.write(s)

    elif not print_revno and line_number:

        pfmt = ":%d:%s".encode(_te)
        if fixed_string:
            for index, line in enumerate(file_text.splitlines()):
                if ignore_case:
                    line = line.lower()
                if pattern in line:
                    line = line.decode(_te, 'replace')
                    s = path + (pfmt % (index+1, line)) + eol_marker
                    res.append(s)
                    outf.write(s)
        else:
            for index, line in enumerate(file_text.splitlines()):
                if patternc.search(line):
                    line = line.decode(_te, 'replace')
                    s = path + (pfmt % (index+1, line)) + eol_marker
                    res.append(s)
                    outf.write(s)

    else:

        pfmt = ":%s".encode(_te)
        if fixed_string:
            for line in file_text.splitlines():
                if ignore_case:
                    line = line.lower()
                if pattern in line:
                    line = line.decode(_te, 'replace')
                    s = path + (pfmt % (line,)) + eol_marker
                    res.append(s)
                    outf.write(s)
        else:
            for line in file_text.splitlines():
                if patternc.search(line):
                    line = line.decode(_te, 'replace')
                    s = path + (pfmt % (line,)) + eol_marker
                    res.append(s)
                    outf.write(s)

    return res

