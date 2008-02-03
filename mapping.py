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

"""Maps between Subversion and Bazaar semantics."""

from bzrlib import osutils, registry
from bzrlib.errors import InvalidRevisionId
from bzrlib.trace import mutter

import calendar
import errors
from scheme import BranchingScheme, guess_scheme_from_branch_path
import sha
import svn
import time
import urllib

from svk import (SVN_PROP_SVK_MERGE, svk_features_merged_since, 
                 parse_svk_features, serialize_svk_features, 
                 parse_svk_feature, generate_svk_feature)

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
SVN_REVPROP_BZR_MAPPING_VERSION = 'bzr:mapping-version'
SVN_REVPROP_BZR_MERGE = 'bzr:merge'
SVN_REVPROP_BZR_REVISION_ID = 'bzr:revision-id'
SVN_REVPROP_BZR_REVNO = 'bzr:revno'
SVN_REVPROP_BZR_REVPROP_PREFIX = 'bzr:revprop:'
SVN_REVPROP_BZR_ROOT = 'bzr:root'
SVN_REVPROP_BZR_SCHEME = 'bzr:scheme'
SVN_REVPROP_BZR_SIGNATURE = 'bzr:gpg-signature'
SVN_REVPROP_BZR_TIMESTAMP = 'bzr:timestamp'


def escape_svn_path(x):
    """Escape a Subversion path for use in a revision identifier.

    :param x: Path
    :return: Escaped path
    """
    assert isinstance(x, str)
    return urllib.quote(x, "")
unescape_svn_path = urllib.unquote


# The following two functions don't use day names (which can vary by 
# locale) unlike the alternatives in bzrlib.timestamp

def format_highres_date(t, offset=0):
    """Format a date, such that it includes higher precision in the
    seconds field.

    :param t:   The local time in fractional seconds since the epoch
    :type t: float
    :param offset:  The timezone offset in integer seconds
    :type offset: int
    """
    assert isinstance(t, float)

    # This has to be formatted for "original" date, so that the
    # revision XML entry will be reproduced faithfully.
    if offset is None:
        offset = 0
    tt = time.gmtime(t + offset)

    return (time.strftime("%Y-%m-%d %H:%M:%S", tt)
            # Get the high-res seconds, but ignore the 0
            + ('%.9f' % (t - int(t)))[1:]
            + ' %+03d%02d' % (offset / 3600, (offset / 60) % 60))


def unpack_highres_date(date):
    """This takes the high-resolution date stamp, and
    converts it back into the tuple (timestamp, timezone)
    Where timestamp is in real UTC since epoch seconds, and timezone is an
    integer number of seconds offset.

    :param date: A date formated by format_highres_date
    :type date: string
    """
    # skip day if applicable
    if not date[0].isdigit():
        space_loc = date.find(' ')
        if space_loc == -1:
            raise ValueError("No valid date: %r" % date)
        date = date[space_loc+1:]
    # Up until the first period is a datestamp that is generated
    # as normal from time.strftime, so use time.strptime to
    # parse it
    dot_loc = date.find('.')
    if dot_loc == -1:
        raise ValueError(
            'Date string does not contain high-precision seconds: %r' % date)
    base_time = time.strptime(date[:dot_loc], "%Y-%m-%d %H:%M:%S")
    fract_seconds, offset = date[dot_loc:].split()
    fract_seconds = float(fract_seconds)

    offset = int(offset)

    hours = int(offset / 100)
    minutes = (offset % 100)
    seconds_offset = (hours * 3600) + (minutes * 60)

    # time.mktime returns localtime, but calendar.timegm returns UTC time
    timestamp = calendar.timegm(base_time)
    timestamp -= seconds_offset
    # Add back in the fractional seconds
    timestamp += fract_seconds
    return (timestamp, seconds_offset)


def parse_merge_property(line):
    """Parse a bzr:merge property value.

    :param line: Line to parse
    :return: List of revisions merged
    """
    if ' ' in line:
        mutter('invalid revision id %r in merged property, skipping' % line)
        return []

    return filter(lambda x: x != "", line.split("\t"))

