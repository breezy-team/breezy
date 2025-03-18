#    release.py -- The plugin for bzr
#    Copyright (C) 2018 Jelmer Vernooij
#
#    This file is part of breezy-debian.
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

import os

from debmutate.changelog import (
    ChangelogEditor,
    distribution_is_unreleased,
)
from debmutate.changelog import (
    release as mark_for_release,
)

from breezy.workingtree import WorkingTree

from .changelog import debcommit_release
from .util import find_changelog


def release(local_tree: WorkingTree, subpath: str):
    """Release a tree."""
    (changelog, top_level) = find_changelog(
        local_tree, subpath, merge=False, max_blocks=2
    )

    # TODO(jelmer): If this changelog is automatically updated,
    # insert missing entries now.
    if distribution_is_unreleased(changelog.distributions):
        if top_level:
            changelog_path = "changelog"
        else:
            changelog_path = "debian/changelog"
        changelog_abspath = local_tree.abspath(os.path.join(subpath, changelog_path))
        with ChangelogEditor(changelog_abspath) as e:
            mark_for_release(e.changelog)
        return debcommit_release(local_tree, subpath=subpath)
    return None


class SuccessReleaseMarker:
    def __init__(self, local_tree, subpath):
        self.local_tree = local_tree
        self.subpath = subpath

    def __enter__(self):
        self.old_revid = self.local_tree.last_revision()
        (changelog, top_level) = find_changelog(
            self.local_tree, self.subpath, merge=False, max_blocks=2
        )

        # TODO(jelmer): If this changelog is automatically updated,
        # insert missing entries now.
        if distribution_is_unreleased(changelog.distributions):
            if top_level:
                self.changelog_path = "changelog"
            else:
                self.changelog_path = "debian/changelog"
            self.changelog_abspath = self.local_tree.abspath(
                os.path.join(self.subpath, self.changelog_path)
            )
            with ChangelogEditor(self.changelog_abspath) as e:
                mark_for_release(e.changelog)
            self.new_revid = debcommit_release(self.local_tree, subpath=self.subpath)
        else:
            self.new_revid = None

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            if self.new_revid:
                self.local_tree.set_last_revision(self.old_revid)
                self.local_tree.branch.generate_revision_history(self.old_revid)
                self.local_tree.revert([self.changelog_path])
        return False
