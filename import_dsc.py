#    import_dsc.py -- Import a series of .dsc files.
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
#              (C) 2008 Canonical Ltd.
#
#    Code is also taken from bzrtools, which is
#             (C) 2005, 2006, 2007 Aaron Bentley <aaron.bentley@utoronto.ca>
#             (C) 2005, 2006 Canonical Limited.
#             (C) 2006 Michael Ellerman.
#    and distributed under the GPL, version 2 or later.
#    
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

from base64 import (
    standard_b64encode,
    )

import os
import re
import shutil
import stat
import subprocess
import tempfile

try:
    from debian import deb822
    from debian.changelog import Version, Changelog, VersionError
except ImportError:
    # Prior to 0.1.15 the debian module was called debian_bundle
    from debian_bundle import deb822
    from debian_bundle.changelog import Version, Changelog, VersionError

from bzrlib import (
                    bzrdir,
                    osutils,
                    )
from bzrlib.config import ConfigObj
from bzrlib.errors import (
        AlreadyBranchError,
        BzrCommandError,
        NotBranchError,
        NoSuchRevision,
        NoWorkingTree,
        UnrelatedBranches,
        )
from bzrlib.revision import NULL_REVISION
from bzrlib.trace import warning, mutter
from bzrlib.transport import (
    get_transport,
    )

from bzrlib.plugins.builddeb.bzrtools_import import import_dir
from bzrlib.plugins.builddeb.errors import (
    TarFailed,
    UpstreamAlreadyImported,
    UpstreamBranchAlreadyMerged,
    )
from bzrlib.plugins.builddeb.util import (
    FORMAT_3_0_QUILT,
    FORMAT_3_0_NATIVE,
    export,
    get_commit_info_from_changelog,
    make_pristine_tar_delta,
    md5sum_filename,
    open_file_via_transport,
    open_transport,
    safe_decode,
    subprocess_setup,
    )
from bzrlib.plugins.builddeb.upstream import (
    PristineTarSource,
    )
from bzrlib.plugins.builddeb.upstream.branch import (
    UpstreamBranchSource,
    )


class DscCache(object):

    def __init__(self, transport=None):
        self.cache = {}
        self.transport_cache = {}
        self.transport = transport

    def get_dsc(self, name):

        if name in self.cache:
            dsc1 = self.cache[name]
        else:
            # Obtain the dsc file, following any redirects as needed.
            filename, transport = open_transport(name)
            f1 = open_file_via_transport(filename, transport)
            try:
                dsc1 = deb822.Dsc(f1)
            finally:
                f1.close()
            self.cache[name] = dsc1
            self.transport_cache[name] = transport

        return dsc1

    def get_transport(self, name):
        return self.transport_cache[name]

class DscComp(object):

    def __init__(self, cache):
        self.cache = cache

    def cmp(self, dscname1, dscname2):
        dsc1 = self.cache.get_dsc(dscname1)
        dsc2 = self.cache.get_dsc(dscname2)
        v1 = Version(dsc1['Version'])
        v2 = Version(dsc2['Version'])
        if v1 == v2:
            return 0
        if v1 > v2:
            return 1
        return -1



class DistributionBranchSet(object):
    """A collection of DistributionBranches with an ordering.

    A DistributionBranchSet collects a group of DistributionBranches
    and an order, and then can provide the branches with information
    about their place in the relationship with other branches.
    """

    def __init__(self):
        """Create a DistributionBranchSet."""
        self._branch_list = []

    def add_branch(self, branch):
        """Adds a DistributionBranch to the end of the list.

        Appends the passed distribution branch to the end of the list
        that this DistributionBranchSet represents. It also provides
        the distribution branch with a way to get the branches that
        are before and after it in the list.

        It will call branch.set_get_lesser_branches_callback() and
        branch.set_get_greater_branches_callback(), passing it methods
        that the DistributionBranch can call to get the list of branches
        before it in the list and after it in the list respectively.
        The passed methods take no arguments and return a list (possibly
        empty) of the desired branches.

        :param branch: the DistributionBranch to add.
        """
        self._branch_list.append(branch)
        lesser_callback = self._make_lesser_callback(branch)
        branch.set_get_lesser_branches_callback(lesser_callback)
        greater_callback = self._make_greater_callback(branch)
        branch.set_get_greater_branches_callback(greater_callback)

    def _make_lesser_callback(self, branch):
        return lambda: self.get_lesser_branches(branch)

    def _make_greater_callback(self, branch):
        return lambda: self.get_greater_branches(branch)

    def get_lesser_branches(self, branch):
        """Return the list of branches less than the argument.

        :param branch: The branch that all branches returned must be less
            than.
        :return: a (possibly empty) list of all the branches that are
            less than the argument. The list is sorted starting with the
            least element.
        """
        index = self._branch_list.index(branch)
        return self._branch_list[:index]

    def get_greater_branches(self, branch):
        """Return the list of branches greater than the argument.

        :param branch: The branch that all branches returned must be greater
            than.
        :return: a (possibly empty) list of all the branches that are
            greater than the argument. The list is sorted starting with the
            least element.
        """
        index = self._branch_list.index(branch)
        return self._branch_list[index+1:]


