# Copyright (C) 2008 Canonical Ltd
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

from bzrlib.repository import InterRepository

from bzrlib.plugins.git.repository import GitRepository, GitFormat

from bzrlib.plugins.git import git

from cStringIO import StringIO


class BzrGraphWalker(object):

    def __init__(self, repository, mapping):
        self.repository = repository
        # FIXME: something more efficient to calculate heads?
        self.heads = self.repository.get_ancestry(None)
        self.parents = {}
        self.mapping = mapping

    def get_parents(self, ref):
        revid = self.mapping.revision_id_foreign_to_bzr(ref)   
        # FIXME: Ghosts
        ps = self.repository.get_parent_map([revid])[revid]
        for [self.repository.lookup_git_revid(revid, self.mapping)

    def next(self):
        if self.heads:
            ret = self.heads.pop(0)
            ps = self.get_parents(ret)
            self.parents[ret] = ps
            self.heads.extend(ps)
            return ret
        return None

    def ack(self, sha):
        if sha in self.heads:
            self.heads.remove(sha)
        if sha in self.parents:
            for p in self.parents[sha]:
                self.ack(p)


class InterFromGitRepository(InterRepository):

    _matching_repo_format = GitFormat()

    @staticmethod
    def _get_repo_format_to_test():
        return None

    def copy_content(self, revision_id=None, pb=None):
        """See InterRepository.copy_content."""
        self.fetch(revision_id, pb, find_ghosts=False)

    def fetch(self, revision_id=None, pb=None, find_ghosts=False, 
              mapping=None):
        if revision_id is None:
            determine_wants = lambda x: x.values()
        else:
            determine_wants = lambda x: [self.lookup_git_revid(revision_id, mapping)]
        pack = StringIO()
        self.source.fetch_pack(determine_wants, 
            BzrGraphWalker(self.target, mapping), pack)
        # FIXME: parse pack

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        # FIXME: Also check target uses VersionedFile
        return isinstance(source, GitRepository) and target.supports_rich_root()


 
