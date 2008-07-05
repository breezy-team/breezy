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

from bzrlib import osutils, ui
from bzrlib.errors import InvalidRevisionId
from bzrlib.trace import mutter

from bzrlib.plugins.svn import mapping, properties
from bzrlib.plugins.svn.core import SubversionException, NODE_DIR
from bzrlib.plugins.svn.errors import ERR_FS_NOT_DIRECTORY, ERR_FS_NOT_FOUND, ERR_RA_DAV_PATH_NOT_FOUND
from bzrlib.plugins.svn.layout import RepositoryLayout
from bzrlib.plugins.svn.mapping3.scheme import (BranchingScheme, guess_scheme_from_branch_path, 
                             guess_scheme_from_history, ListBranchingScheme, 
                             parse_list_scheme_text, NoBranchingScheme,
                             TrunkBranchingScheme, ListBranchingScheme)
import sha

SVN_PROP_BZR_BRANCHING_SCHEME = 'bzr:branching-scheme'

# Number of revisions to evaluate when guessing the branching scheme
SCHEME_GUESS_SAMPLE_SIZE = 2000

def expand_branch_pattern(begin, todo, check_path, get_children):
    """Find the paths in the repository that match the expected branch pattern.

    :param begin: List of path elements currently opened.
    :param todo: List of path elements to still evaluate (including wildcards)
    :param check_path: Function for checking a path exists
    :param get_children: Function for retrieving the children of a path
    """
    mutter('expand branches: %r, %r', begin, todo)
    path = "/".join(begin)
    # If all elements have already been handled, just check the path exists
    if len(todo) == 0:
        if check_path(path):
            return [path]
        else:
            return []
    # Not a wildcard? Just expand next bits
    if todo[0] != "*":
        return expand_branch_pattern(begin+[todo[0]], todo[1:], check_path, get_children)
    children = get_children(path)
    if children is None:
        return []
    ret = []
    pb = ui.ui_factory.nested_progress_bar()
    try:
        for idx, c in enumerate(children):
            pb.update("browsing branches", idx, len(children))
            if len(todo) == 1:
                # Last path element, so return directly
                ret.append("/".join(begin+[c]))
            else:
                ret += expand_branch_pattern(begin+[c], todo[1:], check_path, get_children)
    finally:
        pb.finished()
    return ret


class SchemeDerivedLayout(RepositoryLayout):
    def __init__(self, repository, scheme):
        self.repository = repository
        self.scheme = scheme

    def parse(self, path):
        (bp, rp) = self.scheme.unprefix(path)
        if self.scheme.is_tag(bp):
            type = "tag"
        else:
            type = "branch"
        return (type, "", bp, rp)

    def _get_root_paths(self, revnum, verify_fn, project="", pb=None):
        def check_path(path):
            return self.repository.transport.check_path(path, revnum) == NODE_DIR
        def find_children(path):
            try:
                assert not path.startswith("/")
                dirents = self.repository.transport.get_dir(path, revnum)[0]
            except SubversionException, (msg, num):
                if num in (ERR_FS_NOT_DIRECTORY, ERR_FS_NOT_FOUND, ERR_RA_DAV_PATH_NOT_FOUND):
                    return None
                raise
            return dirents.keys()

        for idx, pattern in enumerate(self.scheme.branch_list):
            if pb is not None:
                pb.update("finding branches", idx, len(self.scheme.branch_list))
            for bp in expand_branch_pattern([], pattern.split("/"), check_path,
                    find_children):
                if verify_fn(bp):
                    yield "", bp, bp.split("/")[-1]

    def get_branches(self, revnum, project="", pb=None):
        return self._get_root_paths(revnum, self.scheme.is_branch, project, pb)

    def get_tags(self, revnum, project="", pb=None):
        return self._get_root_paths(revnum, self.scheme.is_tag, project, pb)

    def get_tag_path(self, name, project=""):
        return self.scheme.get_tag_path(name)

    def is_branch_parent(self, path):
        # Na, na, na...
        return self.scheme.is_branch_parent(path)

    def is_tag_parent(self, path):
        # Na, na, na...
        return self.scheme.is_tag_parent(path)


def get_stored_scheme(repository):
    """Retrieve the stored branching scheme, either in the repository 
    or in the configuration file.
    """
    scheme = repository.get_config().get_branching_scheme()
    if scheme is not None:
        return (scheme, repository.get_config().branching_scheme_is_mandatory())

    last_revnum = repository.get_latest_revnum()
    scheme = get_property_scheme(repository, last_revnum)
    if scheme is not None:
        return (scheme, True)

    return (None, False)


