# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>
 
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

import mapping
from mapping3.scheme import BranchingScheme, guess_scheme_from_branch_path

class BzrSvnMappingv3(mapping.BzrSvnMapping):
    """The third version of the mappings as used in the 0.4.x series.

    """
    experimental = False
    upgrade_suffix = "-svn3"
    revid_prefix = "svn-v3-"

    def __init__(self, scheme):
        mapping.BzrSvnMapping.__init__(self)
        self.scheme = scheme
        assert not isinstance(scheme, str)

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.scheme)

    def generate_file_id(self, uuid, revnum, branch, inv_path):
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

    @staticmethod
    def supports_roundtripping():
        return True

    @classmethod
    def _parse_revision_id(cls, revid):
        assert isinstance(revid, str)

        if not revid.startswith(cls.revid_prefix):
            raise InvalidRevisionId(revid, "")

        try:
            (version, uuid, branch_path, srevnum) = revid.split(":")
        except ValueError:
            raise InvalidRevisionId(revid, "")

        scheme = version[len(cls.revid_prefix):]

        branch_path = unescape_svn_path(branch_path)

        return (uuid, branch_path, int(srevnum), scheme)

    @classmethod
    def parse_revision_id(cls, revid):
        (uuid, branch_path, srevnum, scheme) = cls._parse_revision_id(revid)
        # Some older versions of bzr-svn 0.4 did not always set a branching
        # scheme but set "undefined" instead.
        if scheme == "undefined":
            scheme = guess_scheme_from_branch_path(branch_path)
        else:
            scheme = BranchingScheme.find_scheme(scheme)

        return (uuid, branch_path, srevnum, cls(scheme))

    def is_branch(self, branch_path):
        return (self.scheme.is_branch(branch_path) or 
                self.scheme.is_tag(branch_path))

    def is_tag(self, tag_path):
        return self.scheme.is_tag(tag_path)

    @classmethod
    def _generate_revision_id(cls, uuid, revnum, path, scheme):
        assert isinstance(revnum, int)
        assert isinstance(path, str)
        assert revnum >= 0
        assert revnum > 0 or path == "", \
                "Trying to generate revid for (%r,%r)" % (path, revnum)
        return "%s%s:%s:%s:%d" % (cls.revid_prefix, scheme, uuid, \
                       escape_svn_path(path.strip("/")), revnum)

    def generate_revision_id(self, uuid, revnum, path):
        return self._generate_revision_id(uuid, revnum, path, self.scheme)

    def unprefix(self, branch_path, repos_path):
        (bp, np) = self.scheme.unprefix(repos_path)
        assert branch_path == bp
        return np

    def __eq__(self, other):
        return type(self) == type(other) and self.scheme == other.scheme


class BzrSvnMappingv3FileProps(mapping.BzrSvnMappingFileProps, BzrSvnMappingv3):
    pass


class BzrSvnMappingv3RevProps(mapping.BzrSvnMappingRevProps, BzrSvnMappingv3):
    pass


class BzrSvnMappingv3Hybrid(BzrSvnMappingv3):
    def __init__(self, scheme):
        BzrSvnMappingv3.__init__(self, scheme)
        self.revprops = BzrSvnMappingv3RevProps(scheme)
        self.fileprops = BzrSvnMappingv3FileProps(scheme)

    def get_rhs_parents(self, branch_path, svn_revprops, fileprops):
        if svn_revprops.has_key(SVN_REVPROP_BZR_MAPPING_VERSION):
            return self.revprops.get_rhs_parents(branch_path, svn_revprops, fileprops)
        else:
            return self.fileprops.get_rhs_parents(branch_path, svn_revprops, fileprops)

    def get_revision_id(self, branch_path, revprops, fileprops):
        if revprops.has_key(SVN_REVPROP_BZR_MAPPING_VERSION):
            return self.revprops.get_revision_id(branch_path, revprops, fileprops)
        else:
            return self.fileprops.get_revision_id(branch_path, revprops, fileprops)

    def import_fileid_map(self, svn_revprops, fileprops):
        if svn_revprops.has_key(SVN_REVPROP_BZR_MAPPING_VERSION):
            return self.revprops.import_fileid_map(svn_revprops, fileprops)
        else:
            return self.fileprops.import_fileid_map(svn_revprops, fileprops)

    def export_revision(self, branch_root, timestamp, timezone, committer, revprops, revision_id, 
                        revno, merges, fileprops):
        (_, fileprops) = self.fileprops.export_revision(branch_root, timestamp, timezone, committer, 
                                      revprops, revision_id, revno, merges, fileprops)
        (revprops, _) = self.revprops.export_revision(branch_root, timestamp, timezone, committer, 
                                      revprops, revision_id, revno, merges, fileprops)
        return (revprops, fileprops)

    def export_fileid_map(self, fileids, revprops, fileprops):
        self.fileprops.export_fileid_map(fileids, revprops, fileprops)
        self.revprops.export_fileid_map(fileids, revprops, fileprops)

    def import_revision(self, svn_revprops, fileprops, rev):
        self.fileprops.import_revision(svn_revprops, fileprops, rev)
        self.revprops.import_revision(svn_revprops, fileprops, rev)


