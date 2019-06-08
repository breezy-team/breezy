#    __init__.py -- Quilt support for breezy
#
#    brz-debian is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    brz-debian is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with brz-debian; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

"""Quilt support for Breezy."""

from ....errors import BzrError
from .... import trace


class QuiltUnapplyError(BzrError):

    _fmt = ("Unable to unapply quilt patches for %(kind)r tree: %(msg)s")

    def __init__(self, kind, msg):
        BzrError.__init__(self)
        self.kind = kind
        if msg is not None and msg.count("\n") == 1:
            msg = msg.strip()
        self.msg = msg


def pre_merge_quilt(merger):
    if getattr(merger, "_no_quilt_unapplying", False):
        return

    config = merger.working_tree.get_config_stack()
    merger.debuild_config = config
    if not config.get('quilt.smart_merge'):
        trace.mutter("skipping smart quilt merge, not enabled.")
        return

    if (not merger.other_tree.is_versioned(".pc") and
            not merger.this_tree.is_versioned(".pc") and
            not merger.working_tree.is_versioned(".pc")):
        return

    from .quilt import QuiltPatches, QuiltError
    quilt = QuiltPatches(merger.working_tree)
    from .merge import tree_unapply_patches
    trace.note("Unapplying quilt patches to prevent spurious conflicts")
    merger._quilt_tempdirs = []
    merger._old_quilt_series = quilt.series()
    if merger._old_quilt_series:
        quilt.pop_all()
    try:
        merger.this_tree, this_dir = tree_unapply_patches(
            merger.this_tree, merger.this_branch, force=True)
    except QuiltError as e:
        raise QuiltUnapplyError("this", e.stderr)
    else:
        if this_dir is not None:
            merger._quilt_tempdirs.append(this_dir)
    try:
        merger.base_tree, base_dir = tree_unapply_patches(
            merger.base_tree, merger.this_branch, force=True)
    except QuiltError as e:
        raise QuiltUnapplyError("base", e.stderr)
    else:
        if base_dir is not None:
            merger._quilt_tempdirs.append(base_dir)
    other_branch = getattr(merger, "other_branch", None)
    if other_branch is None:
        other_branch = merger.this_branch
    try:
        merger.other_tree, other_dir = tree_unapply_patches(
            merger.other_tree, other_branch, force=True)
    except QuiltError as e:
        raise QuiltUnapplyError("other", e.stderr)
    else:
        if other_dir is not None:
            merger._quilt_tempdirs.append(other_dir)



from ....hooks import install_lazy_named_hook
install_lazy_named_hook(
    "breezy.merge", "Merger.hooks",
    'pre_merge_quilt', pre_merge_quilt,
    'Debian quilt patch (un)applying')
