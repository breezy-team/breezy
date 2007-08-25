# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""Subversion repository access."""

import bzrlib
from bzrlib import osutils, ui
from bzrlib.branch import BranchCheckResult
from bzrlib.errors import (InvalidRevisionId, NoSuchRevision, 
                           NotBranchError, UninitializableFormat)
from bzrlib.inventory import Inventory
from bzrlib.lockable_files import LockableFiles, TransportLock
from bzrlib.repository import Repository, RepositoryFormat
from bzrlib.revisiontree import RevisionTree
from bzrlib.revision import Revision, NULL_REVISION
from bzrlib.transport import Transport, get_transport
from bzrlib.trace import mutter

from svn.core import SubversionException, Pool
import svn.core

import os

from branchprops import BranchPropertyList
from cache import create_cache_dir, sqlite3
import calendar
from config import SvnRepositoryConfig
import errors
import logwalker
from revids import (generate_svn_revision_id, parse_svn_revision_id, 
                    MAPPING_VERSION, RevidMap)
from scheme import (BranchingScheme, ListBranchingScheme, 
                    parse_list_scheme_text, guess_scheme_from_history)
from tree import SvnRevisionTree
import time
import urllib

SVN_PROP_BZR_PREFIX = 'bzr:'
SVN_PROP_BZR_ANCESTRY = 'bzr:ancestry:v%d-' % MAPPING_VERSION
SVN_PROP_BZR_FILEIDS = 'bzr:file-ids'
SVN_PROP_BZR_MERGE = 'bzr:merge'
SVN_PROP_SVK_MERGE = 'svk:merge'
SVN_PROP_BZR_REVISION_INFO = 'bzr:revision-info'
SVN_REVPROP_BZR_SIGNATURE = 'bzr:gpg-signature'
SVN_PROP_BZR_REVISION_ID = 'bzr:revision-id:v%d-' % MAPPING_VERSION
SVN_PROP_BZR_BRANCHING_SCHEME = 'bzr:branching-scheme'

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


def parse_revid_property(line):
    """Parse a (revnum, revid) tuple as set in revision id properties.
    :param line: line to parse
    :return: tuple with (bzr_revno, revid)
    """
    assert not '\n' in line
    try:
        (revno, revid) = line.split(' ', 1)
    except ValueError:
        raise errors.InvalidPropertyValue(SVN_PROP_BZR_REVISION_ID, 
                "missing space")
    if revid == "":
        raise errors.InvalidPropertyValue(SVN_PROP_BZR_REVISION_ID,
                "empty revision id")
    return (int(revno), revid)


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
            rev.committer = str(value)
        elif key == "timestamp":
            (rev.timestamp, rev.timezone) = unpack_highres_date(value)
        elif key == "properties":
            in_properties = True
        elif key[0] == "\t" and in_properties:
            rev.properties[str(key[1:])] = str(value)
        else:
            raise errors.InvalidPropertyValue(SVN_PROP_BZR_REVISION_INFO, 
                    "Invalid key %r" % key)


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


def parse_svk_feature(feature):
    """Parse a svk feature identifier.

    :param feature: The feature identifier as string.
    :return: tuple with uuid, branch path and revnum
    """
    try:
        (uuid, branch, revnum) = feature.split(":", 3)
    except ValueError:
        raise errors.InvalidPropertyValue(SVN_PROP_SVK_MERGE, 
                "not enough colons")
    return (uuid, branch.strip("/"), int(revnum))


def revision_id_to_svk_feature(revid):
    """Create a SVK feature identifier from a revision id.

    :param revid: Revision id to convert.
    :return: Matching SVK feature identifier.
    """
    (uuid, branch, revnum, _) = parse_svn_revision_id(revid)
    # TODO: What about renamed revisions? Should use 
    # repository.lookup_revision_id here.
    return "%s:/%s:%d" % (uuid, branch, revnum)


