# Copyright (C) 2011 Jelmer Vernooij <jelmer@samba.org>
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Unpeel map storage."""

from __future__ import absolute_import

from collections import defaultdict
from cStringIO import StringIO

from bzrlib import (
    errors,
    trace,
    )


class UnpeelMap(object):
    """Unpeel map.

    Keeps track of the unpeeled object id of tags.
    """

    def __init__(self):
        self._map = defaultdict(set)
        self._re_map = {}

    def update(self, m):
        for k, v in m.iteritems():
            self._map[k].update(v)
            for i in v:
                self._re_map[i] = k

    def load(self, f):
        firstline = f.readline()
        if firstline != "unpeel map version 1\n":
            raise AssertionError("invalid format for unpeel map: %r" % firstline)
        for l in f.readlines():
            (k, v) = l.split(":", 1)
            k = k.strip()
            v = v.strip()
            self._map[k].add(v)
            self._re_map[v] = k

    def save(self, f):
        f.write("unpeel map version 1\n")
        for k, vs in self._map.iteritems():
            for v in vs:
                f.write("%s: %s\n" % (k, v))

    def save_in_repository(self, repository):
        f = StringIO()
        try:
            self.save(f)
            f.seek(0)
            repository.control_transport.put_file("git-unpeel-map", f)
        finally:
            f.close()

    def peel_tag(self, git_sha, default=None):
        """Peel a tag."""
        return self._re_map.get(git_sha, default)

    def re_unpeel_tag(self, new_git_sha, old_git_sha):
        """Re-unpeel a tag.

        Bazaar can't store unpeeled refs so in order to prevent peeling
        existing tags when pushing they are "unpeeled" here.
        """
        if old_git_sha is not None and old_git_sha in self._map[new_git_sha]:
            trace.mutter("re-unpeeling %r to %r", new_git_sha, old_git_sha)
            return old_git_sha
        return new_git_sha

    @classmethod
    def from_repository(cls, repository):
        """Load the unpeel map for a repository.
        """
        m = UnpeelMap()
        try:
            m.load(repository.control_transport.get("git-unpeel-map"))
        except errors.NoSuchFile:
            pass
        return m