def parse_svn_revprops(svn_revprops, rev):
    if svn_revprops.has_key(svn.core.SVN_PROP_REVISION_AUTHOR):
        rev.committer = svn_revprops[svn.core.SVN_PROP_REVISION_AUTHOR]
    else:
        rev.committer = ""

    rev.message = svn_revprops.get(svn.core.SVN_PROP_REVISION_LOG)

    if rev.message:
        try:
            rev.message = rev.message.decode("utf-8")
        except UnicodeDecodeError:
            pass

    if svn_revprops.has_key(svn.core.SVN_PROP_REVISION_DATE):
        rev.timestamp = 1.0 * svn.core.secs_from_timestr(svn_revprops[svn.core.SVN_PROP_REVISION_DATE], None)
    else:
        rev.timestamp = 0.0 # FIXME: Obtain repository creation time
    rev.timezone = None
    rev.properties = {}


def parse_revision_metadata(text, rev):
    """Parse a revision info text (as set in bzr:revision-info).

    :param text: text to parse
    :param rev: Revision object to apply read parameters to
    """
    in_properties = False
    for l in text.splitlines():
        try:
            key, value = l.split(": ", 2)
        except ValueError:
            raise errors.InvalidPropertyValue(SVN_PROP_BZR_REVISION_INFO, 
                    "Missing : in revision metadata")
        if key == "committer":
            rev.committer = value.decode("utf-8")
        elif key == "timestamp":
            (rev.timestamp, rev.timezone) = unpack_highres_date(value)
        elif key == "properties":
            in_properties = True
        elif key[0] == "\t" and in_properties:
            rev.properties[str(key[1:])] = value.decode("utf-8")
        else:
            raise errors.InvalidPropertyValue(SVN_PROP_BZR_REVISION_INFO, 
                    "Invalid key %r" % key)


def parse_revid_property(line):
    """Parse a (revnum, revid) tuple as set in revision id properties.
    :param line: line to parse
    :return: tuple with (bzr_revno, revid)
    """
    if '\n' in line:
        raise errors.InvalidPropertyValue(SVN_PROP_BZR_REVISION_ID, 
                "newline in revision id property line")
    try:
        (revno, revid) = line.split(' ', 1)
    except ValueError:
        raise errors.InvalidPropertyValue(SVN_PROP_BZR_REVISION_ID, 
                "missing space")
    if revid == "":
        raise errors.InvalidPropertyValue(SVN_PROP_BZR_REVISION_ID,
                "empty revision id")
    return (int(revno), revid)


def generate_revision_metadata(timestamp, timezone, committer, revprops):
    """Generate revision metadata text for the specified revision 
    properties.

    :param timestamp: timestamp of the revision, in seconds since epoch
    :param timezone: timezone, specified by offset from GMT in seconds
    :param committer: name/email of the committer
    :param revprops: dictionary with custom revision properties
    :return: text with data to set bzr:revision-info to.
    """
    assert timestamp is None or isinstance(timestamp, float)
    text = ""
    if timestamp is not None:
        text += "timestamp: %s\n" % format_highres_date(timestamp, timezone) 
    if committer is not None:
        text += "committer: %s\n" % committer
    if revprops is not None and revprops != {}:
        text += "properties: \n"
        for k, v in sorted(revprops.items()):
            text += "\t%s: %s\n" % (k, v)
    return text


def parse_bzr_svn_revprops(props, rev):
    """Update a Revision object from a set of Subversion revision properties.
    
    :param props: Dictionary with Subversion revision properties.
    :param rev: Revision object
    """
    if props.has_key(SVN_REVPROP_BZR_TIMESTAMP):
        (rev.timestamp, rev.timezone) = unpack_highres_date(props[SVN_REVPROP_BZR_TIMESTAMP])

    if props.has_key(SVN_REVPROP_BZR_COMMITTER):
        rev.committer = props[SVN_REVPROP_BZR_COMMITTER].decode("utf-8")

    for name, value in props.items():
        if name.startswith(SVN_REVPROP_BZR_REVPROP_PREFIX):
            rev.properties[name[len(SVN_REVPROP_BZR_REVPROP_PREFIX):]] = value


