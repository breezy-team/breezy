# Copyright (C) 2005-2008 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from bzrlib import errors, osutils, registry

import sha
import urllib

MAPPING_VERSION = 3

SVN_PROP_BZR_PREFIX = 'bzr:'
SVN_PROP_BZR_ANCESTRY = 'bzr:ancestry:v%d-' % MAPPING_VERSION
SVN_PROP_BZR_FILEIDS = 'bzr:file-ids'
SVN_PROP_BZR_MERGE = 'bzr:merge'
SVN_PROP_BZR_REVISION_INFO = 'bzr:revision-info'
SVN_PROP_BZR_REVISION_ID = 'bzr:revision-id:v%d-' % MAPPING_VERSION
SVN_PROP_BZR_BRANCHING_SCHEME = 'bzr:branching-scheme'

SVN_REVPROP_BZR_COMMITTER = 'bzr:committer'
SVN_REVPROP_BZR_FILEIDS = 'bzr:file-ids'
SVN_REVPROP_BZR_MERGE = 'bzr:merge'
SVN_REVPROP_BZR_REVISION_ID = 'bzr:revision-id'
SVN_REVPROP_BZR_REVPROP_PREFIX = 'bzr:revprop:'
SVN_REVPROP_BZR_ROOT = 'bzr:root'
SVN_REVPROP_BZR_SCHEME = 'bzr:scheme'
SVN_REVPROP_BZR_SIGNATURE = 'bzr:gpg-signature'


def escape_svn_path(x):
    """Escape a Subversion path for use in a revision identifier.

    :param x: Path
    :return: Escaped path
    """
    assert isinstance(x, str)
    return urllib.quote(x, "")
unescape_svn_path = urllib.unquote


class BzrSvnMapping:
    """Class that maps between Subversion and Bazaar semantics."""

    @staticmethod
    def parse_revision_id(revid):
        """Parse an existing Subversion-based revision id.

        :param revid: The revision id.
        :raises: InvalidRevisionId
        :return: Tuple with uuid, branch path, revision number and scheme.
        """
        raise NotImplementedError(self.parse_revision_id)

    def generate_revision_id(uuid, revnum, path, scheme):
        """Generate a unambiguous revision id. 
        
        :param uuid: UUID of the repository.
        :param revnum: Subversion revision number.
        :param path: Branch path.
        :param scheme: Name of the branching scheme in use

        :return: New revision id.
        """
        raise NotImplementedError(self.generate_revision_id)

    @staticmethod
    def generate_file_id(uuid, revnum, branch, inv_path):
        """Create a file id identifying a Subversion file.

        :param uuid: UUID of the repository
        :param revnum: Revision number at which the file was introduced.
        :param branch: Branch path of the branch in which the file was introduced.
        :param inv_path: Original path of the file within the inventory
        """
        raise NotImplementedError(self.generate_file_id)


class BzrSvnMappingv1(BzrSvnMapping):
    @staticmethod
    def parse_revision_id(revid):
        assert revid.startswith("svn-v1:")
        revid = revid[len("svn-v1:"):]
        at = revid.index("@")
        fash = revid.rindex("-")
        uuid = revid[at+1:fash]
        branch_path = unescape_svn_path(revid[fash+1:])
        revnum = int(revid[0:at])
        assert revnum >= 0
        return (uuid, branch_path, revnum, None)


class BzrSvnMappingv2(BzrSvnMapping):
    @staticmethod
    def parse_revision_id(revid):
        assert revid.startswith("svn-v2:")
        revid = revid[len("svn-v2:"):]
        at = revid.index("@")
        fash = revid.rindex("-")
        uuid = revid[at+1:fash]
        branch_path = unescape_svn_path(revid[fash+1:])
        revnum = int(revid[0:at])
        assert revnum >= 0
        return (uuid, branch_path, revnum, None)


class BzrSvnMappingv3(BzrSvnMapping):
    revid_prefix = "svn-v3-"

    @classmethod
    def parse_revision_id(cls, revid):
        assert revid is not None
        assert isinstance(revid, str)

        if not revid.startswith(cls.revid_prefix):
            raise errors.InvalidRevisionId(revid, "")

        try:
            (version, uuid, branch_path, srevnum) = revid.split(":")
        except ValueError:
            raise errors.InvalidRevisionId(revid, "")

        scheme = version[len(cls.revid_prefix):]

        if scheme == "undefined":
            scheme = None

        return (uuid, unescape_svn_path(branch_path), int(srevnum), scheme)

    @classmethod
    def generate_revision_id(cls, uuid, revnum, path, scheme):
        assert isinstance(revnum, int)
        assert isinstance(path, str)
        assert revnum >= 0
        assert revnum > 0 or path == "", \
                "Trying to generate revid for (%r,%r)" % (path, revnum)
        return "%s%s:%s:%s:%d" % (cls.revid_prefix, scheme, uuid, \
                       escape_svn_path(path.strip("/")), revnum)

    @staticmethod
    def generate_file_id(uuid, revnum, branch, inv_path):
        assert isinstance(uuid, str)
        assert isinstance(revnum, int)
        assert isinstance(branch, str)
        assert isinstance(inv_path, unicode)
        inv_path = inv_path.encode("utf-8")
        ret = "%d@%s:%s:%s" % (revnum, uuid, escape_svn_path(branch), escape_svn_path(inv_path))
        if len(ret) > 150:
            ret = "%d@%s:%s;%s" % (revnum, uuid, 
                                escape_svn_path(branch),
                                sha.new(inv_path).hexdigest())
        assert isinstance(ret, str)
        return osutils.safe_file_id(ret)


class BzrSvnMappingRegistry(registry.Registry):
    def register(self, key, factory, help):
        """Register a mapping between Bazaar and Subversion semantics.

        The factory must be a callable that takes one parameter: the key.
        It must produce an instance of BzrSvnMapping when called.
        """
        registry.Registry.register(self, key, factory, help)

    def set_default(self, key):
        """Set the 'default' key to be a clone of the supplied key.

        This method must be called once and only once.
        """
        registry.Registry.register(self, 'default', self.get(key), 
            self.get_help(key))

mapping_registry = BzrSvnMappingRegistry()
mapping_registry.register('v1', BzrSvnMappingv1,
        'Original bzr-svn mapping format')
mapping_registry.register('v2', BzrSvnMappingv2,
        'Second format')
mapping_registry.register('v3', BzrSvnMappingv3,
        'Third format')
mapping_registry.set_default('v3')

default_mapping = BzrSvnMappingv3
