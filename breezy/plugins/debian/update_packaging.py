#!/usr/bin/python3
# Copyright (C) 2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Refresh packaging."""

import logging
import os
from email.utils import parseaddr
from typing import Optional

from debian.changelog import get_maintainer
from debmutate.changelog import ChangelogEditor

from breezy.plugins.debian.changelog import debcommit
from breezy.tree import Tree
from breezy.workingtree import WorkingTree


def override_dh_autoreconf_add_arguments(basedir: str, args):
    from debmutate._rules import update_rules

    # TODO(jelmer): Make sure dh-autoreconf is installed,
    # or debhelper version is >= 10

    def update_makefile(mf):
        for rule in mf.iter_rules(b"override_dh_autoreconf"):
            command = rule.commands()[0].split(b" ")
            if command[0] != b"dh_autoreconf":
                return
            rule.lines = [rule.lines[0]]
            command += args
            break
        else:
            rule = mf.add_rule(b"override_dh_autoreconf")
            command = [b"dh_autoreconf"] + args
        rule.append_command(b" ".join(command))

    return update_rules(
        makefile_cb=update_makefile, path=os.path.join(basedir, "debian", "rules")
    )


def update_packaging(
    tree: WorkingTree,
    old_tree: Tree,
    subpath: str = "",
    committer: Optional[str] = None,
) -> list[str]:
    """Update packaging to take in changes between upstream trees.

    Args:
      tree: Current tree
      old_tree: Old tree
      committer: Optional committer to use for changes
    """
    if committer is None:
        maintainer = get_maintainer()
    else:
        maintainer = parseaddr(committer)
    notes = []
    tree_delta = tree.changes_from(old_tree, specific_files=[subpath])
    for delta in tree_delta.added:
        path = delta.path[1]
        if path is None:
            continue
        if not path.startswith(subpath):
            continue
        path = path[len(subpath) :]
        if path == "autogen.sh":
            if override_dh_autoreconf_add_arguments(tree.basedir, [b"./autogen.sh"]):
                logging.info(
                    "Modifying debian/rules: " "Invoke autogen.sh from dh_autoreconf."
                )
                with ChangelogEditor(
                    tree.abspath(os.path.join(subpath, "debian/changelog"))
                ) as cl:
                    cl.add_entry(
                        ["Invoke autogen.sh from dh_autoreconf."], maintainer=maintainer
                    )
                debcommit(
                    tree,
                    committer=committer,
                    subpath=subpath,
                    paths=["debian/changelog", "debian/rules"],
                )
        elif path.startswith("LICENSE") or path.startswith("COPYING"):
            notes.append("License file {} has changed.".format(os.path.join(subpath, path)))

    return notes


def main():
    import argparse

    import breezy.bzr
    import breezy.git  # noqa: F401
    from breezy.revisionspec import RevisionSpec

    parser = argparse.ArgumentParser("deb-update-packaging")
    parser.add_argument("--since", type=str, help="Revision since when to update")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    wt, subpath = WorkingTree.open_containing(".")
    if args.since:
        old_tree = RevisionSpec.from_string(args.since).as_tree(args.since)
    else:
        old_tree = wt.basis_tree()

    notes = update_packaging(wt, old_tree, subpath)
    for note in notes:
        logging.info("%s", note)


if __name__ == "__main__":
    import sys

    sys.exit(main())
