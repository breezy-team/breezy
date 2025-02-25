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

import calendar
import os
import stat
import tarfile
import tempfile
from contextlib import ExitStack, contextmanager
from typing import Optional

from debian import deb822
from debian.changelog import Changelog, Version, VersionError
from debmutate.versions import mangle_version_for_git

from ... import (
    controldir,
)
from ...branch import Branch
from ...config import ConfigObj
from ...errors import (
    AlreadyBranchError,
    BzrError,
    NoRoundtrippingSupport,
    NoSuchTag,
    NotBranchError,
    NoWorkingTree,
    UnrelatedBranches,
)
from ...revision import NULL_REVISION, RevisionID
from ...trace import mutter, warning
from ...transport import (
    get_transport,
)
from ...tree import Tree
from .bzrtools_import import import_dir
from .errors import (
    MultipleUpstreamTarballsNotSupported,
)
from .extract import extract
from .upstream import (
    PackageVersionNotPresent,
)
from .upstream.branch import (
    PreviousVersionTagMissing,
)
from .upstream.pristinetar import (
    get_pristine_tar_source,
)
from .util import (
    export_with_nested,
    extract_orig_tarball,
    get_commit_info_from_changelog,
    md5sum_filename,
    open_file_via_transport,
    open_transport,
)


class CorruptUpstreamSourceFile(BzrError):
    _fmt = "Corrupt upstream source file %(filename)s: %(reason)s"


class UpstreamBranchAlreadyMerged(BzrError):
    _fmt = "That revision of the upstream branch has already been merged."


class UpstreamAlreadyImported(BzrError):
    _fmt = 'Upstream version "%(version)s" has already been imported (tag: %(tag)s).'

    def __init__(self, version, tag):
        BzrError.__init__(self, version=str(version), tag=tag)


class VersionAlreadyImported(BzrError):
    _fmt = "Debian version %(version)s has already been imported."

    def __init__(self, version, tag_name):
        BzrError.__init__(self, version=str(version), tag_name=tag_name)


class DscCache:
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
            with open_file_via_transport(filename, transport) as f1:
                dsc1 = deb822.Dsc(f1)
            self.cache[name] = dsc1
            self.transport_cache[name] = transport

        return dsc1

    def get_transport(self, name):
        return self.transport_cache[name]


class DscComp:
    def __init__(self, cache):
        self.cache = cache

    def key(self, dscname):
        dsc = self.cache.get_dsc(dscname)
        return Version(dsc["Version"])


class DistributionBranchSet:
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
        return self._branch_list[index + 1 :]


def checkout_upstream_version(tree, package, version, revisions):
    """Checkout an upstream version from the pristine tar source."""
    main_revid, main_subpath = revisions[None]
    if main_subpath:
        raise Exception("subpaths not yet supported")
    tree.update(revision=main_revid)
    parent_ids = []
    for component in sorted(revisions.keys()):
        revid, subpath = revisions[component]
        if component is not None:
            component_tree = tree.branch.repository.revision_tree(revid)
            export_with_nested(
                component_tree,
                os.path.join(tree.basedir, component),
                format="dir",
                subdir=subpath,
            )
        parent_ids.append(revid)
    tree.set_parent_ids(parent_ids)