class DistributionBranch(object):
    """A DistributionBranch is a representation of one line of development.

    It is a branch that is linked to a line of development, such as Debian
    unstable. It also has associated branches, some of which are "lesser"
    and some are "greater". A lesser branch is one that this branch
    derives from. A greater branch is one that derives from this. For
    instance Debian experimental would have unstable as a lesser branch,
    and vice-versa. It is assumed that a group of DistributionBranches will
    have a total ordering with respect to these relationships.
    """

    def __init__(self, branch, upstream_branch, tree=None,
            upstream_tree=None):
        """Create a distribution branch.

        You can only import packages on to the DistributionBranch
        if both tree and upstream_tree are provided.

        :param branch: the Branch for the packaging part.
        :param upstream_branch: the Branch for the upstream part, if any.
        :param tree: an optional tree for the branch.
        :param upstream_tree: an optional upstream_tree for the
            upstream_branch.
        """
        self.branch = branch
        self.tree = tree
        self.pristine_tar_source = PristineTarSource(branch=branch, tree=tree)
        self.upstream_branch = upstream_branch
        self.upstream_tree = upstream_tree
        if upstream_branch is not None:
            self.upstream_source = UpstreamBranchSource(self.upstream_branch)
        else:
            self.upstream_source = None
        self.get_lesser_branches = None
        self.get_greater_branches = None

    def set_get_lesser_branches_callback(self, callback):
        """Set the callback to get the branches "lesser" than this.

        The function passed to this method will be used to get the
        list of branches that are "lesser" than this one. It is
        expected to require no arguments, and to return the desired
        (possibly empty) list of branches. The returned list should
        be sorted starting with the least element.

        :param callback: a function that is called to get the desired list
            of branches.
        """
        self.get_lesser_branches = callback

    def set_get_greater_branches_callback(self, callback):
        """Set the callback to get the branches "greater" than this.

        The function passed to this method will be used to get the
        list of branches that are "greater" than this one. It is
        expected to require no arguments, and to return the desired
        (possibly empty) list of branches. The returned list should
        be sorted starting with the least element.

        :param callback: a function that is called to get the desired list
            of branches.
        """
        self.get_greater_branches = callback

    def get_other_branches(self):
        """Return all the other branches in this set.

        The returned list will be ordered, and will not contain this
        branch.

        :return: a list of all the other branches in this set (if any).
        """
        return self.get_lesser_branches() + self.get_greater_branches()

    def tag_name(self, version):
        """Gets the name of the tag that is used for the version.

        :param version: the Version object that the tag should refer to.
        :return: a String with the name of the tag.
        """
        return str(version)

    def _has_version(self, branch, tag_name, md5=None):
        if branch.tags.has_tag(tag_name):
            revid = branch.tags.lookup_tag(tag_name)
            branch.lock_read()
            try:
                graph = branch.repository.get_graph()
                if not graph.is_ancestor(revid, branch.last_revision()):
                    return False
            finally:
                branch.unlock()
            if md5 is None:
                return True
            rev = branch.repository.get_revision(revid)
            try:
                return rev.properties['deb-md5'] == md5
            except KeyError:
                warning("tag %s present in branch, but there is no "
                    "associated 'deb-md5' property" % tag_name)
                pass
        return False

    def has_version(self, version, md5=None):
        """Whether this branch contains the package version specified.

        The version must be judged present by having the appropriate tag
        in the branch. If the md5 argument is not None then the string
        passed must the the md5sum that is associated with the revision
        pointed to by the tag.

        :param version: a Version object to look for in this branch.
        :param md5: a string with the md5sum that if not None must be
            associated with the revision.
        :return: True if this branch contains the specified version of the
            package. False otherwise.
        """
        tag_name = self.tag_name(version)
        if self._has_version(self.branch, tag_name, md5=md5):
            return True
        debian_tag_name = "debian-" + tag_name
        if self._has_version(self.branch, debian_tag_name, md5=md5):
            return True
        ubuntu_tag_name = "ubuntu-" + tag_name
        if self._has_version(self.branch, ubuntu_tag_name, md5=md5):
            return True
        return False

    def has_upstream_version(self, version, md5=None):
        """Whether this branch contains the upstream version specified.

        The version must be judged present by having the appropriate tag
        in the upstream branch. If the md5 argument is not None then the
        string passed must the the md5sum that is associated with the
        revision pointed to by the tag.

        :param version: a upstream version number to look for in the upstream 
            branch.
        :param md5: a string with the md5sum that if not None must be
            associated with the revision.
        :return: True if the upstream branch contains the specified upstream
            version of the package. False otherwise.
        """
        for tag_name in self.pristine_tar_source.possible_tag_names(version):
            if self._has_version(self.upstream_branch, tag_name, md5=md5):
                return True
        return False

    def contained_versions(self, versions):
        """Splits a list of versions depending on presence in the branch.

        Partitions the input list of versions depending on whether they
        are present in the branch or not.

        The two output lists will be sorted in the same order as the input
        list.

        :param versions: a list of Version objects to look for in the
            branch. May be an empty list.
        :return: A tuple of two lists. The first list is the list of those
            items from the input list that are present in the branch. The
            second list is the list of those items from the input list that
            are not present in the branch. The two lists will be disjoint
            and cover the input list. Either list may be empty, or both if
            the input list is empty.
        """
        #FIXME: should probably do an ancestory check to find all
        # merged revisions. This will avoid adding an extra parent
        # when say
        # experimental 1-1~rc1
        # unstable 1-1 1-1~rc1
        # Ubuntu 1-1ubuntu1 1-1 1-1~rc1
        # where only the first in each list is actually uploaded.
        contained = []
        not_contained = []
        for version in versions:
            if self.has_version(version):
                contained.append(version)
            else:
                not_contained.append(version)
        return contained, not_contained

    def missing_versions(self, versions):
        """Returns the versions from the list that the branch does not have.

        Looks at all the versions specified and returns a list of the ones
        that are earlier in the list that the last version that is
        contained in this branch.

        :param versions: a list of Version objects to look for in the branch.
            May be an empty list.
        :return: The subset of versions from the list that are not present
            in this branch. May be an empty list.
        """
        last_contained = self.last_contained_version(versions)
        if last_contained is None:
            return versions
        index = versions.index(last_contained)
        return versions[:index]

    def last_contained_version(self, versions):
        """Returns the highest version from the list present in this branch.

        It assumes that the input list of versions is sorted with the
        highest version first.

        :param versions: a list of Version objects to look for in the branch.
            Must be sorted with the highest version first. May be an empty
            list.
        :return: the highest version that is contained in this branch, or
            None if none of the versions are contained within the branch.
        """
        for version in versions:
            if self.has_version(version):
                return version
        return None

    def revid_of_version(self, version):
        """Returns the revision id corresponding to that version.

        :param version: the Version object that you wish to retrieve the
            revision id of. The Version must be present in the branch.
        :return: the revision id corresponding to that version
        """
        tag_name = self.tag_name(version)
        if self._has_version(self.branch, tag_name):
            return self.branch.tags.lookup_tag(tag_name)
        debian_tag_name = "debian-" + tag_name
        if self._has_version(self.branch, debian_tag_name):
            return self.branch.tags.lookup_tag(debian_tag_name)
        ubuntu_tag_name = "ubuntu-" + tag_name
        if self._has_version(self.branch, ubuntu_tag_name):
            return self.branch.tags.lookup_tag(ubuntu_tag_name)
        return self.branch.tags.lookup_tag(tag_name)

    def revid_of_upstream_version(self, version):
        """Returns the revision id corresponding to the upstream version.

        :param version: the Version object to extract the upstream version
            from to retreive the revid of. The upstream version must be
            present in the upstream branch.
        :return: the revision id corresponding to the upstream portion
            of the version
        """
        for tag_name in self.pristine_tar_source.possible_tag_names(version):
            if self._has_version(self.upstream_branch, tag_name):
                return self.upstream_branch.tags.lookup_tag(tag_name)
        tag_name = self.pristine_tar_source.tag_name(version)
        return self.upstream_branch.tags.lookup_tag(tag_name)

    def tag_version(self, version, revid=None):
        """Tags the branch's last revision with the given version.

        Sets a tag on the last revision of the branch with a tag that refers
        to the version provided.

        :param version: the Version object to derive the tag name from.
        :param revid: the revid to associate the tag with, or None for the
            tip of self.branch.
        :return: Name of the tag set
        """
        tag_name = self.tag_name(version)
        if revid is None:
            revid = self.branch.last_revision()
        self.branch.tags.set_tag(tag_name, revid)
        return tag_name

    def tag_upstream_version(self, version, revid=None):
        """Tags the upstream branch's last revision with an upstream version.

        Sets a tag on the last revision of the upstream branch and on the main
        branch with a tag that refers to the upstream part of the version
        provided.

        :param version: the upstream part of the version number to derive the 
            tag name from.
        :param revid: the revid to associate the tag with, or None for the
            tip of self.upstream_branch.
        :return The tag name, revid of the added tag.
        """
        assert isinstance(version, str)
        tag_name = self.pristine_tar_source.tag_name(version)
        if revid is None:
            revid = self.upstream_branch.last_revision()
        self.upstream_branch.tags.set_tag(tag_name, revid)
        try:
            self.branch.repository.fetch(self.upstream_branch.repository,
                revision_id=revid)
        except NoSuchRevision:
            # See bug lp:574223
            pass
        self.branch.tags.set_tag(tag_name, revid)
        return tag_name, revid

    def _default_config_for_tree(self, tree):
        # FIXME: shouldn't go to configobj directly
        path = '.bzr-builddeb/default.conf'
        c_fileid = tree.path2id(path)
        config = None
        if c_fileid is not None:
            tree.lock_read()
            try:
                config = ConfigObj(tree.get_file(c_fileid, path))
                try:
                    config['BUILDDEB']
                except KeyError:
                    config['BUILDDEB'] = {}
            finally:
                tree.unlock()
        return config

    def _is_tree_native(self, tree):
        config = self._default_config_for_tree(tree)
        if config is not None:
            try:
                current_value = config['BUILDDEB']['native']
            except KeyError:
                current_value = False
            return current_value == "True"
        return False

    def is_version_native(self, version):
        """Determines whether the given version is native.

        :param version: the Version object to test. Must be present in
            the branch.
        :return: True if the version is was recorded as native when
            imported, False otherwise.
        """
        revid = self.revid_of_version(version)
        rev_tree = self.branch.repository.revision_tree(revid)
        if self._is_tree_native(rev_tree):
            return True
        rev = self.branch.repository.get_revision(revid)
        try:
            prop = rev.properties["deb-native"]
            return prop == "True"
        except KeyError:
            return False

    def branch_to_pull_version_from(self, version, md5):
        """Checks whether this upload is a pull from a lesser branch.

        Looks in all the lesser branches for the given version/md5 pair
        in a branch that has not diverged from this.

        If it is present in another branch that has not diverged this
        method will return the greatest branch that it is present in,
        otherwise it will return None. If it returns a branch then it
        indicates that a pull should be done from that branch, rather
        than importing the version as a new revision in this branch.

        :param version: the Version object to look for in the lesser
            branches.
        :param md5: a String containing the md5 associateed with the
            version.
        :return: a DistributionBranch object to pull from if that is
            what should be done, otherwise None.
        """
        assert md5 is not None, \
            ("It's not a good idea to use branch_to_pull_version_from with "
             "md5 == None, as you may pull the wrong revision.")
        self.branch.lock_read()
        try:
            for branch in reversed(self.get_lesser_branches()):
                if branch.has_version(version, md5=md5):
                    # Check that they haven't diverged
                    branch.branch.lock_read()
                    try:
                        graph = branch.branch.repository.get_graph(
                                self.branch.repository)
                        if graph.is_ancestor(self.branch.last_revision(),
                                branch.revid_of_version(version)):
                            return branch
                    finally:
                        branch.branch.unlock()
            for branch in self.get_greater_branches():
                if branch.has_version(version, md5=md5):
                    # Check that they haven't diverged
                    branch.branch.lock_read()
                    try:
                        graph = branch.branch.repository.get_graph(
                                self.branch.repository)
                        if graph.is_ancestor(self.branch.last_revision(),
                                branch.revid_of_version(version)):
                            return branch
                    finally:
                        branch.branch.unlock()
            return None
        finally:
            self.branch.unlock()

    def branch_to_pull_upstream_from(self, version, md5):
        """Checks whether this upstream is a pull from a lesser branch.

        Looks in all the other upstream branches for the given
        version/md5 pair in a branch that has not diverged from this.
        If it is present in a lower branch this method will return the
        greatest branch that it is present in that has not diverged,
        otherwise it will return None. If it returns a branch then it
        indicates that a pull should be done from that branch, rather
        than importing the upstream as a new revision in this branch.

        :param version: the upstream version to use when searching in the 
            lesser branches.
        :param md5: a String containing the md5 associateed with the
            upstream version.
        :return: a DistributionBranch object to pull the upstream from
            if that is what should be done, otherwise None.
        """
        assert isinstance(version, str)
        assert md5 is not None, \
            ("It's not a good idea to use branch_to_pull_upstream_from with "
             "md5 == None, as you may pull the wrong revision.")
        up_branch = self.upstream_branch
        up_branch.lock_read()
        try:
            for branch in reversed(self.get_lesser_branches()):
                if branch.has_upstream_version(version, md5=md5):
                    # Check that they haven't diverged
                    other_up_branch = branch.upstream_branch
                    other_up_branch.lock_read()
                    try:
                        graph = other_up_branch.repository.get_graph(
                                up_branch.repository)
                        if graph.is_ancestor(up_branch.last_revision(),
                                branch.revid_of_upstream_version(version)):
                            return branch
                    finally:
                        other_up_branch.unlock()
            for branch in self.get_greater_branches():
                if branch.has_upstream_version(version, md5=md5):
                    # Check that they haven't diverged
                    other_up_branch = branch.upstream_branch
                    other_up_branch.lock_read()
                    try:
                        graph = other_up_branch.repository.get_graph(
                                up_branch.repository)
                        if graph.is_ancestor(up_branch.last_revision(),
                                branch.revid_of_upstream_version(version)):
                            return branch
                    finally:
                        other_up_branch.unlock()
            return None
        finally:
            up_branch.unlock()

    def get_parents(self, versions):
        """Return the list of parents for a specific version.

        This method returns the list of revision ids that should be parents
        for importing a specific package version. The specific package version
        is the first element of the list of versions passed.

        The parents are determined by looking at the other versions in the
        passed list and examining which of the branches (if any) they are
        already present in.

        You should probably use get_parents_with_upstream rather than
        this method.

        :param versions: a list of Version objects, the first item of
            which is the version of the package that is currently being
            imported.
        :return: a list of tuples of (DistributionBranch, version,
            revision id). The revision ids should all be parents of the
            revision that imports the specified version of the package.
            The versions are the versions that correspond to that revision
            id. The DistributionBranch is the branch that contains that
            version.
        """
        assert len(versions) > 0, "Need a version to import"
        mutter("Getting parents of %s" % str(versions))
        missing_versions = self.missing_versions(versions)
        mutter("Versions we don't have are %s" % str(missing_versions))
        last_contained_version = self.last_contained_version(versions)
        parents = []
        if last_contained_version is not None:
            assert last_contained_version != versions[0], \
                "Reupload of a version?"
            mutter("The last versions we do have is %s" \
                    % str(last_contained_version))
            parents = [(self, last_contained_version,
                    self.revid_of_version(last_contained_version))]
        else:
            mutter("We don't have any of those versions")
        for branch in reversed(self.get_lesser_branches()):
            merged, missing_versions = \
                branch.contained_versions(missing_versions)
            if merged:
                revid = branch.revid_of_version(merged[0])
                parents.append((branch, merged[0], revid))
                mutter("Adding merge from lesser of %s for version %s"
                        % (revid, str(merged[0])))
                #FIXME: should this really be here?
                branch.branch.tags.merge_to(self.branch.tags)
                self.branch.fetch(branch.branch,
                        last_revision=revid)
        for branch in self.get_greater_branches():
            merged, missing_versions = \
                branch.contained_versions(missing_versions)
            if merged:
                revid = branch.revid_of_version(merged[0])
                parents.append((branch, merged[0], revid))
                mutter("Adding merge from greater of %s for version %s"
                    % (revid, str(merged[0])))
                #FIXME: should this really be here?
                branch.branch.tags.merge_to(self.branch.tags)
                self.branch.fetch(branch.branch,
                        last_revision=revid)
        return parents

    def pull_upstream_from_branch(self, pull_branch, version):
        """Pulls an upstream version from a branch.

        Given a DistributionBranch and a version number this method
        will pull the upstream part of the given version from the
        branch in to this. The upstream version must be present
        in the DistributionBranch, and it is assumed that the md5
        matches.

        It sets the necessary tags so that the pulled version is
        recognised as being part of this branch.

        :param pull_branch: the DistributionBranch to pull from.
        :param version: the upstream version string
        """
        assert isinstance(version, str)
        pull_revision = pull_branch.revid_of_upstream_version(version)
        mutter("Pulling upstream part of %s from revision %s" % \
                (version, pull_revision))
        up_pull_branch = pull_branch.upstream_branch
        assert self.upstream_tree is not None, \
            "Can't pull upstream with no tree"
        self.upstream_tree.pull(up_pull_branch,
                stop_revision=pull_revision)
        self.tag_upstream_version(version, revid=pull_revision)
        self.branch.fetch(self.upstream_branch, last_revision=pull_revision)
        self.upstream_branch.tags.merge_to(self.branch.tags)

    def pull_version_from_branch(self, pull_branch, version, native=False):
        """Pull a version from a particular branch.

        Given a DistributionBranch and a version number this method
        will pull the given version from the branch in to this. The
        version must be present in the DistributionBranch, and it
        is assumed that the md5 matches.

        It will also pull in any upstream part that is needed to
        the upstream branch. It is assumed that the md5 matches
        here as well. If the upstream version must be present in
        at least one of the upstream branches.

        It sets the necessary tags on the revisions so they are
        recongnised in this branch as well.

        :param pull_branch: the DistributionBranch to pull from.
        :param version: the Version to pull.
        :param native: whether it is a native version that is being
            imported.
        """
        pull_revision = pull_branch.revid_of_version(version)
        mutter("already has version %s so pulling from revision %s"
                % (str(version), pull_revision))
        assert self.tree is not None, "Can't pull branch with no tree"
        self.tree.pull(pull_branch.branch, stop_revision=pull_revision)
        self.tag_version(version, revid=pull_revision)
        if not native and not self.has_upstream_version(version.upstream_version):
            if pull_branch.has_upstream_version(version.upstream_version):
                self.pull_upstream_from_branch(pull_branch, 
                    version.upstream_version)
            else:
                assert False, ("Can't find the needed upstream part "
                        "for version %s" % version)
        if (native and self.upstream_branch.last_revision() == NULL_REVISION
            and pull_branch.upstream_branch.last_revision() != NULL_REVISION):
            # in case the package wasn't native before then we pull
            # the upstream. These checks may be a bit restrictive.
            self.upstream_tree.pull(pull_branch.upstream_branch)
            pull_branch.upstream_branch.tags.merge_to(self.upstream_branch.tags)
        elif native:
            mutter("Not checking for upstream as it is a native package")
        else:
            mutter("Not importing the upstream part as it is already "
                    "present in the upstream branch")

    def get_parents_with_upstream(self, version, versions,
            force_upstream_parent=False):
        """Get the list of parents including any upstream parents.

        Further to get_parents this method includes any upstream parents
        that are needed. An upstream parent is needed if none of
        the other parents include the upstream version. The needed
        upstream must already present in the upstream branch before
        calling this method.

        If force_upstream_parent is True then the upstream parent will
        be included, even if another parent is already using that
        upstream. This is for use in cases where the .orig.tar.gz
        is different in two ditributions.

        :param version: the Version that we are currently importing.
        :param versions: the list of Versions that are ancestors of
            version, including version itself. Sorted with the latest
            versions first, so version must be the first entry.
        :param force_upstream_parent: if True then an upstream parent
            will be added as the first parent, regardless of what the
            other parents are.
        :return: a list of revision ids that should be the parents when
            importing the specified revision.
        """
        assert version == versions[0], \
            "version is not the first entry of versions"
        parents = self.get_parents(versions)
        need_upstream_parent = True
        if not force_upstream_parent:
            for parent_pair in parents:
                if (parent_pair[1].upstream_version == \
                        version.upstream_version):
                    need_upstream_parent = False
                    break
        real_parents = [p[2] for p in parents]
        if need_upstream_parent:
            parent_revid = self.revid_of_upstream_version(version.upstream_version)
            if len(parents) > 0:
                real_parents.insert(1, parent_revid)
            else:
                real_parents = [parent_revid]
        return real_parents

    def _fetch_upstream_to_branch(self, revid):
        """Fetch the revision from the upstream branch in to the packaging one.
        """
        # Make sure we see any revisions added by the upstream branch
        # since self.tree was locked.
        self.branch.repository.refresh_data()
        self.branch.fetch(self.upstream_branch, last_revision=revid)
        self.upstream_branch.tags.merge_to(self.branch.tags)

    def import_upstream(self, upstream_part, version, md5, upstream_parents,
            upstream_tarball=None, upstream_branch=None,
            upstream_revision=None, timestamp=None, author=None,
            file_ids_from=None):
        """Import an upstream part on to the upstream branch.

        This imports the upstream part of the code and places it on to
        the upstream branch, setting the necessary tags.

        :param upstream_part: the path of a directory containing the
            unpacked upstream part of the source package.
        :param version: upstream version that is being imported
        :param md5: the md5 of the upstream part.
        :param upstream_parents: the parents to give the upstream revision
        :param timestamp: a tuple of (timestamp, timezone) to use for
            the commit, or None to use the current time.
        :return: (tag_name, revision_id) of the imported tarball.
        """
        # Should we just dump the upstream part on whatever is currently
        # there, or try and pull all of the other upstream versions
        # from lesser branches first? For now we'll just dump it on.
        # TODO: this method needs a lot of work for when we will make
        # the branches writeable by others.
        assert isinstance(version, str)
        mutter("Importing upstream version %s from %s with parents %s" \
                % (version, upstream_part, str(upstream_parents)))
        assert self.upstream_tree is not None, \
            "Can't import upstream with no tree"
        if len(upstream_parents) > 0:
            parent_revid = upstream_parents[0]
        else:
            parent_revid = NULL_REVISION
        self.upstream_tree.pull(self.upstream_tree.branch, overwrite=True,
                stop_revision=parent_revid)
        other_branches = self.get_other_branches()
        def get_last_revision_tree(br):
            return br.repository.revision_tree(br.last_revision())
        upstream_trees = [get_last_revision_tree(o.upstream_branch)
            for o in other_branches]
        target_tree = None
        if upstream_branch is not None:
            if upstream_revision is None:
                upstream_revision = upstream_branch.last_revision()
            self.upstream_branch.fetch(upstream_branch,
                    last_revision=upstream_revision)
            upstream_branch.tags.merge_to(self.upstream_branch.tags)
            upstream_parents.append(upstream_revision)
            target_tree = self.upstream_branch.repository.revision_tree(
                        upstream_revision)
        if file_ids_from is not None:
            upstream_trees = file_ids_from + upstream_trees
        if self.tree:
            self_tree = self.tree
            self_tree.lock_write() # might also be upstream tree for dh_make
        else:
            self_tree = self.get_branch_tip_revtree()
            self_tree.lock_read()
        try:
            import_dir(self.upstream_tree, upstream_part,
                    file_ids_from=[self_tree] + upstream_trees,
                    target_tree=target_tree)
        finally:
            self_tree.unlock()
        self.upstream_tree.set_parent_ids(upstream_parents)
        revprops = {"deb-md5": md5}
        if upstream_tarball is not None:
            delta = self.make_pristine_tar_delta(
                self.upstream_tree, upstream_tarball)
            uuencoded = standard_b64encode(delta)
            if upstream_tarball.endswith(".tar.bz2"):
                revprops["deb-pristine-delta-bz2"] = uuencoded
            else:
                revprops["deb-pristine-delta"] = uuencoded
        if author is not None:
            revprops['authors'] = author
        timezone=None
        if timestamp is not None:
            timezone = timestamp[1]
            timestamp = timestamp[0]
        revid = self.upstream_tree.commit("Import upstream version %s" \
                % (version,),
                revprops=revprops, timestamp=timestamp, timezone=timezone)
        tag_name, _ = self.tag_upstream_version(version, revid=revid)
        return tag_name, revid

    def import_upstream_tarball(self, tarball_filename, version, parents,
        md5sum=None, upstream_branch=None, upstream_revision=None):
        """Import an upstream part to the upstream branch.

        :param tarball_filename: The tarball to import.
        :param version: The upstream version to import.
        :param parents: The tarball-branch parents to use for the import.
            If an upstream branch is supplied, its automatically added to
            parents.
        :param upstream_branch: An upstream branch to associate with the
            tarball.
        :param upstream_revision: Upstream revision id
        :param md5sum: hex digest of the md5sum of the tarball, if known.
        :return: (tag_name, revision_id) of the imported tarball.
        """
        if not md5sum:
            md5sum = md5sum_filename(tarball_filename)
        tarball_dir = self._extract_tarball_to_tempdir(tarball_filename)
        try:
            return self.import_upstream(tarball_dir, version, md5sum, parents,
                upstream_tarball=tarball_filename,
                upstream_branch=upstream_branch,
                upstream_revision=upstream_revision)
        finally:
            shutil.rmtree(tarball_dir)

    def get_branch_tip_revtree(self):
        return self.branch.repository.revision_tree(
                self.branch.last_revision())

    def _mark_native_config(self, native):
        poss_native_tree = self.get_branch_tip_revtree()
        current_native = self._is_tree_native(poss_native_tree)
        current_config = self._default_config_for_tree(poss_native_tree)
        dirname = os.path.join(self.tree.basedir,
                '.bzr-builddeb')
        if current_config is not None:
            # Add that back to the current tree
            if not os.path.exists(dirname):
                os.mkdir(dirname)
            current_config.filename = os.path.join(dirname,
                    'default.conf')
            current_config.write()
            dir_id = poss_native_tree.path2id('.bzr-builddeb')
            file_id = poss_native_tree.path2id(
                    '.bzr-builddeb/default.conf')
            self.tree.add(['.bzr-builddeb/',
                    '.bzr-builddeb/default.conf'],
                    ids=[dir_id, file_id])
        if native != current_native:
            if current_config is None:
                needs_add = True
                if native:
                    current_config = ConfigObj()
                    current_config['BUILDDEB'] = {}
            if current_config is not None:
                if native:
                    current_config['BUILDDEB']['native'] = True
                else:
                    del current_config['BUILDDEB']['native']
                    if len(current_config['BUILDDEB']) == 0:
                        del current_config['BUILDDEB']
                if len(current_config) == 0:
                    self.tree.remove(['.bzr-builddeb',
                            '.bzr-builddeb/default.conf'],
                            keep_files=False)
                else:
                    if needs_add:
                        os.mkdir(dirname)
                    current_config.filename = os.path.join(dirname,
                            'default.conf')
                    current_config.write()
                    if needs_add:
                        self.tree.add(['.bzr-builddeb/',
                                '.bzr-builddeb/default.conf'])

    def import_debian(self, debian_part, version, parents, md5,
            native=False, timestamp=None, file_ids_from=None):
        """Import the debian part of a source package.

        :param debian_part: the path of a directory containing the unpacked
            source package.
        :param version: the Version of the source package.
        :param parents: a list of revision ids that should be the
            parents of the imported revision.
        :param md5: the md5 sum reported by the .dsc for
            the .diff.gz part of this source package.
        :param native: whether the package is native.
        :param timestamp: a tuple of (timestamp, timezone) to use for
            the commit, or None to use the current values.
        """
        mutter("Importing debian part for version %s from %s, with parents "
                "%s" % (str(version), debian_part, str(parents)))
        assert self.tree is not None, "Can't import with no tree"
        # First we move the branch to the first parent
        if parents:
            if self.branch.last_revision() == NULL_REVISION:
                parent_revid = parents[0]
                self.tree.pull(self.tree.branch, overwrite=True,
                        stop_revision=parent_revid)
            elif parents[0] != self.branch.last_revision():
                mutter("Adding current tip as parent: %s"
                        % self.branch.last_revision())
                parents.insert(0, self.branch.last_revision())
        elif self.branch.last_revision() != NULL_REVISION:
            # We were told to import with no parents. That's not
            # right, so import with the current parent. Should
            # perhaps be fixed in the methods to determine the parents.
            mutter("Told to import with no parents. Adding current tip "
                   "as the single parent")
            parents = [self.branch.last_revision()]
        other_branches = self.get_other_branches()
        def get_last_revision_tree(br):
            return br.repository.revision_tree(br.last_revision())
        debian_trees = [get_last_revision_tree(o.branch)
            for o in other_branches]
        parent_trees = []
        if file_ids_from is not None:
            parent_trees = file_ids_from[:]
        for parent in parents:
            parent_trees.append(self.branch.repository.revision_tree(
                        parent))
        import_dir(self.tree, debian_part,
                file_ids_from=parent_trees + debian_trees)
        rules_path = os.path.join(self.tree.basedir, 'debian', 'rules')
        if os.path.isfile(rules_path):
            os.chmod(rules_path,
                     (stat.S_IRWXU|stat.S_IRGRP|stat.S_IXGRP|
                      stat.S_IROTH|stat.S_IXOTH))
        self.tree.set_parent_ids(parents)
        changelog_path = os.path.join(self.tree.basedir, 'debian',
                'changelog')
        if os.path.exists(changelog_path):
            f = open(changelog_path)
            try:
                changelog_contents = f.read()
            finally:
                f.close()
            changelog = Changelog(file=changelog_contents, max_blocks=1)
        message, authors, thanks, bugs = \
                get_commit_info_from_changelog(changelog, self.branch)
        if message is None:
            message = 'Import packaging changes for version %s' % \
                        (str(version),)
        revprops={"deb-md5":md5}
        if native:
            revprops['deb-native'] = "True"
        if authors:
            revprops['authors'] = "\n".join(authors)
        if thanks:
            revprops['deb-thanks'] = "\n".join(thanks)
        if bugs:
            revprops['bugs'] = "\n".join(bugs)
        timezone = None
        if timestamp is not None:
            timezone = timestamp[1]
            timestamp = timestamp[0]
        self._mark_native_config(native)
        revid = self.tree.commit(message, revprops=revprops, timestamp=timestamp,
                timezone=timezone)
        self.tag_version(version, revid=revid)

    def upstream_parents(self, versions, version):
        """Get the parents for importing a new upstream.

        The upstream parents will be the last upstream version,
        except for some cases when the last version was native.

        :return: the list of revision ids to use as parents when
            importing the specified upstream version.
        """
        parents = []
        first_parent = self.upstream_branch.last_revision()
        if first_parent != NULL_REVISION:
            parents = [first_parent]
        last_contained_version = self.last_contained_version(versions)
        if last_contained_version is not None:
            # If the last version was native, and was not from the same
            # upstream as a non-native version (i.e. it wasn't a mistaken
            # native -2 version), then we want to add an extra parent.
            if (self.is_version_native(last_contained_version)
                and not self.has_upstream_version(last_contained_version.upstream_version)):
                revid = self.revid_of_version(last_contained_version)
                parents.append(revid)
                self.upstream_branch.fetch(self.branch,
                        last_revision=revid)
        pull_parents = self.get_parents(versions)
        if ((first_parent == NULL_REVISION and len(pull_parents) > 0)
                or len(pull_parents) > 1):
            if first_parent == NULL_REVISION:
                pull_branch = pull_parents[0][0]
                pull_version = pull_parents[0][1]
            else:
                pull_branch = pull_parents[1][0]
                pull_version = pull_parents[1][1]
            if not pull_branch.is_version_native(pull_version):
                    pull_revid = \
                        pull_branch.revid_of_upstream_version(pull_version.upstream_version)
                    mutter("Initialising upstream from %s, version %s" \
                        % (str(pull_branch), str(pull_version)))
                    parents.append(pull_revid)
                    self.upstream_branch.fetch(
                            pull_branch.upstream_branch,
                            last_revision=pull_revid)
                    pull_branch.upstream_branch.tags.merge_to(
                            self.upstream_branch.tags)
        return parents

    def get_changelog_from_source(self, dir):
        cl_filename = os.path.join(dir, "debian", "changelog")
        cl = Changelog()
        cl.parse_changelog(open(cl_filename).read(), strict=False)
        return cl

    def _do_import_package(self, version, versions, debian_part, md5,
            upstream_part, upstream_md5, upstream_tarball=None,
            timestamp=None, author=None, file_ids_from=None,
            pull_debian=True):
        pull_branch = None
        if pull_debian:
            pull_branch = self.branch_to_pull_version_from(version, md5)
        if pull_branch is not None:
            if (self.branch_to_pull_upstream_from(version.upstream_version,
                        upstream_md5)
                    is None):
                pull_branch = None
        if pull_branch is not None:
            self.pull_version_from_branch(pull_branch, version)
        else:
            # We need to import at least the diff, possibly upstream.
            # Work out if we need the upstream part first.
            imported_upstream = False
            if not self.has_upstream_version(version.upstream_version):
                up_pull_branch = \
                    self.branch_to_pull_upstream_from(version.upstream_version,
                            upstream_md5)
                if up_pull_branch is not None:
                    self.pull_upstream_from_branch(up_pull_branch,
                            version.upstream_version)
                else:
                    imported_upstream = True
                    # Check whether we should pull first if this initialises
                    # from another branch:
                    upstream_parents = self.upstream_parents(versions,
                            version.upstream_version)
                    _, new_revid = self.import_upstream(upstream_part,
                            version.upstream_version,
                            upstream_md5, upstream_parents,
                            upstream_tarball=upstream_tarball,
                            timestamp=timestamp, author=author,
                            file_ids_from=file_ids_from)
                    self._fetch_upstream_to_branch(new_revid)
            else:
                mutter("We already have the needed upstream part")
            parents = self.get_parents_with_upstream(version, versions,
                    force_upstream_parent=imported_upstream)
            # Now we have the list of parents we need to import the .diff.gz
            self.import_debian(debian_part, version, parents, md5,
                    timestamp=timestamp, file_ids_from=file_ids_from)

    def get_native_parents(self, version, versions):
        last_contained_version = self.last_contained_version(versions)
        if last_contained_version is None:
            parents = []
        else:
            parents = [self.revid_of_version(last_contained_version)]
        missing_versions = self.missing_versions(versions)
        for branch in reversed(self.get_lesser_branches()):
            merged, missing_versions = \
                branch.contained_versions(missing_versions)
            if merged:
                revid = branch.revid_of_version(merged[0])
                parents.append(revid)
                #FIXME: should this really be here?
                branch.branch.tags.merge_to(self.branch.tags)
                self.branch.fetch(branch.branch,
                        last_revision=revid)
                if self.upstream_branch.last_revision() == NULL_REVISION:
                    self.upstream_tree.pull(branch.upstream_branch)
                    branch.upstream_branch.tags.merge_to(self.upstream_branch.tags)
        for branch in self.get_greater_branches():
            merged, missing_versions = \
                branch.contained_versions(missing_versions)
            if merged:
                revid = branch.revid_of_version(merged[0])
                parents.append(revid)
                #FIXME: should this really be here?
                branch.branch.tags.merge_to(self.branch.tags)
                self.branch.fetch(branch.branch,
                        last_revision=revid)
                if self.upstream_branch.last_revision() == NULL_REVISION:
                    self.upstream_tree.pull(branch.upstream_branch)
                    branch.upstream_branch.tags.merge_to(self.upstream_branch.tags)
        if (self.branch.last_revision() != NULL_REVISION
                and not self.branch.last_revision() in parents):
            parents.insert(0, self.branch.last_revision())
        return parents

    def _import_native_package(self, version, versions, debian_part, md5,
            timestamp=None, file_ids_from=None, pull_debian=True):
        pull_branch = None
        if pull_debian:
            pull_branch = self.branch_to_pull_version_from(version, md5)
        if pull_branch is not None:
            self.pull_version_from_branch(pull_branch, version, native=True)
        else:
            parents = self.get_native_parents(version, versions)
            self.import_debian(debian_part, version, parents, md5,
                    native=True, timestamp=timestamp,
                    file_ids_from=file_ids_from)

    def _get_safe_versions_from_changelog(self, cl):
        versions = []
        for block in cl._blocks:
            try:
                versions.append(block.version)
            except VersionError:
                break
        return versions

    def import_package(self, dsc_filename, use_time_from_changelog=True,
            file_ids_from=None, pull_debian=True):
        """Import a source package.

        :param dsc_filename: a path to a .dsc file for the version
            to be imported.
        :param use_time_from_changelog: whether to use the current time or
            the one from the last changelog entry.
        """
        base_path = osutils.dirname(dsc_filename)
        dsc = deb822.Dsc(open(dsc_filename).read())
        version = Version(dsc['Version'])
        format = dsc.get('Format', '1.0').strip()
        extractor_cls = SOURCE_EXTRACTORS.get(format)
        if extractor_cls is None:
            raise AssertionError("Don't know how to import source format %s yet"
                    % format)
        extractor = extractor_cls(dsc_filename, dsc)
        try:
            extractor.extract()
            cl = self.get_changelog_from_source(extractor.extracted_debianised)
            timestamp = None
            author = None
            if use_time_from_changelog and len(cl._blocks) > 0:
                 raw_timestamp = cl.date
                 import rfc822, time
                 time_tuple = rfc822.parsedate_tz(raw_timestamp)
                 if time_tuple is not None:
                     timestamp = (time.mktime(time_tuple[:9]), time_tuple[9])
                 author = safe_decode(cl.author)
            versions = self._get_safe_versions_from_changelog(cl)
            assert not self.has_version(version), \
                "Trying to import version %s again" % str(version)
            #TODO: check that the versions list is correctly ordered,
            # as some methods assume that, and it's not clear what
            # should happen if it isn't.
            if extractor.extracted_upstream is not None:
                self._do_import_package(version, versions,
                        extractor.extracted_debianised,
                        extractor.unextracted_debian_md5,
                        extractor.extracted_upstream,
                        extractor.unextracted_upstream_md5,
                        upstream_tarball=extractor.unextracted_upstream,
                        timestamp=timestamp, author=author,
                        file_ids_from=file_ids_from,
                        pull_debian=pull_debian)
            else:
                self._import_native_package(version, versions,
                        extractor.extracted_debianised,
                        extractor.unextracted_debian_md5,
                        timestamp=timestamp, file_ids_from=file_ids_from,
                        pull_debian=pull_debian)
        finally:
            extractor.cleanup()

    def extract_upstream_tree(self, upstream_tip, basedir):
        """Extract upstream_tip to a tempdir as a working tree."""
        # TODO: should stack rather than trying to use the repository,
        # as that will be more efficient.
        # TODO: remove the _extract_upstream_tree alias below.
        to_location = os.path.join(basedir, "upstream")
        # Use upstream_branch if it has been set, otherwise self.branch.
        source_branch = self.upstream_branch or self.branch
        dir_to = source_branch.bzrdir.sprout(to_location,
                revision_id=upstream_tip,
                accelerator_tree=self.tree)
        try:
            self.upstream_tree = dir_to.open_workingtree()
        except NoWorkingTree:
            # Handle shared treeless repo's.
            self.upstream_tree = dir_to.create_workingtree()
        self.upstream_branch = self.upstream_tree.branch

    _extract_upstream_tree = extract_upstream_tree

    def _create_empty_upstream_tree(self, basedir):
        to_location = os.path.join(basedir, "upstream")
        to_transport = get_transport(to_location)
        to_transport.ensure_base()
        format = bzrdir.format_registry.make_bzrdir('default')
        try:
            existing_bzrdir = bzrdir.BzrDir.open_from_transport(
                    to_transport)
        except NotBranchError:
            # really a NotBzrDir error...
            create_branch = bzrdir.BzrDir.create_branch_convenience
            branch = create_branch(to_transport.base,
                    format=format,
                    possible_transports=[to_transport])
        else:
            if existing_bzrdir.has_branch():
                raise AlreadyBranchError(to_location)
            else:
                branch = existing_bzrdir.create_branch()
                existing_bzrdir.create_workingtree()
        self.upstream_branch = branch
        self.upstream_tree = branch.bzrdir.open_workingtree()
        if self.tree:
            root_id = self.tree.path2id('')
        else:
            tip = self.get_branch_tip_revtree()
            tip.lock_read()
            try:
                root_id = tip.path2id('')
            finally:
                tip.unlock()
        if root_id:
            self.upstream_tree.set_root_id(root_id)

    def _extract_tarball_to_tempdir(self, tarball_filename):
        tempdir = tempfile.mkdtemp()
        if tarball_filename.endswith(".tar.bz2"):
            tar_args = 'xjf'
        else:
            tar_args = 'xzf'
        try:
            proc = subprocess.Popen(["tar", tar_args, tarball_filename, "-C",
                    tempdir, "--strip-components", "1"],
                    preexec_fn=subprocess_setup)
            proc.communicate()
            if proc.returncode != 0:
                raise TarFailed("extract", tarball_filename)
            return tempdir
        except:
            shutil.rmtree(tempdir)
            raise

    def _export_previous_upstream_tree(self, package, previous_version, tempdir, upstream_branch=None):
        assert isinstance(previous_version, str), \
            "Should pass upstream version as str, not Version."
        if self.pristine_tar_source.has_version(package, previous_version):
            upstream_tip = self.pristine_tar_source.version_as_revision(
                    package, previous_version)
            self.extract_upstream_tree(upstream_tip, tempdir)
        elif self.upstream_source is not None:
            upstream_tip = self.upstream_source.version_as_revision(package, previous_version)
            self.extract_upstream_tree(upstream_tip, tempdir)
        else:
            raise BzrCommandError("Unable to find the tag for the "
                    "previous upstream version, %s, in the branch: "
                    "%s" % (
                previous_version,
                self.pristine_tar_source.tag_name(previous_version)))

    def merge_upstream(self, tarball_filename, package, version, previous_version,
            upstream_branch=None, upstream_revision=None, merge_type=None,
            force=False):
        assert self.upstream_branch is None, \
                "Should use self.upstream_branch if set"
        assert isinstance(version, str), \
            "Should pass version as str not %s" % str(type(version))
        assert isinstance(previous_version, str) or previous_version is None, \
            "Should pass previous_version as str not %s" % str(
                    type(previous_version))
        tempdir = tempfile.mkdtemp(dir=os.path.join(self.tree.basedir, '..'))
        try:
            if previous_version is not None:
                self._export_previous_upstream_tree(package, previous_version, tempdir,
                    upstream_branch)
            else:
                self._create_empty_upstream_tree(tempdir)
            if self.pristine_tar_source.has_version(package, version):
                raise UpstreamAlreadyImported(version)
            if upstream_branch is not None:
                upstream_branch.lock_read()
            try:
                if upstream_branch is not None:
                    if upstream_revision is None:
                        upstream_revision = upstream_branch.last_revision()
                    graph = self.branch.repository.get_graph(
                            other_repository=upstream_branch.repository)
                    if not force and graph.is_ancestor(upstream_revision,
                            self.branch.last_revision()):
                        raise UpstreamBranchAlreadyMerged
                tarball_filename = os.path.abspath(tarball_filename)
                md5sum = md5sum_filename(tarball_filename)
                tarball_dir = self._extract_tarball_to_tempdir(tarball_filename)
                try:
                    # FIXME: should use upstream_parents()?
                    parents = []
                    if self.upstream_branch.last_revision() != NULL_REVISION:
                        parents = [self.upstream_branch.last_revision()]
                    _, new_revid = self.import_upstream(tarball_dir,
                            version,
                            md5sum, parents, upstream_tarball=tarball_filename,
                            upstream_branch=upstream_branch,
                            upstream_revision=upstream_revision)
                    self._fetch_upstream_to_branch(new_revid)
                finally:
                    shutil.rmtree(tarball_dir)
                if self.branch.last_revision() != NULL_REVISION:
                    try:
                        conflicts = self.tree.merge_from_branch(
                                self.upstream_branch, merge_type=merge_type)
                    except UnrelatedBranches:
                        # Bug lp:515367 where the first upstream tarball is
                        # missing a proper history link and a criss-cross merge
                        # then recurses and finds no deeper ancestor.
                        # Use the previous upstream import as the from revision
                        if len(parents) == 0:
                            from_revision = NULL_REVISION
                        else:
                            from_revision = parents[0]
                        conflicts = self.tree.merge_from_branch(
                                self.upstream_branch, merge_type=merge_type,
                                from_revision=from_revision)
                else:
                    # Pull so that merge-upstream allows you to start a branch
                    # from upstream tarball.
                    conflicts = 0
                    self.tree.pull(self.upstream_branch)
                self.upstream_branch.tags.merge_to(self.branch.tags)
                return conflicts
            finally:
                if upstream_branch is not None:
                    upstream_branch.unlock()
        finally:
            shutil.rmtree(tempdir)

    def make_pristine_tar_delta(self, tree, tarball_path):
        tmpdir = tempfile.mkdtemp(prefix="builddeb-pristine-")
        try:
            dest = os.path.join(tmpdir, "orig")
            tree.lock_read()
            try:
                for (dp, ie) in tree.inventory.iter_entries():
                    ie._read_tree_state(dp, tree)
                export(tree, dest, format='dir')
            finally:
                tree.unlock()
            return make_pristine_tar_delta(dest, tarball_path)
        finally:
            shutil.rmtree(tmpdir)


