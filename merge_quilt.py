#    quilt.py -- Quilt patch handling
#    Copyright (C) 2011 Canonical Ltd.
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

"""Quilt patch handling."""

from __future__ import absolute_import
import tempfile

from bzrlib import trace
from bzrlib.plugins.builddeb.quilt import quilt_pop_all


def tree_unapply_patches(orig_tree):
    """Return a tree with patches unapplied.

    :param tree: Tree from which to unapply quilt patches
    :return: Tuple with tree and temp path.
        The tree is a tree with unapplied patches; either a checkout of
        tree or tree itself if there were no patches
    """
    series_file_id = orig_tree.path2id("debian/patches/series")
    if series_file_id is None:
        # No quilt patches
        return orig_tree, None

    target_dir = tempfile.mkdtemp()
    tree = orig_tree.branch.create_checkout(target_dir, lightweight=True)
    trace.warning("Applying quilt patches for %r in %s", orig_tree, target_dir)
    quilt_pop_all(working_dir=tree.basedir)
    return tree, target_dir
