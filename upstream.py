#    upstream.py -- Providers of upstream source
#    Copyright (C) 2009 Canonical Ltd.
#    Copyright (C) 2009 Jelmer Vernooij <jelmer@debian.org>
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

import os
import shutil
import subprocess
import tarfile
import tempfile

from debian_bundle.changelog import Version

from bzrlib.export import export
from bzrlib.revisionspec import RevisionSpec
from bzrlib.trace import note

from bzrlib.plugins.builddeb.errors import (
    MissingUpstreamTarball,
    PackageVersionNotPresent,
    PristineTarError,
    )
from bzrlib.plugins.builddeb.import_dsc import DistributionBranch
from bzrlib.plugins.builddeb.repack_tarball import repack_tarball
from bzrlib.plugins.builddeb.util import (
    get_snapshot_revision,
    tarball_name,
    )


class UpstreamSource(object):
    """A source for upstream versions (uscan, get-orig-source, etc)."""

    def get_latest_version(self, package, version, target_dir):
        """Fetch the source tarball for the latest available version.

        :param package: Name of the package
        :param version: The current version of the package.
        :param target_dir: Directory in which to store the tarball
        :return: The version number of the new version, or None if no newer
                version is available.
        """
        raise NotImplementedError(self.get_latest_version)

    def get_specific_version(self, package, version, target_dir):
        """Fetch the source tarball for a particular version.

        :param package: Name of the package
        :param version: Version string of the version to fetch
        :param target_dir: Directory in which to store the tarball
        """
        raise NotImplementedError(self.get_specific_version)

    def _tarball_path(self, package, version, target_dir):
        return os.path.join(target_dir, tarball_name(package, version))


class PristineTarSource(UpstreamSource):
    """Source that uses the pristine-tar revisions in the packaging branch."""

    def __init__(self, tree, branch):
        self.branch = branch
        self.tree = tree

    def get_specific_version(self, package, version, target_dir):
        target_filename = self._tarball_path(package, version,
                                             target_dir)
        db = DistributionBranch(self.branch, None, tree=self.tree)
        if not db.has_upstream_version_in_packaging_branch(version):
            raise PackageVersionNotPresent(package, version, self)
        revid = db.revid_of_upstream_version_from_branch(version)
        if not db.has_pristine_tar_delta(revid):
            raise PackageVersionNotPresent(package, version, self)
        note("Using pristine-tar to reconstruct the needed tarball.")
        try:
            db.reconstruct_pristine_tar(revid, package, version, target_filename)
        except PristineTarError:
            raise PackageVersionNotPresent(package, version, self)


class AptSource(UpstreamSource):
    """Upstream source that uses apt-source."""

    def get_specific_version(self, package, upstream_version, target_dir, 
            _apt_pkg=None):
        if _apt_pkg is None:
            import apt_pkg
        else:
            apt_pkg = _apt_pkg
        apt_pkg.init()

        # Handle the case where the apt.sources file contains no source
        # URIs (LP:375897)
        try:
            sources = apt_pkg.GetPkgSrcRecords()
        except SystemError:
            raise PackageVersionNotPresent(package, upstream_version, self)

        sources.Restart()
        note("Using apt to look for the upstream tarball.")
        while sources.Lookup(package):
            if upstream_version \
                == Version(sources.Version).upstream_version:
                if self._run_apt_source(package, sources.Version, target_dir):
                    return
                break
        note("apt could not find the needed tarball.")
        raise PackageVersionNotPresent(package, upstream_version, self)

    def _get_command(self, package, version_str):
        return 'apt-get source -y --only-source --tar-only %s=%s' % \
            (package, version_str)

    def _run_apt_source(self, package, version_str, target_dir):
        command = self._get_command(package, version_str)
        proc = subprocess.Popen(command, shell=True, cwd=target_dir)
        proc.wait()
        if proc.returncode != 0:
            return False
        return True


class UpstreamBranchSource(UpstreamSource):
    """Upstream source that uses the upstream branch."""

    def __init__(self, upstream_branch, upstream_revision=None, 
                 fallback_revspec=None):
        self.upstream_branch = upstream_branch
        self.upstream_revision = upstream_revision
        self.fallback_revspec = fallback_revspec

    def _get_revision_id(self, version):
        if self.upstream_revision is not None:
            # Explicit revision id to use set
            return self.upstream_revision
        revspec = get_snapshot_revision(version)
        if revspec is None:
            revspec = self.fallback_revspec
        if revspec is not None:
            return RevisionSpec.from_string(
                revspec).as_revision_id(self.upstream_branch)
        return self.upstream_branch.last_revision()

    def get_specific_version(self, package, version, target_dir):
        self.upstream_branch.lock_read()
        try:
            revid = self._get_revision_id(version)
            note("Exporting upstream branch revision %s to create the tarball",
                 revid)
            target_filename = self._tarball_path(package, version, target_dir)
            tarball_base = "%s-%s" % (package, version)
            rev_tree = self.upstream_branch.repository.revision_tree(revid)
            export(rev_tree, target_filename, 'tgz', tarball_base)
        finally:
            self.upstream_branch.unlock()