class SourceExtractor(object):
    """A class to extract a source package to its constituent parts"""

    def __init__(self, dsc_path, dsc):
        self.dsc_path = dsc_path
        self.dsc = dsc
        self.extracted_upstream = None
        self.extracted_debianised = None
        self.unextracted_upstream = None
        self.unextracted_debian_md5 = None
        self.unextracted_upstream_md5 = None

    def extract(self):
        """Extract the package to a new temporary directory."""
        self.tempdir = tempfile.mkdtemp()
        dsc_filename = os.path.abspath(self.dsc_path)
        proc = subprocess.Popen("dpkg-source -su -x %s" % (dsc_filename,), shell=True,
                cwd=self.tempdir, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, preexec_fn=subprocess_setup)
        (stdout, _) = proc.communicate()
        assert proc.returncode == 0, "dpkg-source -x failed, output:\n%s" % \
                    (stdout,)
        name = self.dsc['Source']
        version = Version(self.dsc['Version'])
        self.extracted_upstream = os.path.join(self.tempdir,
                "%s-%s.orig" % (name, str(version.upstream_version)))
        self.extracted_debianised = os.path.join(self.tempdir,
                "%s-%s" % (name, str(version.upstream_version)))
        if not os.path.exists(self.extracted_upstream):
            mutter("It's a native package")
            self.extracted_upstream = None
        for part in self.dsc['files']:
            if self.extracted_upstream is None:
                if part['name'].endswith(".tar.gz"):
                    self.unextracted_debian_md5 = part['md5sum']
            else:
                if part['name'].endswith(".orig.tar.gz"):
                    assert self.unextracted_upstream is None, "Two .orig.tar.gz?"
                    self.unextracted_upstream = os.path.abspath(
                            os.path.join(osutils.dirname(self.dsc_path),
                                part['name']))
                    self.unextracted_upstream_md5 = part['md5sum']
                elif part['name'].endswith(".diff.gz"):
                    self.unextracted_debian_md5 = part['md5sum']

    def cleanup(self):
        if os.path.exists(self.tempdir):
            shutil.rmtree(self.tempdir)


