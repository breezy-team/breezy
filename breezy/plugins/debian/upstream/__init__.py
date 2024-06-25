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
import re
import shutil
import tarfile
import tempfile
from typing import Optional

from debmutate.versions import debianize_upstream_version

from .... import osutils
from ....errors import BzrError, DependencyNotPresent
from ....revision import RevisionID
from ....trace import (
    note,
    warning,
)
from ..repack_tarball import (
    get_filetype,
    repack_tarball,
)
from ..util import (
    component_from_orig_tarball,
    export_with_nested,
    tarball_name,
)


class PackageVersionNotPresent(BzrError):
    _fmt = "%(package)s %(version)s was not found in %(upstream)s."

    def __init__(self, package, version, upstream):
        BzrError.__init__(self, package=package, version=version, upstream=upstream)


class MissingUpstreamTarball(BzrError):
    _fmt = (
        "Unable to find the needed upstream tarball for package "
        "%(package)s, version %(version)s."
    )

    def __init__(self, package, version):
        BzrError.__init__(self, package=package, version=version)


def new_tarball_name(package, version, old_name):
    """Determine new tarball name based on the package name and the old name."""
    if package is None:
        if "-" in old_name:
            package = old_name.split("-")[0]
        elif "_" in old_name:
            package = old_name.split("_")[0]
        else:
            raise ValueError(old_name)
    old_format = get_filetype(old_name)
    if old_format in ("gz", "bz2", "xz"):
        return tarball_name(package, version, None, old_format)
    # Unknown target format, repack to .tar.gz
    return tarball_name(package, version, None, "gz")


class UpstreamSource:
    """A source for upstream versions (uscan, debian/rules, etc)."""

    def get_latest_version(self, package: str, current_version: str):
        """Check what the latest upstream version is.

        Args:
          package: Name of the package
          version: The current upstream version of the package.

        Returns:
          Tuple with the version string of the latest available upstream
          version, and mangled Debian version.
        """
        raise NotImplementedError(self.get_latest_version)

    def get_recent_versions(self, package: str, since_version: Optional[str] = None):
        """Retrieve recent version strings.

        :param package: Name of the package
        :param version: Last upstream version since which to retrieve versions
        :return: Iterator over (version, mangled version) tuples
        """
        raise NotImplementedError(self.get_recent_versions)

    def version_as_revisions(
        self, package: str, version: str, tarballs=None
    ) -> dict[Optional[str], tuple[RevisionID, str]]:
        """Lookup the revision ids for a particular version.

        :param package: Package name
        :param version: Version string
        :raise PackageVersionNotPresent: When the specified version was not
            found
        :return: dictionary mapping component names to revision ids
        """
        raise NotImplementedError(self.version_as_revisions)

    def has_version(self, package: str, version: str, tarballs=None):
        """Check whether this upstream source contains a particular package.

        :param package: Package name
        :param version: Version string
        :param tarballs: Tarballs list
        """
        raise NotImplementedError(self.has_version)

    def fetch_tarballs(
        self, package: str, version: str, target_dir: str, components=None
    ):
        """Fetch the source tarball for a particular version.

        :param package: Name of the package
        :param version: Version string of the version to fetch
        :param target_dir: Directory in which to store the tarball
        :param components: List of component names to fetch; may be None,
            in which case the backend will have to find out.
        :return: Paths of the fetched tarballs
        """
        raise NotImplementedError(self.fetch_tarballs)

    def _tarball_path(self, package, version, component, target_dir, format=None):
        return os.path.join(
            target_dir, tarball_name(package, version, component, format=format)
        )


