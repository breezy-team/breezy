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

from bzrlib.errors import InvalidRevisionId
from bzrlib.repository import InterRepository
from bzrlib.trace import info

from bzrlib.plugins.git.repository import LocalGitRepository, GitRepository, GitFormat
from bzrlib.plugins.git.remote import RemoteGitRepository

from cStringIO import StringIO


class BzrFetchGraphWalker(object):

    def __init__(self, repository, mapping):
        self.repository = repository
        self.mapping = mapping
        self.done = set()
        self.heads = set(repository.all_revision_ids())
        self.parents = {}

    def ack(self, sha):
        revid = self.mapping.revision_id_foreign_to_bzr(sha)
        self.remove(revid)

    def remove(self, revid):
        self.done.add(revid)
        if ref in self.heads:
            self.heads.remove(revid)
        if revid in self.parents:
            for p in self.parents[revid]:
                self.remove(p)

    def next(self):
        while self.heads:
            ret = self.heads.pop()
            ps = self.repository.get_parent_map([ret])[ret]
            self.parents[ret] = ps
            self.heads.update([p for p in ps if not p in self.done])
            try:
                self.done.add(ret)
                return self.mapping.revision_id_bzr_to_foreign(ret)
            except InvalidRevisionId:
                pass
        return None


def import_git_pack(repo, pack):
    raise NotImplementedError(import_git_pack)


class InterGitRepository(InterRepository):

    def copy_content(self, revision_id=None, pb=None):
        """See InterRepository.copy_content."""
        self.fetch(revision_id, pb, find_ghosts=False)

    def fetch(self, revision_id=None, pb=None, find_ghosts=False, 
              mapping=None):
        if mapping is None:
            mapping = self.source.get_mapping()
        def progress(text):
            if pb is not None:
                pb.note("git: %s" % text)
            else:
                info("git: %s" % text)
        def determine_wants(heads):
            if revision_id is None:
                ret = heads.values()
            else:
                ret = [mapping.revision_id_bzr_to_foreign(revision_id)]
            return [rev for rev in ret if not self.target.has_revision(mapping.revision_id_foreign_to_bzr(revision_id))]
        self._fetch_packs(determine_wants, BzrFetchGraphWalker(self.target, mapping), progress)


class InterFromLocalGitRepository(InterGitRepository):

    _matching_repo_format = GitFormat()

    @staticmethod
    def _get_repo_format_to_test():
        return None

    def _fetch_packs(self, determine_wants, graph_walker, progress):
        self.target.lock_write()
        try:
            stream = StringIO()
            self.source.fetch_pack(determine_wants, graph_walker, stream.write, progress)
            import_git_pack(self.target, stream)
        finally:
            self.target.unlock()

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        # FIXME: Also check target uses VersionedFile
        return isinstance(source, LocalGitRepository) and target.supports_rich_root()


class InterFromRemoteGitRepository(InterGitRepository):

    _matching_repo_format = GitFormat()

    @staticmethod
    def _get_repo_format_to_test():
        return None

    def _fetch_packs(self, determine_wants, graph_walker, progress):
        self.target.lock_write()
        try:
            stream = StringIO()
            self.source.fetch_pack(determine_wants, graph_walker, stream.write, progress)
            import_git_pack(self.target, stream)
        finally:
            self.target.unlock()

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        # FIXME: Also check target uses VersionedFile
        return isinstance(source, RemoteGitRepository) and target.supports_rich_root()


 