def get_property_scheme(repository, revnum=None):
    if revnum is None:
        revnum = repository.get_latest_revnum()
    text = repository.branchprop_list.get_properties("", revnum).get(SVN_PROP_BZR_BRANCHING_SCHEME, None)
    if text is None:
        return None
    return ListBranchingScheme(parse_list_scheme_text(text))


def set_property_scheme(repository, scheme):
    conn = repository.transport.get_connection()
    try:
        editor = conn.get_commit_editor(
            {properties.PROP_REVISION_LOG: "Updating branching scheme for Bazaar."},
            None, None, False)
        root = editor.open_root()
        root.change_prop(SVN_PROP_BZR_BRANCHING_SCHEME, 
                "".join(map(lambda x: x+"\n", scheme.branch_list)).encode("utf-8"))
        root.close()
        editor.close()
    finally:
        repository.transport.add_connection(conn)


def repository_guess_scheme(repository, last_revnum, branch_path=None):
    pb = ui.ui_factory.nested_progress_bar()
    try:
        scheme = guess_scheme_from_history(
            repository._log.iter_changes(None, last_revnum, max(0, last_revnum-SCHEME_GUESS_SAMPLE_SIZE), pb=pb), last_revnum, branch_path)
    finally:
        pb.finished()
    mutter("Guessed branching scheme: %r" % scheme)
    return scheme


def config_set_scheme(repository, scheme, mandatory=False):
    repository.get_config().set_branching_scheme(str(scheme), 
                                                 mandatory=mandatory)

def set_branching_scheme(repository, scheme, mandatory=False):
    repository.get_mapping().scheme = scheme
    config_set_scheme(repository, scheme, mandatory)


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

    def get_mandated_layout(self, repository):
        return SchemeDerivedLayout(repository, self.scheme)

    @classmethod
    def from_repository(cls, repository, _hinted_branch_path=None):
        (scheme, mandatory) = get_stored_scheme(repository)
        if mandatory:
            return cls(scheme) 

        if scheme is not None:
            if (_hinted_branch_path is None or 
                scheme.is_branch(_hinted_branch_path)):
                return cls(scheme)

        last_revnum = repository.get_latest_revnum()
        scheme = repository_guess_scheme(repository, last_revnum, _hinted_branch_path)
        if last_revnum > 20:
            config_set_scheme(repository, scheme, mandatory=False)

        return cls(scheme)

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.scheme)

    def generate_file_id(self, uuid, revnum, branch, inv_path):
        assert isinstance(uuid, str)
        assert isinstance(revnum, int)
        assert isinstance(branch, str)
        assert isinstance(inv_path, unicode)
        inv_path = inv_path.encode("utf-8")
        ret = "%d@%s:%s:%s" % (revnum, uuid, mapping.escape_svn_path(branch), 
                               mapping.escape_svn_path(inv_path))
        if len(ret) > 150:
            ret = "%d@%s:%s;%s" % (revnum, uuid, 
                                mapping.escape_svn_path(branch),
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

        branch_path = mapping.unescape_svn_path(branch_path)

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
                       mapping.escape_svn_path(path.strip("/")), revnum)

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
        if svn_revprops.has_key(mapping.SVN_REVPROP_BZR_MAPPING_VERSION):
            return self.revprops.get_rhs_parents(branch_path, svn_revprops, fileprops)
        else:
            return self.fileprops.get_rhs_parents(branch_path, svn_revprops, fileprops)

    def get_revision_id(self, branch_path, revprops, fileprops):
        if revprops.has_key(mapping.SVN_REVPROP_BZR_MAPPING_VERSION):
            return self.revprops.get_revision_id(branch_path, revprops, fileprops)
        else:
            return self.fileprops.get_revision_id(branch_path, revprops, fileprops)

    def import_fileid_map(self, svn_revprops, fileprops):
        if svn_revprops.has_key(mapping.SVN_REVPROP_BZR_MAPPING_VERSION):
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

    def import_revision(self, svn_revprops, fileprops, uuid, branch, revnum, rev):
        self.fileprops.import_revision(svn_revprops, fileprops, uuid, branch, revnum, rev)
        self.revprops.import_revision(svn_revprops, fileprops, uuid, branch, revnum, rev)


