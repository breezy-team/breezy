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
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Map from Git sha's to Bazaar objects."""

from bzrlib.errors import NoSuchRevision


class GitObjectConverter(object):

    def __init__(self, repository, mapping=None):
        self.repository = repository
        if mapping is None:
            self.mapping = self.repository.get_mapping()
        else:
            self.mapping = mapping

    def __getitem__(self, sha):
        # Commit
        revid = self.mapping.revision_id_foreign_to_bzr(sha)
        try:
            rev = self.repository.get_revision(revid)
        except NoSuchRevision:
            pass
        else:
            return reconstruct_git_commit(rev)

        # TODO: Yeah, this won't scale, but the only alternative is a 
        # custom map..
        for (fileid, revision) in self.repository.texts.keys():
            blob = self._get_blob(
            print revision
            

class GitShaMap(object):

    def __init__(self, transport):
        self.transport = transport

    def add_entry(self, sha, type, type_data):
        """Add a new entry to the database.
        """
        raise NotImplementedError(self.add_entry)

    def lookup_git_sha(self, sha):
        """Lookup a Git sha in the database.

        :param sha: Git object sha
        :return: (type, type_data) with type_data:
            revision: revid, tree sha
        """
        raise NotImplementedError(self.lookup_git_sha)


class MappedGitObjectConverter(GitObjectConverter):
    
    def __init__(self, repository):
        self.repository = repository
        self._idmap = GitShaMap(self.repository._transport)

    def _update_sha_map(self):
        # TODO: Check which 
        raise NotImplementedError(self._update_sha_map)

    def __getitem__(self, sha):
        # See if sha is in map
        try:
            (type, type_data) = self._idmap.lookup_git_sha(sha)
        except KeyError:
            # if not, see if there are any unconverted revisions and add them 
            # to the map, search for sha in map again
            self._update_sha_map()
            (type, type_data) = self._idmap.lookup_git_sha(sha)
        # convert object to git object
        if type == "revision":
            return self._get_commit(*type_data)
        else:
            raise AssertionError("Unknown object type '%s'" % type)