class BzrSvnMapping:
    """Class that maps between Subversion and Bazaar semantics."""

    @staticmethod
    def supports_roundtripping():
        """Whether this mapping supports roundtripping.
        """
        return False

    def parse_revision_id(self, revid):
        """Parse an existing Subversion-based revision id.

        :param revid: The revision id.
        :raises: InvalidRevisionId
        :return: Tuple with uuid, branch path, revision number and scheme.
        """
        raise NotImplementedError(self.parse_revision_id)

    def generate_revision_id(self, uuid, revnum, path):
        """Generate a unambiguous revision id. 
        
        :param uuid: UUID of the repository.
        :param revnum: Subversion revision number.
        :param path: Branch path.

        :return: New revision id.
        """
        raise NotImplementedError(self.generate_revision_id)

    def is_branch(self, branch_path):
        raise NotImplementedError(self.is_branch)

    def is_tag(self, tag_path):
        raise NotImplementedError(self.is_tag)

    @staticmethod
    def generate_file_id(uuid, revnum, branch, inv_path):
        """Create a file id identifying a Subversion file.

        :param uuid: UUID of the repository
        :param revnum: Revision number at which the file was introduced.
        :param branch: Branch path of the branch in which the file was introduced.
        :param inv_path: Original path of the file within the inventory
        """
        raise NotImplementedError(self.generate_file_id)

    @staticmethod
    def import_revision(revprops, get_branch_file_property, rev):
        """Update a Revision object from Subversion revision and branch 
        properties.

        :param revprops: Dictionary with Subversion revision properties.
        :param get_branch_file_property: Function that takes a string and
            returns the value of the matching file property set on the branch 
            path.
        :param rev: Revision object to import data into.
        """
        raise NotImplementedError(self.import_revision)

    def get_rhs_parents(self, revprops, get_branch_file_property):
        """Obtain the right-hand side parents for a revision.

        """
        raise NotImplementedError(self.get_rhs_parents)

    def get_rhs_ancestors(self, revprops, get_branch_file_property):
        """Obtain the right-hand side ancestors for a revision.

        """
        raise NotImplementedError(self.get_rhs_ancestors)

    @staticmethod
    def import_fileid_map(revprops, get_branch_file_property):
        """Obtain the file id map for a revision from the properties.

        """
        raise NotImplementedError(self.import_fileid_map)

    @staticmethod
    def export_fileid_map(fileids, revprops, fileprops):
        """Adjust the properties for a file id map.

        :param fileids: Dictionary
        :param revprops: Subversion revision properties
        :param fileprops: File properties
        """
        raise NotImplementedError(self.export_fileid_map)

    def export_revision(self, branch_root, timestamp, timezone, committer, revprops, 
                        revision_id, revno, merges, get_branch_file_property):
        """Determines the revision properties and branch root file 
        properties.
        """
        raise NotImplementedError(self.export_revision)

    def get_revision_id(self ,revprops, get_branch_file_property):
        raise NotImplementedError(self.get_revision_id)

    def unprefix(self, branch_path, repos_path):
        raise NotImplementedError(self.unprefix)


class BzrSvnMappingv1(BzrSvnMapping):
    """This was the initial version of the mappings as used by bzr-svn
    0.2.
    
    It does not support pushing revisions to Subversion as-is, but only 
    as part of a merge.
    """
    @classmethod
    def parse_revision_id(cls, revid):
        if not revid.startswith("svn-v1:"):
            raise InvalidRevisionId(revid, "")
        revid = revid[len("svn-v1:"):]
        at = revid.index("@")
        fash = revid.rindex("-")
        uuid = revid[at+1:fash]
        branch_path = unescape_svn_path(revid[fash+1:])
        revnum = int(revid[0:at])
        assert revnum >= 0
        return (uuid, branch_path, revnum, cls())

    def generate_revision_id(self, uuid, revnum, path):
        return "svn-v1:%d@%s-%s" % (revnum, uuid, escape_svn_path(path))

    def __eq__(self, other):
        return type(self) == type(other)


class BzrSvnMappingv2(BzrSvnMapping):
    """The second version of the mappings as used in the 0.3.x series.

    """
    @classmethod
    def parse_revision_id(cls, revid):
        if not revid.startswith("svn-v2:"):
            raise InvalidRevisionId(revid, "")
        revid = revid[len("svn-v2:"):]
        at = revid.index("@")
        fash = revid.rindex("-")
        uuid = revid[at+1:fash]
        branch_path = unescape_svn_path(revid[fash+1:])
        revnum = int(revid[0:at])
        assert revnum >= 0
        return (uuid, branch_path, revnum, cls())

    def generate_revision_id(self, uuid, revnum, path):
        return "svn-v2:%d@%s-%s" % (revnum, uuid, escape_svn_path(path))

    def __eq__(self, other):
        return type(self) == type(other)


