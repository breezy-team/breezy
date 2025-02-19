#    quilt.py -- Quilt patch handling
#    Copyright (C) 2011 Canonical Ltd.
#    Copyright (C) 2019 Jelmer Verooij <jelmer@jelmer.uk>
#
#    Breezy is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    Breezy is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with Breezy; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

"""Quilt patch handling."""

import shutil
import tempfile

from ... import merge as _mod_merge
from ... import trace
from ...i18n import gettext
from ...mutabletree import MutableTree
from ...revisiontree import RevisionTree
from .quilt import QuiltPatches


class NoUnapplyingMerger(_mod_merge.Merge3Merger):
    _no_quilt_unapplying = True


def tree_unapply_patches(orig_tree, orig_branch=None, force=False):
    """Return a tree with patches unapplied.

    :param orig_tree: Tree from which to unapply quilt patches
    :param orig_branch: Related branch (optional)
    :return: Tuple with tree and temp path.
        The tree is a tree with unapplied patches; either a checkout of
        tree or tree itself if there were no patches
    """
    if orig_branch is None:
        orig_branch = orig_tree.branch
    quilt = QuiltPatches.find(orig_tree)
    if quilt is None:
        return orig_tree, None
    applied_patches = quilt.applied()
    if not applied_patches:
        # No quilt patches
        return orig_tree, None

    target_dir = tempfile.mkdtemp()
    try:
        if isinstance(orig_tree, MutableTree):
            tree = orig_branch.create_checkout(
                target_dir,
                lightweight=True,
                revision_id=orig_tree.last_revision(),
                accelerator_tree=orig_tree,
            )
            merger = _mod_merge.Merger.from_uncommitted(tree, orig_tree)
            merger.merge_type = NoUnapplyingMerger
            merger.do_merge()
        elif isinstance(orig_tree, RevisionTree):
            tree = orig_branch.create_checkout(
                target_dir,
                lightweight=True,
                accelerator_tree=orig_tree,
                revision_id=orig_tree.get_revision_id(),
            )
        else:
            trace.mutter("Not sure how to create copy of %r", orig_tree)
            shutil.rmtree(target_dir)
            return orig_tree, None
        trace.mutter("Applying quilt patches for %r in %s", orig_tree, target_dir)
        quilt = QuiltPatches.find(tree)
        if quilt is not None:
            quilt.pop_all(force=force)
        return tree, target_dir
    except BaseException:
        shutil.rmtree(target_dir)
        raise


def post_process_quilt_patches(tree, old_patches, policy):
    """(Un)apply patches after a merge.

    :param tree: Working tree to work in
    :param old_patches: List of patches applied before the operation (usually a merge)
    """
    quilt = QuiltPatches.find(tree)
    if quilt is None:
        return
    new_patches = quilt.series()
    applied_patches = quilt.applied()
    if policy == "applied":
        to_apply = []
        for p in new_patches:
            if p in old_patches:
                continue
            if p not in applied_patches:
                to_apply.append(p)
        if to_apply == []:
            return
        trace.note(gettext("Applying %d quilt patches."), len(to_apply))
        for p in to_apply:
            quilt.push(p)
    elif policy == "unapplied":
        to_unapply = []
        for p in new_patches:
            if p in old_patches:
                continue
            if p in applied_patches:
                to_unapply.append(p)
        if to_unapply == []:
            return
        trace.note(gettext("Unapplying %d quilt patches."), len(to_unapply))
        for p in to_unapply:
            quilt.pop(p)


def start_commit_quilt_patches(tree, policy):
    quilt = QuiltPatches.find(tree)
    if quilt is None:
        return
    applied_patches = quilt.applied()
    unapplied_patches = quilt.unapplied()
    if policy is None:
        # No policy set - just warn about having both applied and unapplied
        # patches.
        if applied_patches and unapplied_patches:
            trace.warning(
                gettext("Committing with %d patches applied and %d patches unapplied."),
                len(applied_patches),
                len(unapplied_patches),
            )
    elif policy == "applied":
        quilt.push_all()
    elif policy == "unapplied":
        quilt.pop_all()
