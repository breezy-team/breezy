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

import errno
import shutil
import tempfile
from bzrlib.revisiontree import RevisionTree
from bzrlib import (
    merge as _mod_merge,
    trace,
    )

from bzrlib.plugins.builddeb.quilt import (
    quilt_pop_all,
    quilt_push,
    quilt_pop,
    )
from bzrlib.plugins.builddeb.util import debuild_config


class NoUnapplyingMerger(_mod_merge.Merge3Merger):

    _no_quilt_unapplying = True


def tree_unapply_patches(orig_tree, orig_branch=None):
    """Return a tree with patches unapplied.

    :param orig_tree: Tree from which to unapply quilt patches
    :param orig_branch: Related branch (optional)
    :return: Tuple with tree and temp path.
        The tree is a tree with unapplied patches; either a checkout of
        tree or tree itself if there were no patches
    """
    if orig_branch is None:
        orig_branch = orig_tree.branch
    series_file_id = orig_tree.path2id("debian/patches/series")
    if series_file_id is None:
        # No quilt patches
        return orig_tree, None
    applied_patches_id = orig_tree.path2id(".pc/applied-patches")
    if applied_patches_id is None:
        return orig_tree, None
    try:
        applied_patches = orig_tree.get_file_text(applied_patches_id, ".pc/applied-patches")
    except (IOError, OSError), e:
        if e.errno == errno.ENOENT:
            # File has already been removed
            return orig_tree, None
        raise

    # Don't do any processing if there are no unapplied patches
    if not applied_patches:
        return orig_tree, None

    target_dir = tempfile.mkdtemp()
    try:
        if isinstance(orig_tree, RevisionTree):
            tree = orig_branch.create_checkout(target_dir, lightweight=True,
                accelerator_tree=orig_tree, revision_id=orig_tree.get_revision_id())
        else:
            tree = orig_branch.create_checkout(target_dir, lightweight=True,
                revision_id=orig_tree.last_revision(), accelerator_tree=orig_tree)
            merger = _mod_merge.Merger.from_uncommitted(tree, orig_tree)
            merger.merge_type = NoUnapplyingMerger
            merger.do_merge()
        trace.mutter("Applying quilt patches for %r in %s", orig_tree, target_dir)
        quilt_pop_all(working_dir=tree.basedir)
        return tree, target_dir
    except:
        shutil.rmtree(target_dir)
        raise


def post_process_quilt_patches(tree, old_patches):
    """(Un)apply patches after a merge.

    :param tree: Working tree to work in
    :param old_patches: List of patches applied before the operation (usually a merge)
    """
    new_patches = tree.get_file_lines(tree.path2id("debian/patches/series"))
    config = debuild_config(tree, tree)
    policy = config.quilt_tree_policy
    if policy is None:
        return
    applied_file_id = tree.path2id(".pc/applied-patches")
    if applied_file_id is not None:
        applied_patches = tree.get_file_lines(applied_file_id, ".pc/applied-patches")
    else:
        applied_patches = []
    if policy == "applied":
        to_apply = []
        for p in new_patches:
            if p in old_patches:
                continue
            if not p in applied_patches:
                to_apply.append(p)
        if to_apply == []:
            return
        trace.note("Applying %d quilt patches.", to_apply)
        for p in to_apply:
            quilt_push(tree.basedir, p)
    elif policy == "unapplied":
        to_unapply = []
        for p in new_patches:
            if p in old_patches:
                continue
            if p in applied_patches:
                to_unapply.append(p)
        if to_unapply == []:
            return
        trace.note("Unapplying %d quilt patches", to_unapply)
        for p in to_unapply:
            quilt_pop(tree.basedir, p)