def parse_fileid_property(text):
    ret = {}
    for line in text.splitlines():
        (path, key) = line.split("\t", 2)
        ret[urllib.unquote(path)] = osutils.safe_file_id(key)
    return ret


def generate_fileid_property(fileids):
    """Marshall a dictionary with file ids."""
    return "".join(["%s\t%s\n" % (urllib.quote(path), fileids[path]) for path in sorted(fileids.keys())])


class BzrSvnMappingv3(BzrSvnMapping):
    """The third version of the mappings as used in the 0.4.x series.

    """
    revid_prefix = "svn-v3-"

    def __init__(self, scheme):
        self.scheme = scheme
        assert not isinstance(scheme, str)

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.scheme)

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

    def import_revision(self, svn_revprops, get_branch_file_property, rev):
        parse_svn_revprops(svn_revprops, rev)
        parse_revision_metadata(
                get_branch_file_property(SVN_PROP_BZR_REVISION_INFO, ""), rev)

    def _svk_merged_revisions(self, get_branch_file_property):
        """Find out what SVK features were merged in a revision.

        """
        current = get_branch_file_property(SVN_PROP_SVK_MERGE, "")
        (prev_path, prev_revnum) = self._log.get_previous(branch, revnum)
        if prev_path is None and prev_revnum == -1:
            previous = ""
        else:
            previous = self.branchprop_list.get_property(prev_path.encode("utf-8"), 
                         prev_revnum, SVN_PROP_SVK_MERGE, "")
        for feature in svk_features_merged_since(current, previous):
            revid = self._svk_feature_to_revision_id(feature)
            if revid is not None:
                yield revid

    def _svk_feature_to_revision_id(self, feature):
        """Convert a SVK feature to a revision id for this repository.

        :param feature: SVK feature.
        :return: revision id.
        """
        try:
            (uuid, bp, revnum) = parse_svk_feature(feature)
        except errors.InvalidPropertyValue:
            return None
        if uuid != self.uuid:
            return None
        if not self.scheme.is_branch(bp) and not self.scheme.is_tag(bp):
            return None
        return self.generate_revision_id(revnum, bp)

    def get_rhs_parents(self, revprops, get_branch_file_property):
        rhs_parents = []
        bzr_merges = get_branch_file_property(SVN_PROP_BZR_ANCESTRY+str(self.scheme), None)
        if bzr_merges is not None:
            return parse_merge_property(bzr_merges.splitlines()[-1])

        svk_merges = get_branch_file_property(SVN_PROP_SVK_MERGE, None)
        if svk_merges is not None:
            return self._svk_merged_revisions(get_branch_file_property)

        return []

    def get_rhs_ancestors(self, revprops, get_branch_file_property):
        ancestry = []
        for l in get_branch_file_property(SVN_PROP_BZR_ANCESTRY+str(self.scheme), "").splitlines():
            ancestry.extend(l.split("\n"))
        return ancestry

    def import_fileid_map(self, svn_revprops, get_branch_file_property):
        fileids = get_branch_file_property(SVN_PROP_BZR_FILEIDS, None)
        if fileids is None:
            return {}
        return parse_fileid_property(fileids)

    def _revision_id_to_svk_feature(self, revid):
        """Create a SVK feature identifier from a revision id.

        :param revid: Revision id to convert.
        :return: Matching SVK feature identifier.
        """
        assert isinstance(revid, str)
        (uuid, branch, revnum, _) = self.__class__.parse_revision_id(revid)
        # TODO: What about renamed revisions? Should use 
        # repository.lookup_revision_id here.
        return generate_svk_feature(uuid, branch, revnum)

    def _record_merges(self, merges, get_branch_file_property):
        """Store the extra merges (non-LHS parents) in a file property.

        :param merges: List of parents.
        """
        # Bazaar Parents
        old = get_branch_file_property(SVN_PROP_BZR_ANCESTRY+str(self.scheme), "")
        svnprops = { SVN_PROP_BZR_ANCESTRY+str(self.scheme): old + "\t".join(merges) + "\n" }

        old_svk_features = parse_svk_features(get_branch_file_property(SVN_PROP_SVK_MERGE, ""))
        svk_features = set(old_svk_features)

        # SVK compatibility
        for merge in merges:
            try:
                svk_features.add(self._revision_id_to_svk_feature(merge))
            except InvalidRevisionId:
                pass

        if old_svk_features != svk_features:
            svnprops[SVN_PROP_SVK_MERGE] = serialize_svk_features(svk_features)

        return svnprops
 
    def export_revision(self, branch_root, timestamp, timezone, committer, revprops, revision_id, revno, merges, 
                        get_branch_file_property):
        # Keep track of what Subversion properties to set later on
        fileprops = {}
        fileprops[SVN_PROP_BZR_REVISION_INFO] = generate_revision_metadata(
            timestamp, timezone, committer, revprops)

        if len(merges) > 0:
            fileprops.update(self._record_merges(merges, get_branch_file_property))

        # Set appropriate property if revision id was specified by 
        # caller
        if revision_id is not None:
            old = get_branch_file_property(SVN_PROP_BZR_REVISION_ID+str(self.scheme), "")
            fileprops[SVN_PROP_BZR_REVISION_ID+str(self.scheme)] = old + "%d %s\n" % (revno, revision_id)

        return ({}, fileprops)

    def get_revision_id(self, revprops, get_branch_file_property):
        # Lookup the revision from the bzr:revision-id-vX property
        text = get_branch_file_property(SVN_PROP_BZR_REVISION_ID+str(self.scheme), None)
        if text is None:
            return (None, None)

        lines = text.splitlines()
        if len(lines) == 0:
            return (None, None)

        try:
            return parse_revid_property(lines[-1])
        except errors.InvalidPropertyValue, e:
            mutter(str(e))
            return (None, None)

    def export_fileid_map(self, fileids, revprops, fileprops):
        if fileids != {}:
            file_id_text = generate_fileid_property(fileids)
            fileprops[SVN_PROP_BZR_FILEIDS] = file_id_text
        else:
            fileprops[SVN_PROP_BZR_FILEIDS] = ""

    def unprefix(self, branch_path, repos_path):
        (bp, np) = self.scheme.unprefix(repos_path)
        assert branch_path == bp
        return np

    def __eq__(self, other):
        return type(self) == type(other) and self.scheme == other.scheme


