# Copyright (C) 2011-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Unpeel map storage."""

from collections import defaultdict
from io import BytesIO

from .. import trace
from .. import transport as _mod_transport


class UnpeelMap:
    """Unpeel map.

    Keeps track of the unpeeled object id of tags.
    """

    def __init__(self):
        self._map = defaultdict(set)
        self._re_map = {}

    def update(self, m):
        for k, v in m.items():
            self._map[k].update(v)
            for i in v:
                self._re_map[i] = k

    def load(self, f):
        firstline = f.readline()
        if firstline != b"unpeel map version 1\n":
            raise AssertionError("invalid format for unpeel map: %r" % firstline)
        for l in f.readlines():
            (k, v) = l.split(b":", 1)
            k = k.strip()
            v = v.strip()
            self._map[k].add(v)
            self._re_map[v] = k

    def save(self, f):
        f.write(b"unpeel map version 1\n")
        for k, vs in self._map.items():
            for v in vs:
                f.write(b"%s: %s\n" % (k, v))

    def save_in_repository(self, repository):
        with BytesIO() as f:
            self.save(f)
            f.seek(0)
            repository.control_transport.put_file("git-unpeel-map", f)

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
        """Load the unpeel map for a repository."""
        m = UnpeelMap()
        try:
            m.load(repository.control_transport.get("git-unpeel-map"))
        except _mod_transport.NoSuchFile:
            pass
        return m