class GetOrigSourceSource(UpstreamSource):
    """Upstream source that uses the get-orig-source rule in debian/rules."""

    def __init__(self, tree, larstiq):
        self.tree = tree
        self.larstiq = larstiq

    def _get_orig_source(self, source_dir, desired_tarball_name,
                        target_dir):
        note("Trying to use get-orig-source to retrieve needed tarball.")
        command = ["make", "-f", "debian/rules", "get-orig-source"]
        proc = subprocess.Popen(command, cwd=source_dir)
        ret = proc.wait()
        if ret != 0:
            note("Trying to run get-orig-source rule failed")
            return False
        fetched_tarball = os.path.join(source_dir, desired_tarball_name)
        if not os.path.exists(fetched_tarball):
            note("get-orig-source did not create %s", desired_tarball_name)
            return False
        repack_tarball(fetched_tarball, desired_tarball_name, 
                       target_dir=target_dir)
        return True

    def get_specific_version(self, package, version, target_dir):
        if self.larstiq:
            rules_name = 'rules'
        else:
            rules_name = 'debian/rules'
        rules_id = self.tree.path2id(rules_name)
        if rules_id is not None:
            desired_tarball_name = tarball_name(package, version)
            tmpdir = tempfile.mkdtemp(prefix="builddeb-get-orig-source-")
            try:
                base_export_dir = os.path.join(tmpdir, "export")
                export_dir = base_export_dir
                if self.larstiq:
                    os.mkdir(export_dir)
                    export_dir = os.path.join(export_dir, "debian")
                export(self.tree, export_dir, format="dir")
                if not self._get_orig_source(base_export_dir,
                        desired_tarball_name, target_dir):
                    raise PackageVersionNotPresent(package, version, self)
                return
            finally:
                shutil.rmtree(tmpdir)
        note("No debian/rules file to try and use for a get-orig-source rule")
        raise PackageVersionNotPresent(package, version, self)


class UScanSource(UpstreamSource):
    """Upstream source that uses uscan."""

    def __init__(self, tree, larstiq):
        self.tree = tree
        self.larstiq = larstiq

    def _uscan(self, package, upstream_version, watch_file, target_dir):
        note("Using uscan to look for the upstream tarball.")
        r = os.system("uscan --upstream-version %s --force-download --rename "
                      "--package %s --watchfile %s --check-dirname-level 0 " 
                      "--download --repack --destdir %s --download-version %s" %
                      (upstream_version, package, watch_file, target_dir,
                       upstream_version))
        if r != 0:
            note("uscan could not find the needed tarball.")
            return False
        return True

    def _export_watchfile(self):
        if self.larstiq:
            watchfile = 'watch'
        else:
            watchfile = 'debian/watch'
        watch_id = self.tree.path2id(watchfile)
        if watch_id is None:
            note("No watch file to use to retrieve upstream tarball.")
            return None
        (tmp, tempfilename) = tempfile.mkstemp()
        try:
            tmp = os.fdopen(tmp, 'wb')
            watch = self.tree.get_file_text(watch_id)
            tmp.write(watch)
        finally:
            tmp.close()
        return tempfilename

    def get_specific_version(self, package, version, target_dir):
        tempfilename = self._export_watchfile()
        if tempfilename is None:
            raise PackageVersionNotPresent(package, version, self)
        try:
            if not self._uscan(package, version, tempfilename, 
                    target_dir):
                raise PackageVersionNotPresent(package, version, self)
        finally:
            os.unlink(tempfilename)

    def get_latest_version(self, package, version, target_dir):
        pass


class SelfSplitSource(UpstreamSource):

    def __init__(self, tree):
        self.tree = tree

    def _split(self, package, upstream_version, target_filename):
        tmpdir = tempfile.mkdtemp(prefix="builddeb-get-orig-source-")
        try:
            export_dir = os.path.join(tmpdir,
                    "%s-%s" % (package, upstream_version))
            export(self.tree, export_dir, format="dir")
            shutil.rmtree(os.path.join(export_dir, "debian"))
            tar = tarfile.open(target_filename, "w:gz")
            try:
                tar.add(export_dir, "%s-%s" % (package, upstream_version))
            finally:
                tar.close()
        finally:
            shutil.rmtree(tmpdir)

    def get_specific_version(self, package, version, target_dir):
        note("Using the current branch without the 'debian' directory "
                "to create the tarball")
        self._split(package, version, 
                    self._tarball_path(package, version, target_dir))


class StackedUpstreamSource(UpstreamSource):
    """An upstream source that checks a list of other upstream sources.
    
    The first source that can provide a tarball, wins. 
    """

    def __init__(self, sources):
        self._sources = sources

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self._sources)

    def get_specific_version(self, package, version, target_dir):
        for source in self._sources:
            try:
                return source.get_specific_version(package, version, target_dir)
            except PackageVersionNotPresent:
                pass
        raise PackageVersionNotPresent(package, version, self)

    def get_latest_version(self, package, version, target_dir):
        for source in self._sources:
            try:
                new_version = source.get_latest_version(package, version, target_dir)
                if new_version is not None:
                    return new_version
            except NotImplementedError:
                pass
        return None