class BzrSvnMappingv4:
    @staticmethod
    def supports_roundtripping():
        return True

    def import_revision(self, svn_revprops, get_branch_file_property, rev):
        parse_svn_revprops(svn_revprops, rev)
        parse_bzr_svn_revprops(svn_revprops, rev)

    def import_fileid_map(self, svn_revprops, get_branch_file_property):
        if not svn_revprops.has_key(SVN_REVPROP_BZR_FILEIDS):
            return {}
        return parse_fileid_property(svn_revprops[SVN_REVPROP_BZR_FILEIDS])

    def get_rhs_parents(self, svn_revprops, get_branch_file_property):
        if svn_revprops[SVN_REVPROP_BZR_ROOT] != branch:
            return []
        return svn_revprops.get(SVN_REVPROP_BZR_MERGE, "").splitlines()

    def get_revision_id(self, revprops, get_branch_file_property):
        if revprops[SVN_REVPROP_BZR_ROOT] == path:
            revid = revprops[SVN_REVPROP_BZR_REVISION_ID]
            revno = int(revprops[SVN_REVPROP_BZR_REVNO])
            return (revno, revid)
        return (None, None)

    def export_revision(self, branch_root, timestamp, timezone, committer, revprops, revision_id, revno, 
                        merges, get_branch_file_property):
        svn_revprops = {SVN_REVPROP_BZR_MAPPING_VERSION: str(MAPPING_VERSION)}

        if timestamp is not None:
            svn_revprops[SVN_REVPROP_BZR_TIMESTAMP] = format_highres_date(timestamp, timezone)

        if committer is not None:
            svn_revprops[SVN_REVPROP_BZR_COMMITTER] = committer.encode("utf-8")

        if revprops is not None:
            for name, value in revprops.items():
                svn_revprops[SVN_REVPROP_BZR_REVPROP_PREFIX+name] = value

        svn_revprops[SVN_REVPROP_BZR_ROOT] = branch_root

        if revision_id is not None:
            svn_revprops[SVN_REVPROP_BZR_REVISION_ID] = revid

        if merges != []:
            svn_revprops[SVN_REVPROP_BZR_MERGE] = "".join([x+"\n" for x in merges])
        svn_revprops[SVN_REVPROP_BZR_REVNO] = str(revno)

        return (svn_revprops, {})

    def export_fileid_map(self, fileids, revprops, fileprops):
        revprops[SVN_REVPROP_BZR_FILEIDS] = generate_fileid_property(fileids)

    def get_rhs_ancestors(self, revprops, get_branch_file_property):
        raise NotImplementedError(self.get_rhs_ancestors)

    @classmethod
    def parse_revision_id(cls, revid):
        raise NotImplementedError(self.parse_revision_id)

    def generate_revision_id(self, uuid, revnum, path):
        raise NotImplementedError(self.generate_revision_id)

    def generate_file_id(self, uuid, revnum, branch, inv_path):
        raise NotImplementedError(self.generate_file_id)

    def is_branch(self, branch_path):
        return True

    def is_tag(self, tag_path):
        return True

    def __eq__(self, other):
        return type(self) == type(other)


