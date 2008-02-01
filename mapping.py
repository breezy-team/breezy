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

from bzrlib import osutils, registry
from bzrlib.errors import InvalidRevisionId
from bzrlib.trace import mutter

import calendar
import errors
import sha
import svn
import time
import urllib

from svk import SVN_PROP_SVK_MERGE

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

    @staticmethod
    def parse_svn_revision(revprops, get_branch_file_property, rev):
        """Update a Revision object from Subversion revision and branch 
        properties.

        :param revprops: Dictionary with Subversion revision properties.
        :param get_branch_file_property: Function that takes a string and
            returns the value of the matching file property set on the branch 
            path.
        :param rev: Revision object to import data into.
        """
        raise NotImplementedError(self.parse_svn_revision)

    @staticmethod
    def get_rhs_parents(self, revnum, branch):
        """Obtain the right-hand side parents for a revision.

        """
        raise NotImplementedError(self.get_rhs_parents)


class BzrSvnMappingv1(BzrSvnMapping):
    """This was the initial version of the mappings as used by bzr-svn
    0.2.
    
    It does not support pushing revisions to Subversion as-is, but only 
    as part of a merge.
    """
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
    """The second version of the mappings as used in the 0.3.x series.

    """
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
    """The third version of the mappings as used in the 0.4.x series.

    """
    revid_prefix = "svn-v3-"

    @classmethod
    def parse_revision_id(cls, revid):
        assert revid is not None
        assert isinstance(revid, str)

        if not revid.startswith(cls.revid_prefix):
            raise InvalidRevisionId(revid, "")

        try:
            (version, uuid, branch_path, srevnum) = revid.split(":")
        except ValueError:
            raise InvalidRevisionId(revid, "")

        scheme = version[len(cls.revid_prefix):]

        # Some older versions of bzr-svn 0.4 did not always set a branching
        # scheme but set "undefined" instead.
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

    @staticmethod
    def parse_svn_revision(svn_revprops, get_branch_file_property, rev):
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
        parse_revision_metadata(
                get_branch_file_property(SVN_PROP_BZR_REVISION_INFO, ""), rev)

    @classmethod
    def get_rhs_parents(cls, revprops, get_branch_file_property, scheme):
        rhs_parents = []
        bzr_merges = get_branch_file_property(SVN_PROP_BZR_ANCESTRY+str(scheme), None)
        if bzr_merges is not None:
            return parse_merge_property(bzr_merges.splitlines()[-1])

        svk_merges = get_branch_file_property(SVN_PROP_SVK_MERGE, None)
        if svk_merges is not None:
            _merges = cls._svk_merged_revisions(branch, revnum, scheme)

        return []


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