class DistributionBranch:
    """A DistributionBranch is a representation of one line of development.

    It is a branch that is linked to a line of development, such as Debian
    unstable. It also has associated branches, some of which are "lesser"
    and some are "greater". A lesser branch is one that this branch
    derives from. A greater branch is one that derives from this. For
    instance Debian experimental would have unstable as a lesser branch,
    and vice-versa. It is assumed that a group of DistributionBranches will
    have a total ordering with respect to these relationships.
    """

    def __init__(
        self, branch, pristine_upstream_branch, tree=None, pristine_upstream_tree=None
    ):
        """Create a distribution branch.

        You can only import packages on to the DistributionBranch
        if both tree and pristine_upstream_tree are provided.

        :param branch: the Branch for the packaging part.
        :param pristine_upstream_branch: the Branch for the pristine tar part,
            if any.
        :param tree: an optional tree for the branch.
        :param pristine_upstream_tree: an optional tree for the
            pristine_upstream_branch.
        """
        self.branch = branch
        self.tree = tree
        self.pristine_upstream_branch = pristine_upstream_branch
        self.pristine_upstream_tree = pristine_upstream_tree
        if pristine_upstream_branch is not None:
            self.pristine_upstream_source = get_pristine_tar_source(
                tree, pristine_upstream_branch
            )
        else:
            self.pristine_upstream_source = None
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

    def tag_name(self, version: Version, vendor: Optional[str]) -> str:
        """Gets the name of the tag that is used for the version.

        :param version: the Version object that the tag should refer to.
        :return: a String with the name of the tag.
        """
        if vendor is not None and version.debian_revision:
            return f"{vendor}/{mangle_version(self.branch, version)}"
        else:
            return mangle_version(self.branch, version)

    def has_version(
        self, version: Version, md5: Optional[str] = None, vendor: Optional[str] = None
    ) -> bool:
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
        for tag in self.possible_tags(version):
            if branch_has_debian_version(self.branch, tag, md5=md5):
                return True
        return False

    def contained_versions(
        self, versions: list[Version]
    ) -> tuple[list[Version], list[Version]]:
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
        # FIXME: should probably do an ancestory check to find all
        # merged revisions. This will avoid adding an extra parent when say
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

    def missing_versions(self, versions: list[Version]) -> list[Version]:
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

    def last_contained_version(self, versions: list[Version]) -> Optional[Version]:
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

    def possible_tags(self, version: Version, vendor: Optional[str] = None):
        if vendor:
            if version.debian_revision:
                yield from [
                    f"{vendor}-{version}",
                    f"{vendor}/{version}",
                ]
            else:
                yield str(version)
        else:
            version_str = mangle_version(self.branch, version)
            yield version_str
            yield from ["debian-{}".format(version_str), "debian/{}".format(version_str)]
            yield from ["ubuntu-{}".format(version_str), "ubuntu/{}".format(version_str)]
            yield from ["v{}".format(version_str)]

    def revid_of_version(self, version: Version) -> RevisionID:
        """Returns the revision id corresponding to that version.

        :param version: the Version object that you wish to retrieve the
            revision id of. The Version must be present in the branch.
        :return: the revision id corresponding to that version
        """
        tag = self.tag_of_version(version)
        if tag is None:
            raise NoSuchTag(version)
        return self.branch.tags.lookup_tag(tag)

    def tag_of_version(
        self, version: Version, vendor: Optional[str] = None
    ) -> Optional[str]:
        """Returns the revision id corresponding to that version.

        :param version: the Version object that you wish to retrieve the
            revision id of. The Version must be present in the branch.
        :return: the tag corresponding to that version
        """
        for tag in self.possible_tags(version, vendor):
            if branch_has_debian_version(self.branch, tag):
                return tag
        return None

    def tag_version(
        self,
        version: Version,
        revid: Optional[RevisionID] = None,
        vendor: Optional[str] = None,
    ) -> str:
        """Tags the branch's last revision with the given version.

        Sets a tag on the last revision of the branch with a tag that refers
        to the version provided.

        :param version: the Version object to derive the tag name from.
        :param revid: the revid to associate the tag with, or None for the
            tip of self.branch.
        :return: Name of the tag set
        """
        tag_name = self.tag_name(version, vendor)
        if revid is None:
            revid = self.branch.last_revision()
        self.branch.tags.set_tag(tag_name, revid)
        return tag_name

    def is_version_native(self, version: Version) -> bool:
        """Determines whether the given version is native.

        :param version: the Version object to test. Must be present in
            the branch.
        :return: True if the version is was recorded as native when
            imported, False otherwise.
        """
        revid = self.revid_of_version(version)
        rev_tree = self.branch.repository.revision_tree(revid)
        (config_fileid, config_path, current_config) = _default_config_for_tree(
            rev_tree
        )
        rev = self.branch.repository.get_revision(revid)
        try:
            prop = rev.properties["deb-native"]
            return prop == "True"
        except KeyError:
            return False

    def can_pull_from_branch(self, branch, version, md5):
        if not branch.has_version(version, md5=md5):
            return False

        # Check that they haven't diverged
        with branch.branch.lock_read():
            graph = branch.branch.repository.get_graph(self.branch.repository)
            return graph.is_ancestor(
                self.branch.last_revision(), branch.revid_of_version(version)
            )

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
        assert md5 is not None, (  # noqa: S101
            "It's not a good idea to use branch_to_pull_version_from with "
            "md5 == None, as you may pull the wrong revision."
        )
        with self.branch.lock_read():
            for branch in reversed(self.get_lesser_branches()):
                if self.can_pull_from_branch(branch, version, md5):
                    return branch
            for branch in self.get_greater_branches():
                if self.can_pull_from_branch(branch, version, md5):
                    return branch
            return None

    def can_pull_upstream_from_branch(
        self, branch, package, version, upstream_tarballs=None
    ):
        """Check if a version can be pulled from another branch into this one.

        :param branch: Branch with upstream version
        :param package: Package name
        :param version: Package version
        :param upstream_tarballs: Required upstream tarballs (optional)
        """
        if not branch.pristine_upstream_source.has_version(
            package, version, tarballs=upstream_tarballs
        ):
            return False

        up_branch = self.pristine_upstream_branch
        with up_branch.lock_read():
            # Check that they haven't diverged
            other_up_branch = branch.pristine_upstream_branch
            with other_up_branch.lock_read():
                graph = other_up_branch.repository.get_graph(up_branch.repository)
                pristine_upstream_revids = (
                    branch.pristine_upstream_source.version_as_revisions(
                        package, version, tarballs=upstream_tarballs
                    )
                )
                for (
                    pristine_upstream_revid,
                    _pristine_upstream_subpath,
                ) in pristine_upstream_revids.values():
                    if not graph.is_ancestor(
                        up_branch.last_revision(), pristine_upstream_revid
                    ):
                        return False
                return True

    def branch_to_pull_upstream_from(self, package, version, upstream_tarballs):
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
        :return: a DistributionBranch object to pull the upstream from
            if that is what should be done, otherwise None.
        """
        for branch in reversed(self.get_lesser_branches()):
            if self.can_pull_upstream_from_branch(
                branch, package, version, upstream_tarballs
            ):
                return branch
        for branch in self.get_greater_branches():
            if self.can_pull_upstream_from_branch(
                branch, package, version, upstream_tarballs
            ):
                return branch
        return None

    def get_parents(self, versions: list[Version]):
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
        if len(versions) == 0:
            raise AssertionError("Need a version to import")
        mutter("Getting parents of %s", versions)
        missing_versions = self.missing_versions(versions)
        mutter("Versions we don't have are %s", missing_versions)
        last_contained_version = self.last_contained_version(versions)
        parents = []
        if last_contained_version is not None:
            if last_contained_version == versions[0]:
                raise AssertionError("Reupload of a version?")
            mutter("The last versions we do have is %s", str(last_contained_version))
            parents = [
                (
                    self,
                    last_contained_version,
                    self.revid_of_version(last_contained_version),
                    "",
                )
            ]
        else:
            mutter("We don't have any of those versions")
        for branch in (
            list(reversed(self.get_lesser_branches())) + self.get_greater_branches()
        ):
            merged, missing_versions = branch.contained_versions(missing_versions)
            if merged:
                revid = branch.revid_of_version(merged[0])
                parents.append((branch, merged[0], revid, ""))
                mutter(
                    "Adding merge from related branch of %s for version %s",
                    revid,
                    str(merged[0]),
                )
                # FIXME: should this really be here?
                self._fetch_from_branch(branch, revid)
        return parents

    def pull_upstream_from_branch(self, pull_branch, package, version):
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
        pull_revisions = pull_branch.pristine_upstream_source.version_as_revisions(
            package, version
        )
        for component, (pull_revision, _pull_subpath) in pull_revisions.items():
            mutter(
                "Fetching upstream part %s of %s from revision %s",
                component,
                version,
                pull_revision,
            )
            if self.pristine_upstream_tree is None:
                raise AssertionError("Can't pull upstream with no tree")
            self.pristine_upstream_branch.pull(
                pull_branch.pristine_upstream_branch, stop_revision=pull_revision
            )
            self.pristine_upstream_source.tag_version(version, pull_revision)
            self.branch.fetch(self.pristine_upstream_branch, pull_revision)
            self.pristine_upstream_branch.tags.merge_to(self.branch.tags)
        checkout_upstream_version(
            self.pristine_upstream_tree, package, version, pull_revisions
        )

    def pull_version_from_branch(
        self, pull_branch, package, version, native=False
    ) -> str:
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
        mutter(
            "already has version %s so pulling from revision %s",
            str(version),
            pull_revision,
        )
        if self.tree is None:
            raise AssertionError("Can't pull branch with no tree")
        self.tree.pull(pull_branch.branch, stop_revision=pull_revision)
        tag_name = self.tag_version(version, revid=pull_revision)
        if not native and not self.pristine_upstream_source.has_version(
            package, version.upstream_version
        ):
            if pull_branch.pristine_upstream_source.has_version(
                package, version.upstream_version
            ):
                self.pull_upstream_from_branch(
                    pull_branch, package, version.upstream_version
                )
            else:
                raise AssertionError(
                    "Can't find the needed upstream part for version {}".format(version)
                )
        if (
            native
            and self.pristine_upstream_branch.last_revision() == NULL_REVISION
            and pull_branch.pristine_upstream_branch.last_revision() != NULL_REVISION
        ):
            # in case the package wasn't native before then we pull
            # the upstream. These checks may be a bit restrictive.
            self.pristine_upstream_tree.pull(pull_branch.pristine_upstream_branch)
            pull_branch.pristine_upstream_branch.tags.merge_to(
                self.pristine_upstream_branch.tags
            )
        elif native:
            mutter("Not checking for upstream as it is a native package")
        else:
            mutter(
                "Not importing the upstream part as it is already "
                "present in the upstream branch"
            )
        return tag_name

    def get_parents_with_upstream(
        self, package, version, versions, tarballs, force_upstream_parent=False
    ):
        """Get the list of parents including any upstream parents.

        Further to get_parents this method includes any upstream parents
        that are needed. An upstream parent is needed if none of
        the other parents include the upstream version. The needed
        upstream must already present in the upstream branch before
        calling this method.

        If force_upstream_parent is True then the upstream parent will
        be included, even if another parent is already using that
        upstream. This is for use in cases where the .orig.tar.gz
        is different in two distributions.

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
        if version != versions[0]:
            raise AssertionError("version is not the first entry of versions")
        parents = self.get_parents(versions)
        need_upstream_parent = True
        if not force_upstream_parent:
            for parent_pair in parents:
                if parent_pair[1].upstream_version == version.upstream_version:
                    need_upstream_parent = False
                    break
        real_parents = [(p[2], p[3]) for p in parents]
        if need_upstream_parent:
            upstream_revids = self.pristine_upstream_source.version_as_revisions(
                package, version.upstream_version, tarballs
            )

            def key(a):
                if a is None:
                    return ""
                return a

            for component in sorted(upstream_revids.keys(), key=key):
                if len(real_parents) > 0:
                    real_parents.insert(1, upstream_revids[component])
                else:
                    real_parents = [upstream_revids[component]]
        return real_parents

    def _fetch_upstream_to_branch(self, imported_revids):
        """Fetch the revision from the upstream branch in to the packaging one."""
        # Make sure we see any revisions added by the upstream branch
        # since self.tree was locked.
        self.branch.repository.refresh_data()
        for (
            _component,
            _tag,
            revid,
            _pristine_tar_imported,
            _subpath,
        ) in imported_revids:
            self.branch.fetch(self.pristine_upstream_branch, revid)
        self.pristine_upstream_branch.tags.merge_to(self.branch.tags)

    def import_upstream(
        self,
        upstream_part: str,
        package: str,
        version: str,
        upstream_parents,
        upstream_tarballs,
        upstream_branch=None,
        upstream_revisions=None,
        timestamp=None,
        author=None,
        file_ids_from=None,
        force_pristine_tar=False,
        committer=None,
        files_excluded=None,
    ):
        """Import an upstream part on to the upstream branch.

        This imports the upstream part of the code and places it on to
        the upstream branch, setting the necessary tags.

        :param upstream_part: the path of a directory containing the
            unpacked upstream part of the source package.
        :param version: upstream version that is being imported
        :param upstream_parents: the parents to give the upstream revision
        :param timestamp: a tuple of (timestamp, timezone) to use for
            the commit, or None to use the current time.
        :return: list with
            (component, tag, revid, pristine_tar_imported, subpath) tuples
        """
        # Should we just dump the upstream part on whatever is currently
        # there, or try and pull all of the other upstream versions
        # from lesser branches first? For now we'll just dump it on.
        # TODO: this method needs a lot of work for when we will make
        # the branches writeable by others.
        mutter(
            "Importing upstream version %s from %s with parents %r",
            version,
            upstream_part,
            upstream_parents,
        )
        if self.pristine_upstream_tree is None:
            raise AssertionError("Can't import upstream with no tree")
        other_branches = self.get_other_branches()
        ret = []
        for tarball, component, md5 in upstream_tarballs:
            parents = upstream_parents.get(component, [])
            if upstream_revisions is not None:
                revid, subpath = upstream_revisions[component]
            else:
                revid = None
                subpath = ""
            if subpath:
                raise Exception("subpaths are not yet supported")
            upstream_trees = [
                o.pristine_upstream_branch.basis_tree() for o in other_branches
            ]
            target_tree = None
            if upstream_branch is not None:
                if revid is None:
                    # FIXME: This is wrong for component tarballs
                    revid = upstream_branch.last_revision()
                try:
                    self.pristine_upstream_branch.fetch(upstream_branch, revid)
                except NoRoundtrippingSupport:
                    fetch_result = self.pristine_upstream_branch.fetch(
                        upstream_branch, revid, lossy=True
                    )
                    revid = fetch_result.revidmap[revid]
                upstream_branch.tags.merge_to(self.pristine_upstream_branch.tags)
                parents.append((revid, ""))
                target_tree = self.pristine_upstream_branch.repository.revision_tree(
                    revid
                )
            if file_ids_from is not None:
                upstream_trees = file_ids_from + upstream_trees
            if self.tree:
                self_tree = self.tree
                self_tree.lock_write()
            else:
                self_tree = self.branch.basis_tree()
                self_tree.lock_read()
            if len(parents) > 0:
                parent_revid, parent_subpath = parents[0]
            else:
                parent_revid = NULL_REVISION
                parent_subpath = None
            if parent_subpath:
                raise Exception("subpaths are not supported yet")
            self.pristine_upstream_tree.pull(
                self.pristine_upstream_tree.branch,
                overwrite=True,
                stop_revision=parent_revid,
            )
            if component is None:
                path = upstream_part
            else:
                path = os.path.join(upstream_part, component)
            try:
                import_dir(
                    self.pristine_upstream_tree,
                    path,
                    file_ids_from=[self_tree] + upstream_trees,
                    target_tree=target_tree,
                )
            finally:
                self_tree.unlock()
            if component is None:
                exclude = [tb[1] for tb in upstream_tarballs if tb[1] is not None]
            else:
                exclude = []
            (
                tag,
                revid,
                pristine_tar_imported,
            ) = self.pristine_upstream_source.import_component_tarball(
                package,
                version,
                self.pristine_upstream_tree,
                parents,
                component,
                md5,
                tarball,
                author=author,
                timestamp=timestamp,
                exclude=exclude,
                force_pristine_tar=force_pristine_tar,
                committer=committer,
                files_excluded=files_excluded,
                reuse_existing=True,
            )
            self.pristine_upstream_branch.generate_revision_history(revid)
            ret.append((component, tag, revid, pristine_tar_imported, subpath))
            self.branch.fetch(self.pristine_upstream_branch)
            self.branch.tags.set_tag(tag, revid)
        return ret

    def import_upstream_tarballs(
        self,
        tarballs,
        package,
        version,
        parents,
        upstream_branch=None,
        upstream_revisions=None,
        force_pristine_tar=False,
        committer=None,
        files_excluded=None,
    ):
        """Import an upstream part to the upstream branch.

        Args:
          tarballs: List of tarballs / components to extract
          version: The upstream version to import.
          parents: The tarball-branch parents to use for the import.
            If an upstream branch is supplied, its automatically added to
            parents.
          upstream_branch: An upstream branch to associate with the
            tarball.
          upstream_revisions: Upstream revision ids dictionary
          md5sum: hex digest of the md5sum of the tarball, if known.

        Returns:
          list with (component, tag, revid, pristine_tar_imported, subpath)
          tuples
        """
        with _extract_tarballs_to_tempdir(tarballs) as tarball_dir:
            return self.import_upstream(
                tarball_dir,
                package,
                version,
                parents,
                tarballs,
                upstream_branch=upstream_branch,
                upstream_revisions=upstream_revisions,
                force_pristine_tar=force_pristine_tar,
                committer=committer,
                files_excluded=files_excluded,
            )

    def import_debian(
        self,
        debian_part,
        version,
        parents,
        md5,
        *,
        native: bool = False,
        timestamp=None,
        file_ids_from: Optional[list[Tree]] = None,
    ):
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
        mutter(
            "Importing debian part for version %s from %s, with parents " "%s",
            str(version),
            debian_part,
            str(parents),
        )
        if self.tree is None:
            raise AssertionError("Can't import with no tree")
        # First we move the branch to the first parent
        if parents:
            if self.branch.last_revision() == NULL_REVISION:
                parent_revid, parent_subpath = parents[0]
                if parent_subpath:
                    raise Exception("subpaths are not yet supported")
                self.tree.pull(
                    self.tree.branch, overwrite=True, stop_revision=parent_revid
                )
            elif parents[0][0] != self.branch.last_revision():
                mutter("Adding current tip as parent: %s", self.branch.last_revision())
                parents.insert(0, (self.branch.last_revision(), ""))
        elif self.branch.last_revision() != NULL_REVISION:
            # We were told to import with no parents. That's not
            # right, so import with the current parent. Should
            # perhaps be fixed in the methods to determine the parents.
            mutter(
                "Told to import with no parents. Adding current tip "
                "as the single parent"
            )
            parents = [(self.branch.last_revision(), "")]
        other_branches = self.get_other_branches()
        debian_trees = [o.branch.basis_tree() for o in other_branches]
        parent_trees = []
        if file_ids_from is not None:
            parent_trees = file_ids_from[:]
        for parent_revid, _parent_subpath in parents:
            parent_trees.append(self.branch.repository.revision_tree(parent_revid))
        import_dir(self.tree, debian_part, file_ids_from=parent_trees + debian_trees)
        rules_path = os.path.join(self.tree.basedir, "debian", "rules")
        if os.path.isfile(rules_path):
            os.chmod(
                rules_path,
                (
                    stat.S_IRWXU  # noqa: S103
                    | stat.S_IRGRP
                    | stat.S_IXGRP
                    | stat.S_IROTH
                    | stat.S_IXOTH
                ),
            )
        self.tree.set_parent_ids(
            [parent_revid for (parent_revid, parent_subpath) in parents]
        )
        changelog_path = os.path.join(self.tree.basedir, "debian", "changelog")
        if os.path.exists(changelog_path):
            changelog = get_changelog_from_source(self.tree.basedir, max_blocks=1)
        message, authors, thanks, bugs = get_commit_info_from_changelog(
            changelog, self.branch
        )
        if message is None:
            message = f"Import packaging changes for version {version!s}"
        supports_revprops = (
            self.tree.branch.repository._format.supports_custom_revision_properties
        )
        revprops = {}
        if authors:
            revprops["authors"] = "\n".join(authors)
        if supports_revprops:
            revprops["deb-md5"] = md5
            if native:
                revprops["deb-native"] = "True"
            if thanks:
                revprops["deb-thanks"] = "\n".join(thanks)
            if bugs:
                revprops["bugs"] = "\n".join(bugs)
        timezone = None
        if timestamp is not None:
            timezone = timestamp[1]
            timestamp = timestamp[0]
        revid = self.tree.commit(
            message, revprops=revprops, timestamp=timestamp, timezone=timezone
        )
        return self.tag_version(version, revid=revid)

    def upstream_parents(self, package: str, versions, version):
        """Get the parents for importing a new upstream.

        The upstream parents will be the last upstream version,
        except for some cases when the last version was native.

        :return: the list of revision ids to use as parents when
            importing the specified upstream version.
        """
        parents = []
        first_parent = self.pristine_upstream_branch.last_revision()
        if first_parent != NULL_REVISION:
            parents = [(first_parent, "")]
        last_contained_version = self.last_contained_version(versions)
        if last_contained_version is not None:
            # If the last version was native, and was not from the same
            # upstream as a non-native version (i.e. it wasn't a mistaken
            # native -2 version), then we want to add an extra parent.
            if self.is_version_native(
                last_contained_version
            ) and not self.pristine_upstream_source.has_version(
                package, last_contained_version.upstream_version
            ):
                revid = self.revid_of_version(last_contained_version)
                parents.append((revid, ""))
                self.pristine_upstream_branch.fetch(self.branch, revid)
        pull_parents = self.get_parents(versions)
        if (first_parent == NULL_REVISION and len(pull_parents) > 0) or len(
            pull_parents
        ) > 1:
            if first_parent == NULL_REVISION:
                pull_branch = pull_parents[0][0]
                pull_version = pull_parents[0][1]
            else:
                pull_branch = pull_parents[1][0]
                pull_version = pull_parents[1][1]
            if not pull_branch.is_version_native(pull_version):
                pull_revids = pull_branch.pristine_upstream_source.version_as_revisions(
                    package, pull_version.upstream_version
                )
                if list(pull_revids.keys()) != [None]:
                    raise MultipleUpstreamTarballsNotSupported()
                mutter(
                    "Initialising upstream from %s, version %s",
                    str(pull_branch),
                    str(pull_version),
                )
                parents.append(pull_revids[None])
                self.pristine_upstream_branch.fetch(
                    pull_branch.pristine_upstream_branch, pull_revids[None][0]
                )
                pull_branch.pristine_upstream_branch.tags.merge_to(
                    self.pristine_upstream_branch.tags
                )
        # FIXME: What about other versions ?
        return {None: parents}

    def _fetch_from_branch(self, branch, revid):
        branch.branch.tags.merge_to(self.branch.tags)
        self.branch.fetch(branch.branch, revid)
        if self.pristine_upstream_branch.last_revision() == NULL_REVISION:
            self.pristine_upstream_tree.pull(branch.pristine_upstream_branch)
            branch.pristine_upstream_branch.tags.merge_to(
                self.pristine_upstream_branch.tags
            )

    def _import_normal_package(
        self,
        package,
        version,
        versions,
        debian_part,
        md5,
        upstream_part,
        upstream_tarballs,
        timestamp=None,
        author=None,
        file_ids_from=None,
        pull_debian=True,
        force_pristine_tar=False,
    ) -> str:
        """Import a source package.

        :param package: Package name
        :param version: Full Debian version
        :param versions: Safe versions from changelog
        :param debian_part: Path to extracted directory with Debian changes
        :param unextracted_debian_md5: MD5 sum of unextracted Debian
            diff/tarball
        :param upstream_part: Extracted upstream directory
        :param upstream_tarballs:
            List of tuples with (upstream tarfile, md5sum)
        :param timestamp: Version timestamp according to changelog
        :param author: Author according to changelog
        :param file_ids_from: Sequence of trees to take file ids from
        :param pull_debian: Whether to pull from the Debian branch
        """
        pull_branch = None
        if pull_debian:
            pull_branch = self.branch_to_pull_version_from(version, md5)
        if pull_branch is not None:
            if (
                self.branch_to_pull_upstream_from(
                    package, version.upstream_version, upstream_tarballs
                )
                is None
            ):
                pull_branch = None
        if pull_branch is not None:
            return self.pull_version_from_branch(pull_branch, package, version)
        else:
            # We need to import at least the diff, possibly upstream.
            # Work out if we need the upstream part first.
            imported_upstream = False
            if not self.pristine_upstream_source.has_version(
                package, version.upstream_version
            ):
                up_pull_branch = self.branch_to_pull_upstream_from(
                    package, version.upstream_version, upstream_tarballs
                )
                if up_pull_branch is not None:
                    self.pull_upstream_from_branch(
                        up_pull_branch, package, version.upstream_version
                    )
                else:
                    imported_upstream = True
                    # Check whether we should pull first if this initialises
                    # from another branch:
                    upstream_parents = self.upstream_parents(
                        package, versions, version.upstream_version
                    )
                    imported_revids = self.import_upstream(
                        upstream_part,
                        package,
                        version.upstream_version,
                        upstream_parents,
                        upstream_tarballs=upstream_tarballs,
                        timestamp=timestamp,
                        author=author,
                        file_ids_from=file_ids_from,
                        force_pristine_tar=force_pristine_tar,
                    )
                    self._fetch_upstream_to_branch(imported_revids)
            else:
                mutter("We already have the needed upstream part")
            parents = self.get_parents_with_upstream(
                package,
                version,
                versions,
                upstream_tarballs,
                force_upstream_parent=imported_upstream,
            )
            # Now we have the list of parents we need to import the .diff.gz
            return self.import_debian(
                debian_part,
                version,
                parents,
                md5,
                timestamp=timestamp,
                file_ids_from=file_ids_from,
            )

    def get_native_parents(
        self, versions: list[Version]
    ) -> list[tuple[RevisionID, str]]:
        last_contained_version = self.last_contained_version(versions)
        if last_contained_version is None:
            parents = []
        else:
            parents = [(self.revid_of_version(last_contained_version), "")]
        missing_versions = self.missing_versions(versions)
        for branch in (
            list(reversed(self.get_lesser_branches())) + self.get_greater_branches()
        ):
            merged, missing_versions = branch.contained_versions(missing_versions)
            if merged:
                revid = branch.revid_of_version(merged[0])
                parents.append((revid, ""))
                # FIXME: should this really be here?
                self._fetch_from_branch(branch, revid)
        if (
            self.branch.last_revision() != NULL_REVISION
            and self.branch.last_revision() not in parents
        ):
            parents.insert(0, (self.branch.last_revision(), ""))
        return parents

    def _import_native_package(
        self,
        package,
        version,
        versions,
        debian_part,
        md5,
        timestamp=None,
        file_ids_from=None,
        pull_debian=True,
    ):
        pull_branch = None
        if pull_debian:
            pull_branch = self.branch_to_pull_version_from(version, md5)
        if pull_branch is not None:
            return self.pull_version_from_branch(
                pull_branch, package, version, native=True
            )
        else:
            parents = self.get_native_parents(versions)
            return self.import_debian(
                debian_part,
                version,
                parents,
                md5,
                native=True,
                timestamp=timestamp,
                file_ids_from=file_ids_from,
            )

    def import_package(
        self,
        dsc_filename: str,
        *,
        use_time_from_changelog: bool = True,
        file_ids_from: Optional[Tree] = None,
        pull_debian: bool = True,
        force_pristine_tar: bool = False,
        apply_patches: bool = False,
    ) -> str:
        """Import a source package.

        :param dsc_filename: a path to a .dsc file for the version
            to be imported.
        :param use_time_from_changelog: whether to use the current time or
            the one from the last changelog entry.
        """
        with open(dsc_filename, "rb") as f:
            dsc = deb822.Dsc(f.read())
        version = Version(dsc["Version"])
        with extract(dsc_filename, dsc, apply_patches=apply_patches) as extractor:
            cl = get_changelog_from_source(extractor.extracted_debianised)
            timestamp = None
            author = None
            if use_time_from_changelog and len(cl._blocks) > 0:
                raw_timestamp = cl.date
                import email.utils

                time_tuple = email.utils.parsedate_tz(raw_timestamp)
                if time_tuple is not None:
                    timestamp = (
                        calendar.timegm(time_tuple[:9]) - time_tuple[9],
                        time_tuple[9],
                    )
                author = cl.author
            versions = _get_safe_versions_from_changelog(cl)
            if self.has_version(version):
                raise VersionAlreadyImported(
                    version, tag_name=self.tag_of_version(version)
                )
            # TODO: check that the versions list is correctly ordered,
            # as some methods assume that, and it's not clear what
            # should happen if it isn't.

            if extractor.extracted_upstream is not None:
                return self._import_normal_package(
                    dsc["Source"],
                    version,
                    versions,
                    extractor.extracted_debianised,
                    extractor.unextracted_debian_md5,
                    extractor.extracted_upstream,
                    extractor.upstream_tarballs,
                    timestamp=timestamp,
                    author=author,
                    file_ids_from=file_ids_from,
                    pull_debian=pull_debian,
                    force_pristine_tar=force_pristine_tar,
                )
            else:
                return self._import_native_package(
                    dsc["Source"],
                    version,
                    versions,
                    extractor.extracted_debianised,
                    extractor.unextracted_debian_md5,
                    timestamp=timestamp,
                    file_ids_from=file_ids_from,
                    pull_debian=pull_debian,
                )

    def extract_upstream_tree(self, upstream_tips, basedir):
        """Extract upstream_tip to a tempdir as a working tree."""
        # TODO: should stack rather than trying to use the repository,
        # as that will be more efficient.
        to_location = os.path.join(basedir, "upstream")
        # Use upstream_branch if it has been set, otherwise self.branch.
        source_branch = self.pristine_upstream_branch or self.branch
        if list(upstream_tips.keys()) != [None]:
            raise AssertionError("Upstream tips: {!r}".format(list(upstream_tips.keys())))
        # TODO(jelmer): Use colocated branches rather than creating a copy.
        if upstream_tips[None][1]:
            raise Exception("subpaths are not yet supported")
        dir_to = source_branch.controldir.sprout(
            to_location, revision_id=upstream_tips[None][0], accelerator_tree=self.tree
        )
        try:
            self.pristine_upstream_tree = dir_to.open_workingtree()
        except NoWorkingTree:
            # Handle shared treeless repo's.
            self.pristine_upstream_tree = dir_to.create_workingtree()
        self.pristine_upstream_branch = self.pristine_upstream_tree.branch
        self.pristine_upstream_branch.get_config_stack().set("branch.fetch_tags", True)

    def create_empty_upstream_tree(self, basedir):
        to_location = os.path.join(basedir, "upstream")
        to_transport = get_transport(to_location)
        to_transport.ensure_base()
        source_branch = self.pristine_upstream_branch or self.branch
        format = source_branch.controldir._format
        try:
            existing_controldir = controldir.ControlDir.open_from_transport(
                to_transport
            )
        except NotBranchError:
            # really a NotControlDirError error...
            create_branch = controldir.ControlDir.create_branch_convenience
            branch = create_branch(
                to_transport.base, format=format, possible_transports=[to_transport]
            )
        else:
            if existing_controldir.has_branch():
                raise AlreadyBranchError(to_location)
            else:
                branch = existing_controldir.create_branch()
                existing_controldir.create_workingtree()
        self.pristine_upstream_branch = branch
        self.pristine_upstream_tree = branch.controldir.open_workingtree()
        if self.pristine_upstream_tree.supports_setting_file_ids():
            if self.tree:
                root_id = self.tree.path2id("")
            else:
                tip = self.branch.basis_tree()
                with tip.lock_read():
                    root_id = tip.path2id("")
            if root_id:
                self.pristine_upstream_tree.set_root_id(root_id)

    def _export_previous_upstream_tree(self, package, previous_version, tempdir):
        try:
            upstream_tips = self.pristine_upstream_source.version_as_revisions(
                package, previous_version
            )
        except PackageVersionNotPresent as e:
            raise PreviousVersionTagMissing(
                previous_version,
                self.pristine_upstream_source.tag_name(previous_version),
            ) from e
        self.extract_upstream_tree(upstream_tips, tempdir)

    def has_merged_upstream_revisions(
        self, this_revision, upstream_repository, upstream_revisions
    ):
        graph = self.branch.repository.get_graph(other_repository=upstream_repository)
        return all(
            graph.is_ancestor(upstream_revision, this_revision)
            for upstream_revision, upstream_subpath in upstream_revisions.values()
        )

    def merge_upstream(
        self,
        tarball_filenames,
        package,
        version,
        previous_version,
        upstream_branch=None,
        upstream_revisions=None,
        merge_type=None,
        force=False,
        force_pristine_tar=False,
        committer=None,
        files_excluded=None,
    ):
        with ExitStack() as es:
            tempdir = es.enter_context(
                tempfile.TemporaryDirectory(dir=os.path.join(self.tree.basedir, ".."))
            )
            if previous_version is not None:
                self._export_previous_upstream_tree(package, previous_version, tempdir)
            else:
                self.create_empty_upstream_tree(tempdir)
            tag = self.pristine_upstream_source.version_tag(package, version)
            if tag is not None:
                raise UpstreamAlreadyImported(version, tag)
            if upstream_branch is not None:
                es.enter_context(upstream_branch.lock_read())
            if upstream_branch is not None:
                if upstream_revisions is None:
                    upstream_revisions = {None: (upstream_branch.last_revision(), "")}
                if not force and self.has_merged_upstream_revisions(
                    self.branch.last_revision(),
                    upstream_branch.repository,
                    upstream_revisions,
                ):
                    raise UpstreamBranchAlreadyMerged
            upstream_tarballs = [
                (os.path.abspath(fn), component, md5sum_filename(fn))
                for (fn, component) in tarball_filenames
            ]
            with _extract_tarballs_to_tempdir(upstream_tarballs) as tarball_dir:
                # FIXME: should use upstream_parents()?
                parents = {None: []}
                if self.pristine_upstream_branch.last_revision() != NULL_REVISION:
                    parents = {
                        None: [(self.pristine_upstream_branch.last_revision(), "")]
                    }
                imported_revids = self.import_upstream(
                    tarball_dir,
                    package,
                    version,
                    parents,
                    upstream_tarballs=upstream_tarballs,
                    upstream_branch=upstream_branch,
                    upstream_revisions=upstream_revisions,
                    force_pristine_tar=force_pristine_tar,
                    committer=committer,
                    files_excluded=files_excluded,
                )
                self._fetch_upstream_to_branch(imported_revids)
            if self.branch.last_revision() != NULL_REVISION:
                try:
                    conflicts = self.tree.merge_from_branch(
                        self.pristine_upstream_branch, merge_type=merge_type
                    )
                except UnrelatedBranches as e:
                    # Bug lp:515367 where the first upstream tarball is
                    # missing a proper history link and a criss-cross merge
                    # then recurses and finds no deeper ancestor.
                    # Use the previous upstream import as the from revision
                    if len(parents[None]) == 0:
                        from_revision = NULL_REVISION
                        from_subpath = ""
                    else:
                        from_revision, from_subpath = parents[None][0]
                    if from_subpath:
                        raise Exception("subpath not yet supported") from e
                    conflicts = self.tree.merge_from_branch(
                        self.pristine_upstream_branch,
                        merge_type=merge_type,
                        from_revision=from_revision,
                    )
                if not isinstance(conflicts, list):
                    conflicts = self.tree.conflicts()
            else:
                # Pull so that merge-upstream allows you to start a branch
                # from upstream tarball.
                conflicts = []
                self.tree.pull(self.pristine_upstream_branch)
            self.pristine_upstream_branch.tags.merge_to(self.branch.tags)
            return conflicts, imported_revids


