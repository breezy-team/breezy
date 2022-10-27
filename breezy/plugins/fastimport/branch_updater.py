# Copyright (C) 2009 Canonical Ltd
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""An object that updates a bunch of branches based on data imported."""

from operator import itemgetter

from ... import errors, osutils, transport
from ...trace import show_error, note

from breezy import controldir
from .helpers import (
    best_format_for_objects_in_a_repository,
    single_plural,
    )


class BranchUpdater(object):

    def __init__(self, repo, branch, cache_mgr, heads_by_ref, last_ref, tags):
        """Create an object responsible for updating branches.

        :param heads_by_ref: a dictionary where
          names are git-style references like refs/heads/master;
          values are one item lists of commits marks.
        """
        self.repo = repo
        self.branch = branch
        self.cache_mgr = cache_mgr
        self.heads_by_ref = heads_by_ref
        self.last_ref = last_ref
        self.tags = tags
        self._branch_format = \
            best_format_for_objects_in_a_repository(repo)

    def update(self):
        """Update the Bazaar branches and tips matching the heads.

        If the repository is shared, this routine creates branches
        as required. If it isn't, warnings are produced about the
        lost of information.

        :return: updated, lost_heads where
          updated = the list of branches updated ('trunk' is first)
          lost_heads = a list of (bazaar-name,revision) for branches that
            would have been created had the repository been shared
        """
        updated = []
        branch_tips, lost_heads = self._get_matching_branches()
        for br, tip in branch_tips:
            if self._update_branch(br, tip):
                updated.append(br)
        return updated, lost_heads

    def _get_matching_branches(self):
        """Get the Bazaar branches.

        :return: branch_tips, lost_heads where
          branch_tips = a list of (branch,tip) tuples for branches. The
            first tip is the 'trunk'.
          lost_heads = a list of (bazaar-name,revision) for branches that
            would have been created had the repository been shared and
            everything succeeded
        """
        branch_tips = []
        lost_heads = []
        ref_names = list(self.heads_by_ref)
        if self.branch is not None:
            trunk = self.select_trunk(ref_names)
            default_tip = self.heads_by_ref[trunk][0]
            branch_tips.append((self.branch, default_tip))
            ref_names.remove(trunk)

        # Convert the reference names into Bazaar speak. If we haven't
        # already put the 'trunk' first, do it now.
        git_to_bzr_map = {}
        for ref_name in ref_names:
            git_to_bzr_map[ref_name] = self.cache_mgr.branch_mapper.git_to_bzr(
                ref_name)
        if ref_names and self.branch is None:
            trunk = self.select_trunk(ref_names)
            git_bzr_items = [(trunk, git_to_bzr_map[trunk])]
            del git_to_bzr_map[trunk]
        else:
            git_bzr_items = []
        git_bzr_items.extend(sorted(git_to_bzr_map.items(), key=itemgetter(1)))

        # Policy for locating branches
        def dir_under_current(name):
            # Using the Bazaar name, get a directory under the current one
            repo_base = self.repo.controldir.transport.base
            return osutils.pathjoin(repo_base, "..", name)

        def dir_sister_branch(name):
            # Using the Bazaar name, get a sister directory to the branch
            return osutils.pathjoin(self.branch.base, "..", name)
        if self.branch is not None:
            dir_policy = dir_sister_branch
        else:
            dir_policy = dir_under_current

        # Create/track missing branches
        can_create_branches = (
            self.repo.is_shared() or
            self.repo.controldir._format.colocated_branches)
        for ref_name, name in git_bzr_items:
            tip = self.heads_by_ref[ref_name][0]
            if can_create_branches:
                try:
                    br = self.make_branch(name, ref_name, dir_policy)
                    branch_tips.append((br, tip))
                    continue
                except errors.BzrError as ex:
                    show_error("ERROR: failed to create branch %s: %s",
                               name, ex)
            lost_head = self.cache_mgr.lookup_committish(tip)
            lost_info = (name, lost_head)
            lost_heads.append(lost_info)
        return branch_tips, lost_heads

    def select_trunk(self, ref_names):
        """Given a set of ref names, choose one as the trunk."""
        for candidate in ['refs/heads/master']:
            if candidate in ref_names:
                return candidate
        # Use the last reference in the import stream
        return self.last_ref

    def make_branch(self, name, ref_name, dir_policy):
        """Make a branch in the repository if not already there."""
        if self.repo.is_shared():
            location = dir_policy(name)
            to_transport = transport.get_transport(location)
            to_transport.create_prefix()
            try:
                return controldir.ControlDir.open(location).open_branch()
            except errors.NotBranchError as ex:
                return controldir.ControlDir.create_branch_convenience(
                    location,
                    format=self._branch_format,
                    possible_transports=[to_transport])
        else:
            try:
                return self.repo.controldir.open_branch(name)
            except errors.NotBranchError as ex:
                return self.repo.controldir.create_branch(name)

    def _update_branch(self, br, last_mark):
        """Update a branch with last revision and tag information.

        :return: whether the branch was changed or not
        """
        last_rev_id = self.cache_mgr.lookup_committish(last_mark)
        with self.repo.lock_read():
            graph = self.repo.get_graph()
            revno = graph.find_distance_to_null(last_rev_id, [])
        existing_revno, existing_last_rev_id = br.last_revision_info()
        changed = False
        if revno != existing_revno or last_rev_id != existing_last_rev_id:
            br.set_last_revision_info(revno, last_rev_id)
            changed = True
        # apply tags known in this branch
        my_tags = {}
        if self.tags:
            graph = self.repo.get_graph()
            ancestry = [r for (r, ps) in graph.iter_ancestry(
                [last_rev_id]) if ps is not None]
            for tag, rev in self.tags.items():
                if rev in ancestry:
                    my_tags[tag] = rev
            if my_tags:
                br.tags._set_tag_dict(my_tags)
                changed = True
        if changed:
            tagno = len(my_tags)
            note("\t branch %s now has %d %s and %d %s", br.nick,
                 revno, single_plural(revno, "revision", "revisions"),
                 tagno, single_plural(tagno, "tag", "tags"))
        return changed