def get_upstream_sources(tree, branch, larstiq=False, upstream_branch=None,
                         upstream_revision=None, allow_split=False):
    """Get the list of upstream sources to retrieve upstream versions from.

    :param tree: The tree that is being built from.
    :param branch: The branch that is being built from.
    :param larstiq: Whether the tree versions the root of ./debian.
    :param upstream_branch: An upstream branch that can be exported
        if needed.
    :param upstream_revision: The revision to use of the upstream branch
        if it is used.
    :param allow_split: Whether the provider can provide the tarball
        by exporting the branch and removing the "debian" dir.

    """
    sources = [
        PristineTarSource(tree, branch), 
        AptSource(),
        ]
    if upstream_branch is not None:
        sources.append(
            UpstreamBranchSource(upstream_branch, upstream_revision))
    sources.extend([
        GetOrigSourceSource(tree, larstiq), 
        UScanSource(tree, larstiq),
        ])
    if allow_split:
        sources.append(SelfSplitSource(tree))
    return sources


class UpstreamProvider(object):
    """An upstream provider can provide the upstream source for a package.

    Different implementations can provide it in different ways, for
    instance using pristine-tar, or using apt.
    """

    def __init__(self, package, version, store_dir, sources):
        """Create an UpstreamProvider.

        :param package: the name of the source package that is being built.
        :param version: the Version of the package that is being built.
        :param store_dir: A directory to cache the tarballs.
        """
        self.package = package
        self.version = Version(version)
        self.store_dir = store_dir
        self.source = StackedUpstreamSource(sources)

    def provide(self, target_dir):
        """Provide the upstream tarball any way possible.

        Call this to place the correctly named tarball in to target_dir,
        through means possible.

        If the tarball is already there then do nothing.
        If it is in self.store_dir then copy it over.
        Else retrive it and cache it in self.store_dir, then copy it over:
           - If pristine-tar metadata is available then that will be used.
           - Else if apt knows about a source of that version that will be
             retrieved.
           - Else if uscan knows about that version it will be downloaded
             and repacked as needed.
           - Else a call will be made to get-orig-source to try and retrieve
             the tarball.

        If the tarball can't be found at all then MissingUpstreamTarball
        will be raised.

        :param target_dir: The directory to place the tarball in.
        :return: The path to the tarball.
        """
        note("Looking for a way to retrieve the upstream tarball")
        if self.already_exists_in_target(target_dir):
            note("Upstream tarball already exists in build directory, "
                    "using that")
            return os.path.join(target_dir, self._tarball_name())
        if not self.already_exists_in_store():
            if not os.path.exists(self.store_dir):
                os.makedirs(self.store_dir)
            try:
                self.source.get_specific_version(self.package, 
                    self.version.upstream_version, self.store_dir)
            except PackageVersionNotPresent:
                raise MissingUpstreamTarball(self._tarball_name())
        else:
             note("Using the upstream tarball that is present in "
                     "%s" % self.store_dir)
        assert self.provide_from_store_dir(target_dir)
        return os.path.join(target_dir, self._tarball_name())

    def already_exists_in_target(self, target_dir):
        return os.path.exists(os.path.join(target_dir, self._tarball_name()))

    def already_exists_in_store(self):
        return os.path.exists(os.path.join(self.store_dir,
                    self._tarball_name()))

    def provide_from_store_dir(self, target_dir):
        if self.already_exists_in_store():
            repack_tarball(os.path.join(self.store_dir, self._tarball_name()),
                    self._tarball_name(), target_dir=target_dir)
            return True
        return False

    def _tarball_name(self):
        return tarball_name(self.package, self.version.upstream_version)


class _MissingUpstreamProvider(UpstreamProvider):
    """For tests"""

    def __init__(self):
        pass

    def provide(self, target_dir):
        raise MissingUpstreamTarball("test_tarball")


class _TouchUpstreamProvider(UpstreamProvider):
    """For tests"""

    def __init__(self, desired_tarball_name):
        self.desired_tarball_name = desired_tarball_name

    def provide(self, target_dir):
        f = open(os.path.join(target_dir, self.desired_tarball_name), "wb")
        f.write("I am a tarball, honest\n")
        f.close()


class _SimpleUpstreamProvider(UpstreamProvider):
    """For tests"""

    def __init__(self, package, version, store_dir):
        self.package = package
        self.version = Version(version)
        self.store_dir = store_dir

    def provide(self, target_dir):
        if self.already_exists_in_target(target_dir) \
            or self.provide_from_store_dir(target_dir):
            return os.path.join(target_dir, self._tarball_name())
        raise MissingUpstreamTarball(self._tarball_name())