class SvnRepositoryFormat(RepositoryFormat):
    """Repository format for Subversion repositories (accessed using svn_ra).
    """
    rich_root_data = True

    def __get_matchingbzrdir(self):
        from format import SvnFormat
        return SvnFormat()

    _matchingbzrdir = property(__get_matchingbzrdir)

    def __init__(self):
        super(SvnRepositoryFormat, self).__init__()

    def get_format_description(self):
        return "Subversion Repository"

    def initialize(self, url, shared=False, _internal=False):
        """Svn repositories cannot be created (yet)."""
        raise UninitializableFormat(self)

    def check_conversion_target(self, target_repo_format):
        return target_repo_format.rich_root_data

cachedbs = {}

class SvnRepository(Repository):
    """
    Provides a simplified interface to a Subversion repository 
    by using the RA (remote access) API from subversion
    """
    def __init__(self, bzrdir, transport, branch_path=None):
        from fileids import SimpleFileIdMap
        _revision_store = None

        assert isinstance(transport, Transport)

        control_files = LockableFiles(transport, '', TransportLock)
        Repository.__init__(self, SvnRepositoryFormat(), bzrdir, 
            control_files, None, None, None)

        self.transport = transport
        self.uuid = transport.get_uuid()
        assert self.uuid is not None
        self.base = transport.base
        assert self.base is not None
        self._serializer = None
        self.dir_cache = {}
        self.pool = Pool()
        self.config = SvnRepositoryConfig(self.uuid)
        self.config.add_location(self.base)
        self._revids_seen = {}
        cache_dir = self.create_cache_dir()
        cachedir_transport = get_transport(cache_dir)
        cache_file = os.path.join(cache_dir, 'cache-v%d' % MAPPING_VERSION)
        if not cachedbs.has_key(cache_file):
            cachedbs[cache_file] = sqlite3.connect(cache_file)
        self.cachedb = cachedbs[cache_file]

        self._log = logwalker.LogWalker(transport=transport, 
                                        cache_db=self.cachedb)

        self.branchprop_list = BranchPropertyList(self._log, self.cachedb)
        self.fileid_map = SimpleFileIdMap(self, cachedir_transport)
        self.revmap = RevidMap(self.cachedb)
        self._scheme = None
        self._hinted_branch_path = branch_path
    
    def get_transaction(self):
        raise NotImplementedError(self.get_transaction)

    def get_scheme(self):
        """Determine the branching scheme to use for this repository.

        :return: Branching scheme.
        """
        if self._scheme is not None:
            return self._scheme

        scheme = self.config.get_branching_scheme()
        if scheme is not None:
            self._scheme = scheme
            return scheme

        last_revnum = self.transport.get_latest_revnum()
        scheme = self._get_property_scheme(last_revnum)
        if scheme is not None:
            self.set_branching_scheme(scheme)
            return scheme

        self.set_branching_scheme(
            self._guess_scheme(last_revnum, self._hinted_branch_path),
            store=(last_revnum > 20))

        return self._scheme

    def _get_property_scheme(self, revnum=None):
        if revnum is None:
            revnum = self.transport.get_latest_revnum()
        text = self.branchprop_list.get_property("", 
            revnum, SVN_PROP_BZR_BRANCHING_SCHEME, None)
        if text is None:
            return None
        return ListBranchingScheme(parse_list_scheme_text(text))

    def set_property_scheme(self, scheme):
        def done(revision, date, author):
            pass
        editor = self.transport.get_commit_editor(
                "Updating branching scheme for Bazaar.",
                done, None, False)
        root = editor.open_root(-1)
        editor.change_dir_prop(root, SVN_PROP_BZR_BRANCHING_SCHEME, 
                "".join(map(lambda x: x+"\n", scheme.branch_list)).encode("utf-8"))
        editor.close_directory(root)
        editor.close()

    def _guess_scheme(self, last_revnum, branch_path=None):
        scheme = guess_scheme_from_history(
            self._log.follow_path("", last_revnum), last_revnum, 
            branch_path)
        mutter("Guessed branching scheme: %r" % scheme)
        return scheme

    def set_branching_scheme(self, scheme, store=True):
        self._scheme = scheme
        if store:
            self.config.set_branching_scheme(str(scheme))

    def _warn_if_deprecated(self):
        # This class isn't deprecated
        pass

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, 
                           self.base)

    def create_cache_dir(self):
        cache_dir = create_cache_dir()
        dir = os.path.join(cache_dir, self.uuid)
        if not os.path.exists(dir):
            os.mkdir(dir)
        return dir

    def _check(self, revision_ids):
        return BranchCheckResult(self)

    def get_inventory(self, revision_id):
        assert revision_id != None
        return self.revision_tree(revision_id).inventory

    def get_fileid_map(self, revnum, path, scheme):
        return self.fileid_map.get_map(self.uuid, revnum, path, 
                                       self.revision_fileid_renames, scheme)

    def transform_fileid_map(self, uuid, revnum, branch, changes, renames, 
                             scheme):
        return self.fileid_map.apply_changes(uuid, revnum, branch, changes, 
                                             renames, scheme)

    def all_revision_ids(self, scheme=None):
        if scheme is None:
            scheme = self.get_scheme()
        for (bp, rev) in self.follow_history(
                self.transport.get_latest_revnum(), scheme):
            yield self.generate_revision_id(rev, bp, str(scheme))

    def get_inventory_weave(self):
        """See Repository.get_inventory_weave()."""
        raise NotImplementedError(self.get_inventory_weave)

    def set_make_working_trees(self, new_value):
        """See Repository.set_make_working_trees()."""
        pass # FIXME: ignored, nowhere to store it... 

    def make_working_trees(self):
        """See Repository.make_working_trees().

        Always returns False, as working trees are never created inside 
        Subversion repositories.
        """
        return False

    def get_ancestry(self, revision_id, topo_sorted=True):
        """See Repository.get_ancestry().
        
        Note: only the first bit is topologically ordered!
        """
        if revision_id is None: 
            return [None]

        (path, revnum, scheme) = self.lookup_revision_id(revision_id)

        ancestry = [revision_id]

        for l in self.branchprop_list.get_property(path, revnum, 
                                    SVN_PROP_BZR_ANCESTRY+str(scheme), "").splitlines():
            ancestry.extend(l.split("\n"))

        if revnum > 0:
            for (branch, rev) in self.follow_branch(path, revnum - 1, scheme):
                ancestry.append(
                    self.generate_revision_id(rev, branch, str(scheme)))

        ancestry.append(None)
        ancestry.reverse()
        return ancestry

    def has_revision(self, revision_id):
        """See Repository.has_revision()."""
        if revision_id is None:
            return True

        try:
            (path, revnum, _) = self.lookup_revision_id(revision_id)
        except NoSuchRevision:
            return False

        try:
            return (svn.core.svn_node_dir == self.transport.check_path(path, revnum))
        except SubversionException, (_, num):
            if num == svn.core.SVN_ERR_FS_NO_SUCH_REVISION:
                return False
            raise


    def revision_trees(self, revids):
        """See Repository.revision_trees()."""
        for revid in revids:
            yield self.revision_tree(revid)

    def revision_tree(self, revision_id):
        """See Repository.revision_tree()."""
        if revision_id is None:
            revision_id = NULL_REVISION

        if revision_id == NULL_REVISION:
            inventory = Inventory(root_id=None)
            inventory.revision_id = revision_id
            return RevisionTree(self, inventory, revision_id)

        return SvnRevisionTree(self, revision_id)

    def revision_fileid_renames(self, revid):
        """Check which files were renamed in a particular revision.
        
        :param revid: Id of revision to look up.
        :return: dictionary with paths as keys, file ids as values
        """
        (path, revnum, _) = self.lookup_revision_id(revid)
        # Only consider bzr:file-ids if this is a bzr revision
        if not self.branchprop_list.touches_property(path, revnum, 
                SVN_PROP_BZR_REVISION_INFO):
            return {}
        fileids = self.branchprop_list.get_property(path, revnum, 
                                                    SVN_PROP_BZR_FILEIDS)
        if fileids is None:
            return {}
        ret = {}
        for line in fileids.splitlines():
            (path, key) = line.split("\t", 2)
            ret[urllib.unquote(path)] = osutils.safe_file_id(key)
        return ret

    def _mainline_revision_parent(self, path, revnum, scheme):
        """Find the mainline parent of the specified revision.

        :param path: Path of the revision in Subversion
        :param revnum: Subversion revision number
        :param scheme: Name of branching scheme to use
        :return: Revision id of the left-hand-side parent or None if 
                  this is the first revision
        """
        assert isinstance(path, basestring)
        assert isinstance(revnum, int)

        if not scheme.is_branch(path) and \
           not scheme.is_tag(path):
            raise NoSuchRevision(self, 
                    self.generate_revision_id(revnum, path, str(scheme)))

        it = self.follow_branch(path, revnum, scheme)
        # the first tuple returned should match the one specified. 
        # if it's not, then the branch, revnum didn't change in the specified 
        # revision and so it is invalid
        if (path, revnum) != it.next():
            raise NoSuchRevision(self, 
                    self.generate_revision_id(revnum, path, str(scheme)))
        try:
            (branch, rev) = it.next()
            return self.generate_revision_id(rev, branch, str(scheme))
        except StopIteration:
            # The specified revision was the first one in the branch
            return None

    def _bzr_merged_revisions(self, branch, revnum, scheme):
        """Find out what revisions were merged by Bazaar in a revision.

        :param branch: Subversion branch path.
        :param revnum: Subversion revision number.
        :param scheme: Branching scheme.
        """
        change = self.branchprop_list.get_property_diff(branch, revnum, 
                                       SVN_PROP_BZR_ANCESTRY+str(scheme)).splitlines()
        if len(change) == 0:
            return []

        assert len(change) == 1

        return parse_merge_property(change[0])

    def _svk_feature_to_revision_id(self, scheme, feature):
        """Convert a SVK feature to a revision id for this repository.

        :param scheme: Branching scheme.
        :param feature: SVK feature.
        :return: revision id.
        """
        try:
            (uuid, bp, revnum) = parse_svk_feature(feature)
        except errors.InvalidPropertyValue:
            return None
        if uuid != self.uuid:
            return None
        if not scheme.is_branch(bp) and not scheme.is_tag(bp):
            return None
        return self.generate_revision_id(revnum, bp, str(scheme))

    def _svk_merged_revisions(self, branch, revnum, scheme):
        """Find out what SVK features were merged in a revision.

        :param branch: Subversion branch path.
        :param revnum: Subversion revision number.
        :param scheme: Branching scheme.
        """
        current = set(self.branchprop_list.get_property(branch, revnum, SVN_PROP_SVK_MERGE, "").splitlines())
        (prev_path, prev_revnum) = self._log.get_previous(branch, revnum)
        if prev_path is None and prev_revnum == -1:
            previous = set()
        else:
            previous = set(self.branchprop_list.get_property(prev_path.encode("utf-8"), 
                         prev_revnum, SVN_PROP_SVK_MERGE, "").splitlines())
        for feature in current.difference(previous):
            revid = self._svk_feature_to_revision_id(scheme, feature)
            if revid is not None:
                yield revid

    def revision_parents(self, revision_id, bzr_merges=None, svk_merges=None):
        """See Repository.revision_parents()."""
        parent_ids = []
        (branch, revnum, scheme) = self.lookup_revision_id(revision_id)
        mainline_parent = self._mainline_revision_parent(branch, revnum, scheme)
        if mainline_parent is not None:
            parent_ids.append(mainline_parent)

        # if the branch didn't change, bzr:merge or svk:merge can't have changed
        if not self._log.touches_path(branch, revnum):
            return parent_ids
       
        if bzr_merges is None:
            bzr_merges = self._bzr_merged_revisions(branch, revnum, scheme)
        if svk_merges is None:
            svk_merges = self._svk_merged_revisions(branch, revnum, scheme)

        parent_ids.extend(bzr_merges)

        if bzr_merges == []:
            # Commit was doing using svk apparently
            parent_ids.extend(svk_merges)

        return parent_ids

    def get_revision(self, revision_id):
        """See Repository.get_revision."""
        if not revision_id or not isinstance(revision_id, basestring):
            raise InvalidRevisionId(revision_id=revision_id, branch=self)

        (path, revnum, _) = self.lookup_revision_id(revision_id)
        
        parent_ids = self.revision_parents(revision_id)

        # Commit SVN revision properties to a Revision object
        rev = Revision(revision_id=revision_id, parent_ids=parent_ids)

        (rev.committer, rev.message, date) = self._log.get_revision_info(revnum)
        if rev.committer is None:
            rev.committer = ""

        if date is not None:
            rev.timestamp = 1.0 * svn.core.secs_from_timestr(date, None)
        else:
            rev.timestamp = 0.0 # FIXME: Obtain repository creation time
        rev.timezone = None
        rev.properties = {}
        parse_revision_metadata(
                self.branchprop_list.get_property(path, revnum, 
                     SVN_PROP_BZR_REVISION_INFO, ""), rev)

        rev.inventory_sha1 = property(lambda: self.get_inventory_sha1(revision_id))

        return rev

    def get_revisions(self, revision_ids):
        """See Repository.get_revisions()."""
        # TODO: More efficient implementation?
        return map(self.get_revision, revision_ids)

    def add_revision(self, rev_id, rev, inv=None, config=None):
        raise NotImplementedError(self.add_revision)

    def generate_revision_id(self, revnum, path, scheme):
        """Generate an unambiguous revision id. 
        
        :param revnum: Subversion revision number.
        :param path: Branch path.
        :param scheme: Branching scheme name

        :return: New revision id.
        """
        assert isinstance(path, str)
        assert isinstance(revnum, int)

        # Look in the cache to see if it already has a revision id
        revid = self.revmap.lookup_branch_revnum(revnum, path, scheme)
        if revid is not None:
            return revid

        # Lookup the revision from the bzr:revision-id-vX property
        line = self.branchprop_list.get_property_diff(path, revnum, 
                SVN_PROP_BZR_REVISION_ID+str(scheme)).strip("\n")
        # Or generate it
        if line == "":
            revid = generate_svn_revision_id(self.uuid, revnum, path, 
                                             scheme)
        else:
            try:
                (bzr_revno, revid) = parse_revid_property(line)
                self.revmap.insert_revid(revid, path, revnum, revnum, 
                        scheme, bzr_revno)
            except errors.InvalidPropertyValue, e:
                mutter(str(e))
                revid = generate_svn_revision_id(self.uuid, revnum, path, 
                                                 scheme)
                self.revmap.insert_revid(revid, path, revnum, revnum, 
                        scheme)

        return revid

    def lookup_revision_id(self, revid, scheme=None):
        """Parse an existing Subversion-based revision id.

        :param revid: The revision id.
        :param scheme: Optional branching scheme to use when searching for 
                       revisions
        :raises: NoSuchRevision
        :return: Tuple with branch path, revision number and scheme.
        """
        def get_scheme(name):
            assert isinstance(name, basestring)
            return BranchingScheme.find_scheme(name)

        # Try a simple parse
        try:
            (uuid, branch_path, revnum, schemen) = parse_svn_revision_id(revid)
            assert isinstance(branch_path, str)
            if uuid == self.uuid:
                return (branch_path, revnum, get_scheme(schemen))
            # If the UUID doesn't match, this may still be a valid revision
            # id; a revision from another SVN repository may be pushed into 
            # this one.
        except InvalidRevisionId:
            pass

        # Check the record out of the revmap, if it exists
        try:
            (branch_path, min_revnum, max_revnum, \
                    scheme) = self.revmap.lookup_revid(revid)
            assert isinstance(branch_path, str)
            # Entry already complete?
            if min_revnum == max_revnum:
                return (branch_path, min_revnum, get_scheme(scheme))
        except NoSuchRevision, e:
            # If there is no entry in the map, walk over all branches:
            if scheme is None:
                scheme = self.get_scheme()
            last_revnum = self.transport.get_latest_revnum()
            if (self._revids_seen.has_key(str(scheme)) and 
                last_revnum <= self._revids_seen[str(scheme)]):
                # All revision ids in this repository for the current 
                # scheme have already been discovered. No need to 
                # check again.
                raise e
            found = False
            for (branch, revno, _) in self.find_branches(scheme, last_revnum):
                # Look at their bzr:revision-id-vX
                revids = []
                for line in self.branchprop_list.get_property(branch, revno, 
                        SVN_PROP_BZR_REVISION_ID+str(scheme), "").splitlines():
                    try:
                        revids.append(parse_revid_property(line))
                    except errors.InvalidPropertyValue, ie:
                        mutter(str(ie))

                # If there are any new entries that are not yet in the cache, 
                # add them
                for (entry_revno, entry_revid) in revids:
                    if entry_revid == revid:
                        found = True
                    self.revmap.insert_revid(entry_revid, branch, 0, revno, 
                            str(scheme), entry_revno)

                if found:
                    break
                
            if not found:
                # We've added all the revision ids for this scheme in the repository,
                # so no need to check again unless new revisions got added
                self._revids_seen[str(scheme)] = last_revnum
                raise e
            (branch_path, min_revnum, max_revnum, scheme) = self.revmap.lookup_revid(revid)
            assert isinstance(branch_path, str)

        # Find the branch property between min_revnum and max_revnum that 
        # added revid
        for (bp, rev) in self.follow_branch(branch_path, max_revnum, 
                                            get_scheme(scheme)):
            try:
                (entry_revno, entry_revid) = parse_revid_property(
                 self.branchprop_list.get_property_diff(bp, rev, 
                     SVN_PROP_BZR_REVISION_ID+str(scheme)).strip("\n"))
            except errors.InvalidPropertyValue:
                # Don't warn about encountering an invalid property, 
                # that will already have happened earlier
                continue
            if entry_revid == revid:
                self.revmap.insert_revid(revid, bp, rev, rev, scheme, 
                                         entry_revno)
                return (bp, rev, get_scheme(scheme))

        raise AssertionError("Revision id %s was added incorrectly" % revid)

    def get_inventory_xml(self, revision_id):
        """See Repository.get_inventory_xml()."""
        return bzrlib.xml5.serializer_v5.write_inventory_to_string(
            self.get_inventory(revision_id))

    def get_inventory_sha1(self, revision_id):
        """Get the sha1 for the XML representation of an inventory.

        :param revision_id: Revision id of the inventory for which to return 
         the SHA1.
        :return: XML string
        """

        return osutils.sha_string(self.get_inventory_xml(revision_id))

    def get_revision_xml(self, revision_id):
        """Return the XML representation of a revision.

        :param revision_id: Revision for which to return the XML.
        :return: XML string
        """
        return bzrlib.xml5.serializer_v5.write_revision_to_string(
            self.get_revision(revision_id))

    def follow_history(self, revnum, scheme):
        """Yield all the branches found between the start of history 
        and a specified revision number.

        :param revnum: Revision number up to which to search.
        :return: iterator over branches in the range 0..revnum
        """
        assert scheme is not None

        while revnum >= 0:
            yielded_paths = []
            paths = self._log.get_revision_paths(revnum)
            for p in paths:
                try:
                    bp = scheme.unprefix(p)[0]
                    if not bp in yielded_paths:
                        if not paths.has_key(bp) or paths[bp][0] != 'D':
                            assert revnum > 0 or bp == ""
                            yield (bp, revnum)
                        yielded_paths.append(bp)
                except NotBranchError:
                    pass
            revnum -= 1

    def follow_branch(self, branch_path, revnum, scheme):
        """Follow the history of a branch. Will yield all the 
        left-hand side ancestors of a specified revision.
    
        :param branch_path: Subversion path to search.
        :param revnum: Revision number in Subversion to start.
        :param scheme: Name of the branching scheme to use
        :return: iterator over the ancestors
        """
        assert branch_path is not None
        assert isinstance(branch_path, str)
        assert isinstance(revnum, int) and revnum >= 0
        assert scheme.is_branch(branch_path) or scheme.is_tag(branch_path)
        branch_path = branch_path.strip("/")

        while revnum >= 0:
            paths = self._log.get_revision_paths(revnum)

            yielded = False
            # If something underneath branch_path changed, there is a 
            # revision there, so yield it.
            for p in paths:
                assert isinstance(p, str)
                if p == branch_path or p.startswith(branch_path+"/") or branch_path == "":
                    yield (branch_path, revnum)
                    yielded = True
                    break
            
            # If there are no special cases, just go try the 
            # next revnum in history
            revnum -= 1

            # Make sure we get the right location for next time, if 
            # the branch itself was copied
            if (paths.has_key(branch_path) and 
                paths[branch_path][0] in ('R', 'A')):
                if not yielded:
                    yield (branch_path, revnum+1)
                if paths[branch_path][1] is None:
                    return
                if not scheme.is_branch(paths[branch_path][1]) and \
                   not scheme.is_tag(paths[branch_path][1]):
                    # FIXME: if copyfrom_path is not a branch path, 
                    # should simulate a reverse "split" of a branch
                    # for now, just make it look like the branch ended here
                    return
                revnum = paths[branch_path][2]
                branch_path = paths[branch_path][1].encode("utf-8")
                continue
            
            # Make sure we get the right location for the next time if 
            # one of the parents changed

            # Path names need to be sorted so the longer paths 
            # override the shorter ones
            for p in sorted(paths.keys()):
                if branch_path.startswith(p+"/"):
                    assert paths[p][1] is not None and paths[p][0] in ('A', 'R'), "Parent didn't exist yet, but child wasn't added !?"

                    revnum = paths[p][2]
                    branch_path = paths[p][1].encode("utf-8") + branch_path[len(p):]

    def follow_branch_history(self, branch_path, revnum, scheme):
        """Return all the changes that happened in a branch 
        between branch_path and revnum. 

        :return: iterator that returns tuples with branch path, 
            changed paths and revision number.
        """
        assert branch_path is not None
        assert scheme.is_branch(branch_path) or scheme.is_tag(branch_path)

        for (bp, paths, revnum) in self._log.follow_path(branch_path, revnum):
            if (paths.has_key(bp) and 
                paths[bp][1] is not None and 
                not scheme.is_branch(paths[bp][1]) and
                not scheme.is_tag(paths[bp][1])):
                # FIXME: if copyfrom_path is not a branch path, 
                # should simulate a reverse "split" of a branch
                # for now, just make it look like the branch ended here
                for c in self._log.find_children(paths[bp][1], paths[bp][2]):
                    path = c.replace(paths[bp][1], bp+"/", 1).replace("//", "/")
                    paths[path] = ('A', None, -1)
                paths[bp] = ('A', None, -1)

                yield (bp, paths, revnum)
                return
                     
            yield (bp, paths, revnum)

    def has_signature_for_revision_id(self, revision_id):
        """Check whether a signature exists for a particular revision id.

        :param revision_id: Revision id for which the signatures should be looked up.
        :return: False, as no signatures are stored for revisions in Subversion 
            at the moment.
        """
        # TODO: Retrieve from SVN_PROP_BZR_SIGNATURE 
        return False # SVN doesn't store GPG signatures. Perhaps 
                     # store in SVN revision property?


    def get_signature_text(self, revision_id):
        """Return the signature text for a particular revision.

        :param revision_id: Id of the revision for which to return the 
                            signature.
        :raises NoSuchRevision: Always
        """
        # TODO: Retrieve from SVN_PROP_BZR_SIGNATURE 
        # SVN doesn't store GPG signatures
        raise NoSuchRevision(self, revision_id)

    def _full_revision_graph(self, scheme, _latest_revnum=None):
        if _latest_revnum is None:
            _latest_revnum = self.transport.get_latest_revnum()
        graph = {}
        for (branch, revnum) in self.follow_history(_latest_revnum, 
                                                    scheme):
            mutter('%r, %r' % (branch, revnum))
            revid = self.generate_revision_id(revnum, branch, str(scheme))
            graph[revid] = self.revision_parents(revid)
        return graph

    def get_revision_graph(self, revision_id=None):
        """See Repository.get_revision_graph()."""
        if revision_id == NULL_REVISION:
            return {}

        if revision_id is None:
            return self._full_revision_graph(self.get_scheme())

        (path, revnum, scheme) = self.lookup_revision_id(revision_id)

        _previous = revision_id
        self._ancestry = {}
        
        if revnum > 0:
            for (branch, rev) in self.follow_branch(path, revnum - 1, scheme):
                revid = self.generate_revision_id(rev, branch, str(scheme))
                self._ancestry[_previous] = [revid]
                _previous = revid

        self._ancestry[_previous] = []

        return self._ancestry

    def find_branches(self, scheme, revnum=None):
        """Find all branches that were changed in the specified revision number.

        :param revnum: Revision to search for branches.
        :return: iterator that returns tuples with (path, revision number, still exists). The revision number is the revision in which the branch last existed.
        """
        assert scheme is not None
        if revnum is None:
            revnum = self.transport.get_latest_revnum()

        created_branches = {}

        ret = []

        pb = ui.ui_factory.nested_progress_bar()
        try:
            for i in range(revnum+1):
                pb.update("finding branches", i, revnum+1)
                paths = self._log.get_revision_paths(i)
                for p in sorted(paths.keys()):
                    if scheme.is_branch(p) or scheme.is_tag(p):
                        if paths[p][0] in ('R', 'D'):
                            del created_branches[p]
                            j = self._log.find_latest_change(p, i-1, 
                                recurse=True)
                            ret.append((p, j, False))

                        if paths[p][0] in ('A', 'R'): 
                            created_branches[p] = i
                    elif scheme.is_branch_parent(p) or \
                            scheme.is_tag_parent(p):
                        if paths[p][0] in ('R', 'D'):
                            k = created_branches.keys()
                            for c in k:
                                if c.startswith(p+"/"):
                                    del created_branches[c] 
                                    j = self._log.find_latest_change(c, i-1, 
                                            recurse=True)
                                    ret.append((c, j, False))
                        if paths[p][0] in ('A', 'R'):
                            parents = [p]
                            while parents:
                                p = parents.pop()
                                for c in self.transport.get_dir(p, i)[0].keys():
                                    n = p+"/"+c
                                    if scheme.is_branch(n) or scheme.is_tag(n):
                                        created_branches[n] = i
                                    elif (scheme.is_branch_parent(n) or 
                                          scheme.is_tag_parent(n)):
                                        parents.append(n)
        finally:
            pb.finished()

        for p in created_branches:
            j = self._log.find_latest_change(p, revnum, recurse=True)
            if j is None:
                j = created_branches[p]
            ret.append((p, j, True))

        return ret

    def is_shared(self):
        """Return True if this repository is flagged as a shared repository."""
        return True

    def get_physical_lock_status(self):
        return False

    def get_commit_builder(self, branch, parents, config, timestamp=None, 
                           timezone=None, committer=None, revprops=None, 
                           revision_id=None):
        from commit import SvnCommitBuilder
        return SvnCommitBuilder(self, branch, parents, config, timestamp, 
                timezone, committer, revprops, revision_id)



