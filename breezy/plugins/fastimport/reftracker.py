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


"""Tracker of refs."""

from __future__ import absolute_import


class RefTracker(object):

    def __init__(self):
        # Head tracking: last ref, last id per ref & map of commit ids to ref*s*
        self.last_ref = None
        self.last_ids = {}
        self.heads = {}

    def dump_stats(self, note):
        self._show_stats_for(self.last_ids, "last-ids", note=note)
        self._show_stats_for(self.heads, "heads", note=note)

    def clear(self):
        self.last_ids.clear()
        self.heads.clear()

    def track_heads(self, cmd):
        """Track the repository heads given a CommitCommand.

        :param cmd: the CommitCommand
        :return: the list of parents in terms of commit-ids
        """
        # Get the true set of parents
        if cmd.from_ is not None:
            parents = [cmd.from_]
        else:
            last_id = self.last_ids.get(cmd.ref)
            if last_id is not None:
                parents = [last_id]
            else:
                parents = []
        parents.extend(cmd.merges)

        # Track the heads
        self.track_heads_for_ref(cmd.ref, cmd.id, parents)
        return parents

    def track_heads_for_ref(self, cmd_ref, cmd_id, parents=None):
        if parents is not None:
            for parent in parents:
                if parent in self.heads:
                    del self.heads[parent]
        self.heads.setdefault(cmd_id, set()).add(cmd_ref)
        self.last_ids[cmd_ref] = cmd_id
        self.last_ref = cmd_ref


