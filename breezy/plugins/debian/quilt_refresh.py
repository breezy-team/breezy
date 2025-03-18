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

from breezy.commit import PointlessCommit
from breezy.plugins.debian.changelog import debcommit
from breezy.plugins.quilt.quilt import (
    QuiltError,
    QuiltPatches,
)
from breezy.workingtree import WorkingTree


class QuiltPatchPushFailure(Exception):
    def __init__(self, patch_name, actual_error):
        self.patch_name = patch_name
        self.actual_error = actual_error


class QuiltPatchDoesNotApply(Exception):
    def __init__(self, patch_name, error_lines):
        self.patch_name = patch_name
        self.error_lines = error_lines


def refresh_quilt_patches(
    local_tree: WorkingTree,
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
            m = re.match("Patch debian/patches/(.*) can be reverse-applied", lines[-1])
            if m:
                if m.group(1) != name:
                    raise AssertionError("Unexpected patch name") from e
                patches.delete(name, remove=True)
                with ChangelogEditor(
                    local_tree.abspath(os.path.join(subpath, "debian/changelog"))
                ) as cl:
                    cl.add_entry(["Drop patch {}, present upstream.".format(name)])
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
                continue
            m = re.match(
                r"Patch debian/patches/(.*) does not apply " r"\(enforce with -f\)",
                lines[-1],
            )
            if m:
                if m.group(1) != name:
                    raise AssertionError("Unexpected patch name") from e
                raise QuiltPatchDoesNotApply(name, e) from e
            raise QuiltPatchPushFailure(name, e) from e
    patches.pop_all()
    try:
        local_tree.commit(
            "Refresh patches.", committer=committer, allow_pointless=False
        )
    except PointlessCommit:
        pass
