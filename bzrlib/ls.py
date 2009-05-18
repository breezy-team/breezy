# Copyright (C) 2004, 2005, 2006, 2007, 2008, 2009 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""List files in a tree."""


from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    errors,
    osutils,
    )
from bzrlib.trace import mutter, note
from bzrlib.workingtree import WorkingTree
""")


def ls(tree, outf, from_dir=None, recursive=False, kind=None, unknown=False,
    versioned=False, ignored=False, verbose=False, null=False, show_ids=False,
    prefix=None, from_root=False):
    """List files for a tree.

    If unknown, versioned and ignored are all False, then all are displayed.

    :param tree: the tree to display files for
    :param outf: the output stream
    :param from_dir: just from this directory
    :param recursive: whether to recurse into subdirectories or not
    :param kind: one of 'file', 'symlink', 'directory' or None for all
    :param unknown: include unknown files or not
    :param versioned: include versioned files or not
    :param ignored: include ignored files or not
    :param verbose: show file kinds, not just paths
    :param null: separate entries with null characters instead of newlines
    :param show_ids: show file_ids or not
    :param prefix: prefix paths with this string or None for no prefix
    :param from_root: show paths from the root instead of relative
    """
    mutter("ls from: %s" % (from_dir,))
    # Tell the user if a view if being applied
    apply_view = False
    if isinstance(tree, WorkingTree) and tree.supports_views():
        view_files = tree.views.lookup_view()
        if view_files:
            apply_view = True
            view_str = views.view_display_str(view_files)
            note("Ignoring files outside view. View is %s" % view_str)

    # Find and display the files
    all = not (unknown or versioned or ignored)
    selection = {'I':ignored, '?':unknown, 'V':versioned}
    #if from_dir and from_root:
    #    prefix = from_dir
    #else:
    #    prefix = None
    tree.lock_read()
    try:
        for fp, fc, fkind, fid, entry in tree.list_files(include_root=False,
            from_dir=from_dir, recursive=recursive):
            # Apply additional masking
            if not all and not selection[fc]:
                continue
            if kind is not None and fkind != kind:
                continue
            if apply_view:
                if from_dir:
                    fullpath = osutils.pathjoin(from_dir, fp)
                else:
                    fullpath = fp
                try:
                    views.check_path_in_view(tree, fullpath)
                except errors.FileOutsideView:
                    continue

            # Output the entry
            kindch = entry.kind_character()
            if prefix is not None:
                fp = osutils.pathjoin(prefix, fp)
            outstring = fp + kindch
            if verbose:
                outstring = '%-8s %s' % (fc, outstring)
                if show_ids and fid is not None:
                    outstring = "%-50s %s" % (outstring, fid)
                outf.write(outstring + '\n')
            elif null:
                outf.write(fp + '\0')
                if show_ids:
                    if fid is not None:
                        outf.write(fid)
                    outf.write('\0')
                outf.flush()
            else:
                if show_ids:
                    if fid is not None:
                        my_id = fid
                    else:
                        my_id = ''
                    outf.write('%-50s %s\n' % (outstring, my_id))
                else:
                    outf.write(outstring + '\n')
    finally:
        tree.unlock()