class BzrSvnMappingHybrid:
    @staticmethod
    def supports_roundtripping():
        return True

    def get_rhs_parents(self, svn_revprops, get_branch_file_property):
        if svn_revprops.has_key(SVN_REVPROP_BZR_MAPPING_VERSION):
            return BzrSvnMappingv4.get_rhs_parents(self, svn_revprops, get_branch_file_property)
        else:
            return BzrSvnMappingv3.get_rhs_parents(self, svn_revprops, get_branch_file_property)

    def get_revision_id(self, revprops, get_branch_file_property):
        if revprops.has_key(SVN_REVPROP_BZR_MAPPING_VERSION):
            return BzrSvnMappingv4.get_revision_id(self, revprops, get_branch_file_property)
        else:
            return BzrSvnMappingv3.get_revision_id(self, revprops, get_branch_file_property)

    def import_fileid_map(self, svn_revprops, get_branch_file_property):
        if svn_revprops.has_key(SVN_REVPROP_BZR_MAPPING_VERSION):
            return BzrSvnMappingv4.import_fileid_map(self, svn_revprops, get_branch_file_property)
        else:
            return BzrSvnMappingv3.import_fileid_map(self, svn_revprops, get_branch_file_property)

    def export_revision(self, branch_root, timestamp, timezone, committer, revprops, revision_id, revno, 
                        merges, get_branch_file_property):
        (_, fileprops) = BzrSvnMappingv3.export_revision(self, branch_root, timestamp, timezone, committer, 
                                      revprops, revision_id, revno, merges, get_branch_file_property)
        (revprops, _) = BzrSvnMappingv4.export_revision(self, branch_root, timestamp, timezone, committer, 
                                      revprops, revision_id, revno, merges, get_branch_file_property)
        return (revprops, fileprops)

    def parse_revision_id(self, revid):
        raise NotImplementedError(self.parse_revision_id)

    def generate_revision_id(self, uuid, revnum, path):
        raise NotImplementedError(self.generate_revision_id)

    def generate_file_id(self, uuid, revnum, branch, inv_path):
        raise NotImplementedError(self.generate_file_id)

    def export_fileid_map(self, fileids, revprops, fileprops):
        BzrSvnMappingv3.export_fileid_map(self, fileids, revprops, fileprops)
        BzrSvnMappingv4.export_fileid_map(self, fileids, revprops, fileprops)

    def import_revision(self, svn_revprops, get_branch_file_property, rev):
        BzrSvnMappingv3.import_revision(self, svn_revprops, get_branch_file_property, rev)
        BzrSvnMappingv4.import_revision(self, svn_revprops, get_branch_file_property, rev)


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
mapping_registry.register('v4', BzrSvnMappingv3,
        'Fourth format')
mapping_registry.register('hybrid', BzrSvnMappingHybrid,
        'Hybrid v3 and v4 format')
mapping_registry.set_default('v3')


def parse_revision_id(revid):
    """Try to parse a Subversion revision id.
    
    :param revid: Revision id to parse
    :return: tuple with (uuid, branch_path, mapping)
    """
    if revid.startswith("svn-"):
        try:
            mapping_version = revid[len("svn-"):len("svn-vx")]
            mapping = mapping_registry.get(mapping_version)
            return mapping.parse_revision_id(revid)
        except KeyError:
            pass

    raise InvalidRevisionId(revid, None)

def get_default_mapping():
    return mapping_registry.get("default")