class AptSource(UpstreamSource):
    """Upstream source that uses apt-source."""

    def __init__(self, apt=None):
        if apt is None:
            from ..apt_repo import LocalApt

            apt = LocalApt()
        self.apt = apt

    def fetch_tarballs(self, package, upstream_version, target_dir, components=None):
        with self.apt:
            from ..apt_repo import AptSourceError, NoAptSources

            source_name = package
            try:
                for source in self.apt.iter_source_by_name(package):
                    filenames = []
                    for entry in source["Files"]:
                        filename = os.path.basename(entry["name"])
                        if filename.startswith(f"{package}_{upstream_version}.orig"):
                            filenames.append(filename)
                    if filenames:
                        source_version = source["Version"]
                        break
                else:
                    note(
                        "%r could not find %s/%s.", self.apt, package, upstream_version
                    )
                    raise PackageVersionNotPresent(package, upstream_version, self)
            except NoAptSources as e:
                note("No apt sources configured, skipping")
                # Handle the case where the apt.sources file contains no source
                # URIs (LP:375897)
                raise PackageVersionNotPresent(package, upstream_version, self) from e
            note("Using apt to look for the upstream tarball.")
            try:
                self.apt.retrieve_source(
                    source_name, target_dir, source_version, tar_only=True
                )
            except AptSourceError as e:
                note("apt found %s/%s but could not download.", package, source_version)
                raise PackageVersionNotPresent(package, upstream_version, self) from e
            return [os.path.join(target_dir, filename) for filename in filenames]


class SelfSplitSource(UpstreamSource):
    def __init__(self, tree):
        self.tree = tree

    def _split(self, package, upstream_version, target_filename):
        with tempfile.TemporaryDirectory(prefix="builddeb-get-orig-source-") as tmpdir:
            export_dir = os.path.join(tmpdir, f"{package}-{upstream_version}")
            export_with_nested(self.tree, export_dir, format="dir")
            shutil.rmtree(os.path.join(export_dir, "debian"))
            with tarfile.open(target_filename, "w:gz") as tar:
                tar.add(export_dir, f"{package}-{upstream_version}")

    def fetch_tarballs(self, package, version, target_dir, components=None):
        note(
            "Using the current branch without the 'debian' directory "
            "to create the tarball"
        )
        tarball_path = self._tarball_path(package, version, None, target_dir)
        self._split(package, version, tarball_path)
        return [tarball_path]


class StackedUpstreamSource(UpstreamSource):
    """An upstream source that checks a list of other upstream sources.

    The first source that can provide a tarball, wins.
    """

    def __init__(self, sources):
        self._sources = sources

    def __repr__(self):
        return f"{self.__class__.__name__}({self._sources!r})"

    def fetch_tarballs(self, package, version, target_dir, components=None):
        for source in self._sources:
            try:
                paths = source.fetch_tarballs(package, version, target_dir, components)
            except PackageVersionNotPresent:
                pass
            except DependencyNotPresent as e:
                warning("not checking %r due to missing dependency: %s", source, e)
            else:
                return paths
        raise PackageVersionNotPresent(package, version, self)

    def get_latest_version(self, package, version):
        for source in self._sources:
            try:
                new_version = source.get_latest_version(package, version)
                if new_version is not None:
                    return new_version
            except NotImplementedError:
                pass
        return None, None

    def get_recent_versions(self, package, since_version=None):
        versions = {}
        for source in self._sources:
            for unmangled, mangled in source.get_recent_versions(
                package, since_version
            ):
                versions[mangled] = unmangled
        # TODO(jelmer): Perhaps there are better ways of comparing arbitrary
        # upstream versions?
        from debian.changelog import Version

        return [
            (u, m) for (m, u) in sorted(versions.items(), key=lambda v: Version(v[0]))
        ]

    def version_as_revisions(self, package, version, tarballs=None):
        for source in self._sources:
            try:
                return source.version_as_revisions(package, version, tarballs)
            except PackageVersionNotPresent:
                pass
            except DependencyNotPresent as e:
                warning("not checking %r due to missing dependency: %s", source, e)
        raise PackageVersionNotPresent(package, version, self)

    def has_version(self, package: str, version: str, tarballs=None) -> bool:
        for source in self._sources:
            if source.has_version(package, version, tarballs):
                return True
        return False