class ThreeDotZeroNativeSourceExtractor(SourceExtractor):

    def extract(self):
        self.tempdir = tempfile.mkdtemp()
        dsc_filename = os.path.abspath(self.dsc_path)
        proc = subprocess.Popen("dpkg-source -x %s" % (dsc_filename,), shell=True,
                cwd=self.tempdir, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, preexec_fn=subprocess_setup)
        (stdout, _) = proc.communicate()
        assert proc.returncode == 0, "dpkg-source -x failed, output:\n%s" % \
                    (stdout,)
        name = self.dsc['Source']
        version = Version(self.dsc['Version'])
        self.extracted_debianised = os.path.join(self.tempdir,
                "%s-%s" % (name, str(version.upstream_version)))
        self.extracted_upstream = None
        for part in self.dsc['files']:
            if (part['name'].endswith(".tar.gz")
                    or part['name'].endswith(".tar.bz2")):
                self.unextracted_debian_md5 = part['md5sum']


class ThreeDotZeroQuiltSourceExtractor(SourceExtractor):

    def extract(self):
        self.tempdir = tempfile.mkdtemp()
        dsc_filename = os.path.abspath(self.dsc_path)
        proc = subprocess.Popen("dpkg-source --skip-debianization -x %s"
                % (dsc_filename,), shell=True,
                cwd=self.tempdir, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, preexec_fn=subprocess_setup)
        (stdout, _) = proc.communicate()
        assert proc.returncode == 0, "dpkg-source -x failed, output:\n%s" % \
                    (stdout,)
        name = self.dsc['Source']
        version = Version(self.dsc['Version'])
        self.extracted_debianised = os.path.join(self.tempdir,
                "%s-%s" % (name, str(version.upstream_version)))
        self.extracted_upstream = self.extracted_debianised + ".orig"
        os.rename(self.extracted_debianised, self.extracted_upstream)
        proc = subprocess.Popen("dpkg-source -x %s" % (dsc_filename,), shell=True,
                cwd=self.tempdir, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, preexec_fn=subprocess_setup)
        (stdout, _) = proc.communicate()
        assert proc.returncode == 0, "dpkg-source -x failed, output:\n%s" % \
                    (stdout,)
        # Check that there are no unreadable files extracted.
        subprocess.call(["find", self.extracted_upstream, "-perm",
                "0000", "-exec", "chmod", "644", "{}", ";"])
        subprocess.call(["find", self.extracted_debianised, "-perm",
                "0000", "-exec", "chmod", "644", "{}", ";"])
        for part in self.dsc['files']:
            if (re.search("\.orig-[^.]+\.tar\.(gz|bz2|lzma)$", part['name'])):
                raise AssertionError("Can't import packages with multiple "
                    "upstream tarballs yet")
            if (part['name'].endswith(".orig.tar.gz")
                    or part['name'].endswith(".orig.tar.bz2")):
                assert self.unextracted_upstream is None, "Two .orig.tar.(gz|bz2)?"
                self.unextracted_upstream = os.path.abspath(
                        os.path.join(osutils.dirname(self.dsc_path),
                            part['name']))
                self.unextracted_upstream_md5 = part['md5sum']
            elif (part['name'].endswith(".debian.tar.gz")
                    or part['name'].endswith(".debian.tar.bz2")):
                self.unextracted_debian_md5 = part['md5sum']
        assert self.unextracted_upstream is not None, \
            "Can't handle non gz|bz2 tarballs yet"
        assert self.unextracted_debian_md5 is not None, \
            "Can't handle non gz|bz2 tarballs yet"


SOURCE_EXTRACTORS = {}
SOURCE_EXTRACTORS["1.0"] = SourceExtractor
SOURCE_EXTRACTORS[FORMAT_3_0_NATIVE] = ThreeDotZeroNativeSourceExtractor
SOURCE_EXTRACTORS[FORMAT_3_0_QUILT] = ThreeDotZeroQuiltSourceExtractor