@contextmanager
def _extract_tarballs_to_tempdir(tarballs):
    with tempfile.TemporaryDirectory() as tempdir:
        for tarball_filename, component, _md5 in tarballs:
            try:
                extract_orig_tarball(tarball_filename, component, tempdir)
            except tarfile.ReadError as e:
                raise CorruptUpstreamSourceFile(tarball_filename, str(e)) from e
        yield tempdir


def _get_safe_versions_from_changelog(cl):
    versions = []
    for block in cl._blocks:
        try:
            versions.append(block.version)
        except VersionError:
            break
    return versions


def get_changelog_from_source(dir, max_blocks=None):
    cl_filename = os.path.join(dir, "debian", "changelog")
    with open(cl_filename, "rb") as f:
        content = f.read()
    content = content.decode("utf-8", "surrogateescape")
    cl = Changelog()
    cl.parse_changelog(content, strict=False, max_blocks=max_blocks)
    return cl


def _default_config_for_tree(tree):
    # FIXME: shouldn't go to configobj directly
    for path in ("debian/bzr-builddeb.conf", ".bzr-builddeb/default.conf"):
        fileid = tree.path2id(path)
        if fileid is not None:
            break
    else:
        return None, None, None
    with tree.lock_read():
        config = ConfigObj(tree.get_file(path))
        try:
            config["BUILDDEB"]
        except KeyError:
            config["BUILDDEB"] = {}
    return fileid, path, config


def mangle_version(branch: Branch, version: Version) -> str:
    git = getattr(branch.repository, "_git", None)
    if git:
        return mangle_version_for_git(version)
    return str(version)


def branch_has_debian_version(branch, tag_name, md5=None):
    if not branch.tags.has_tag(tag_name):
        return False
    revid = branch.tags.lookup_tag(tag_name)
    with branch.lock_read():
        graph = branch.repository.get_graph()
        if not graph.is_ancestor(revid, branch.last_revision()):
            return False
    if md5 is None:
        return True
    rev = branch.repository.get_revision(revid)
    # TODO(jelmer): Check the commit message for git repositories
    try:
        return rev.properties["deb-md5"] == md5
    except KeyError:
        warning(
            "tag {} present in branch, but there is no "
            "associated 'deb-md5' property".format(tag_name)
        )
        return False