def gather_orig_files(package, version, path):
    """Grab the orig files for a particular package.

    :param package: package name
    :param version: package upstream version string
    :return: List of orig tarfile paths, or None if none were found
    """
    prefix = f"{package}_{version}.orig"
    ret = []
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        return None
    if isinstance(path, bytes):
        prefix = prefix.encode(osutils._fs_enc)
    for filename in os.listdir(path):
        if filename.endswith(".asc"):
            continue
        if filename.startswith(prefix):
            ret.append(os.path.join(path, filename))
    if ret:
        return ret
    return None


class UpstreamProvider:
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
        self.version = version
        self.store_dir = os.path.abspath(store_dir)
        self.source = StackedUpstreamSource(sources)

    def provide(self, target_dir):
        """Provide the upstream tarball(s) any way possible.

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
           - Else a call will be made to debian/rules to try and retrieve
             the tarball.

        If the tarball can't be found at all then MissingUpstreamTarball
        will be raised.

        :param target_dir: The directory to place the tarball in.
        :return: The path to the tarball.
        """
        note("Looking for a way to retrieve the upstream tarball")
        in_target = self.already_exists_in_target(target_dir)
        if in_target is not None:
            note("Upstream tarball already exists in build directory, " "using that")
            return [
                (p, component_from_orig_tarball(p, self.package, self.version))
                for p in in_target
            ]
        if self.already_exists_in_store() is None:
            if not os.path.exists(self.store_dir):
                os.makedirs(self.store_dir)
            try:
                paths = self.source.fetch_tarballs(
                    self.package, self.version, self.store_dir
                )
            except PackageVersionNotPresent as e:
                raise MissingUpstreamTarball(self.package, self.version) from e
        else:
            note("Using the upstream tarball that is present in {}".format(self.store_dir))
        paths = self.provide_from_store_dir(target_dir)
        return [
            (p, component_from_orig_tarball(p, self.package, self.version))
            for p in paths
        ]

    def already_exists_in_target(self, target_dir):
        return gather_orig_files(self.package, self.version, target_dir)

    def already_exists_in_store(self):
        return gather_orig_files(self.package, self.version, self.store_dir)

    def provide_from_store_dir(self, target_dir):
        paths = self.already_exists_in_store()
        if paths is None:
            return None
        for path in paths:
            repack_tarball(path, os.path.basename(path), target_dir=target_dir)
        return paths


def extract_tarball_version(path, packagename):
    """Extract a version from a tarball path.

    :param path: Path to the tarball (e.g. "/tmp/bzr-builddeb-2.7.3.tar.gz")
    :param packagename: Name of the package (e.g. "bzr-builddeb")
    """
    basename = os.path.basename(path)
    for extension in [".tar.gz", ".tgz", ".tar.bz2", ".tar.lzma", ".tar.xz", ".zip"]:
        if basename.endswith(extension):
            basename = basename[: -len(extension)]
            break
    else:
        # Unknown extension
        return None
    # Debian style tarball
    m = re.match(packagename + "_(.*).orig", basename)
    if m:
        return m.group(1)
    # Traditional, PACKAGE-VERSION.tar.gz
    m = re.match(packagename + "-(.*)", basename)
    if m:
        return m.group(1)
    return None


class TarfileSource(UpstreamSource):
    """Source that uses a single local tarball."""

    def __init__(self, path, version=None):
        self.path = path
        if version is not None:
            self.version = str(version)
        else:
            self.version = None

    def fetch_tarballs(self, package, version, target_dir, components=None):
        if version != self.version:
            raise PackageVersionNotPresent(package, version, self)
        dest_name = new_tarball_name(package, version, self.path)
        repack_tarball(self.path, dest_name, target_dir=target_dir)
        return [os.path.join(target_dir, dest_name)]

    def get_recent_versions(self, package, since_version=None):
        latest_version = self.get_latest_version(package, since_version)
        if latest_version is None:
            return []
        return [latest_version]

    def get_latest_version(self, package, version):
        if self.version is not None:
            return (self.version, self.version)
        self.version = extract_tarball_version(self.path, package)
        return (self.version, self.version)


