#!/usr/bin/python3
# Copyright (C) 2018-2022 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Quilt patch refreshing."""

import os
import re
from typing import Optional

from debmutate.changelog import ChangelogEditor
from breezy.plugins.debian.changelog import debcommit
from breezy.commit import PointlessCommit
from breezy.tree import Tree

from breezy.plugins.quilt.quilt import (
    QuiltError,
    QuiltPatches,
)


class QuiltPatchPushFailure(Exception):
    def __init__(self, patch_name, actual_error):
        self.patch_name = patch_name
        self.actual_error = actual_error


def refresh_quilt_patches(
    local_tree: Tree,
    committer: Optional[str] = None,
    subpath: str = "",
) -> None:
    # TODO(jelmer):
    # Find patch base branch.
    #   If it exists, rebase it onto the new upstream.
    #   And then run 'gbp pqm export' or similar
    # If not:
    #   Refresh patches against the new upstream revision
    patches = QuiltPatches(local_tree, os.path.join(subpath, "debian/patches"))
    patches.upgrade()
    for name in patches.unapplied():
        try:
            patches.push(name, refresh=True)
        except QuiltError as e:
            lines = e.stdout.splitlines()
            m = re.match(
                "Patch debian/patches/(.*) can be reverse-applied",
                lines[-1])
            if m and getattr(patches, "delete", None):
                assert m.group(1) == name
                patches.delete(name, remove=True)
                with ChangelogEditor(
                        local_tree.abspath(
                            os.path.join(subpath, 'debian/changelog'))
                        ) as cl:
                    cl.add_entry(["Drop patch %s, present upstream." % name])
                debcommit(
                    local_tree,
                    committer=committer,
                    subpath=subpath,
                    paths=[
                        "debian/patches/series",
                        "debian/patches/" + name,
                        "debian/changelog",
                    ],
                )
            else:
                raise QuiltPatchPushFailure(name, e)
    patches.pop_all()
    try:
        local_tree.commit(
            "Refresh patches.", committer=committer, allow_pointless=False
        )
    except PointlessCommit:
        pass