class LaunchpadReleaseFileSource(UpstreamSource):
    """Source that retrieves release files from Launchpad."""

    @classmethod
    def from_package(cls, distribution_name, distroseries_name, package):
        """Create a LaunchpadReleaseFileSource from a distribution package.

        :param distribution_name: Name of the distribution (e.g. "Ubuntu")
        :param distroseries_name: Name of the distribution series
            (e.g. "oneiric")
        :param package: Package name
        :return: A `LaunchpadReleaseFileSource`
        """
        from ...launchpad import (
            get_upstream_projectseries_for_package,
        )

        project_series = get_upstream_projectseries_for_package(
            package, distribution_name, distroseries_name
        )
        if project_series is None:
            return None
        return cls(project_series=project_series)

    def __init__(self, project=None, project_series=None):
        if project_series is None:
            self.project_series = project.development_focus
        else:
            self.project_series = project_series
        if project is None:
            self.project = project_series.project
        else:
            self.project = project

    def fetch_tarballs(self, package, version, target_dir, components=None):
        note("Retrieving tarball for %s from Launchpad.", package)
        release = self.project.getRelease(version=version)
        if release is None:
            raise PackageVersionNotPresent(package, version, self)
        release_files = []
        for f in release.files:
            if f.file_type == "Code Release Tarball":
                release_files.append(f.file)
        if len(release_files) == 0:
            warning(
                "Release %s for package %s found on Launchpad but no "
                "associated tarballs.",
                version,
                package,
            )
            raise PackageVersionNotPresent(package, version, self)
        elif len(release_files) > 1:
            warning(
                "More than one release file for release %s of package %s"
                "found on Launchpad. Using the first.",
                version,
                package,
            )
        hosted_file = release_files[0]
        with tempfile.TemporaryDirectory(prefix="builddeb-launchpad-source-") as tmpdir:
            with hosted_file.open() as inf:
                note("Downloading upstream tarball %s from Launchpad", inf.filename)
                filename = inf.filename.encode(osutils._fs_enc)
                filename = filename.replace("/", "")
                tmppath = os.path.join(tmpdir, filename)
                with open(tmppath, "wb") as outf:
                    outf.write(inf.read())
            dest_name = new_tarball_name(package, version, filename)
            repack_tarball(tmppath, dest_name, target_dir=target_dir)
            return os.path.join(target_dir, dest_name)

    def _all_versions(self):
        for release in self.project_series.releases:
            yield (release.date_released, release.version)

    def get_recent_versions(self, package, since_version=None):
        versions = []
        for unmangled, mangled in self._all_versions():
            if since_version is None or since_version < mangled:
                versions.append((unmangled, mangled))
        return sorted(versions)

    def get_latest_version(self, package, version):
        versions = list(self._all_versions())
        versions.sort()
        return (versions[-1][1], debianize_upstream_version(versions[-1][1], package))


class DirectoryScanSource(UpstreamSource):
    """Source that scans a local directory for sources."""

    def __init__(self, path):
        self.path = os.path.abspath(path)

    def fetch_tarballs(self, package: str, version: str, target_dir, components=None):
        prefix = f"{package}_{version}.orig"
        ret = []
        for entry in os.scandir(self.path):
            if entry.name.startswith(prefix):
                component = entry.name[len(prefix) :].split(".")[0] or None
                shutil.copy(entry.path, target_dir)
                if components is None or component in components:
                    ret.append(os.path.join(target_dir, entry.name))
        if ret:
            return ret
        raise PackageVersionNotPresent(package, version, self)

    def get_recent_versions(self, package, since_version=None):
        return []

    def get_latest_version(self, package, version):
        return None, None
