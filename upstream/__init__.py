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
import subprocess
import tarfile
import tempfile

from debian.changelog import Version

from .... import osutils
from ....export import export
from ....trace import (
    note,
    warning,
    )

from ..errors import (
    MissingUpstreamTarball,
    PackageVersionNotPresent,
    WatchFileMissing,
    )
from ..repack_tarball import (
    get_filetype,
    repack_tarball,
    )
from ..util import (
    component_from_orig_tarball,
    tarball_name,
    )


def new_tarball_name(package, version, old_name):
    """Determine new tarball name based on the package name and the old name.
    """
    old_format = get_filetype(old_name)
    if old_format in ("gz", "bz2", "xz"):
        return tarball_name(package, version, None, old_format)
    # Unknown target format, repack to .tar.gz
    return tarball_name(package, version, None, "gz")


class UpstreamSource(object):
    """A source for upstream versions (uscan, debian/rules, etc)."""

    def get_latest_version(self, package, current_version):
        """Check what the latest upstream version is.

        :param package: Name of the package
        :param version: The current upstream version of the package.
        :return: The version string of the latest available upstream version.
        """
        raise NotImplementedError(self.get_latest_version)

    def version_as_revisions(self, package, version, tarballs=None):
        """Lookup the revision ids for a particular version.

        :param package: Package name
        :param version: Version string
        :raise PackageVersionNotPresent: When the specified version was not
            found
        :return: dictionary mapping component names to revision ids
        """
        raise NotImplementedError(self.version_as_revisions)

    def has_version(self, package, version, tarballs=None):
        """Check whether this upstream source contains a particular package.

        :param package: Package name
        :param version: Version string
        :param tarballs: Tarballs list
        """
        raise NotImplementedError(self.has_version)

    def fetch_tarballs(self, package, version, target_dir, components=None):
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
        return os.path.join(target_dir, tarball_name(package, version, component,
                    format=format))


class AptSource(UpstreamSource):
    """Upstream source that uses apt-source."""

    def fetch_tarballs(self, package, upstream_version, target_dir,
            _apt_pkg=None, components=None):
        if _apt_pkg is None:
            import apt_pkg
        else:
            apt_pkg = _apt_pkg
        apt_pkg.init()

        def get_fn(obj, new_name, old_name):
            try:
                return getattr(obj, new_name)
            except AttributeError:
                return getattr(obj, old_name)

        # Handle the case where the apt.sources file contains no source
        # URIs (LP:375897)
        try:
            get_sources = get_fn(apt_pkg, 'SourceRecords',
                "GetPkgSrcRecords")
            sources = get_sources()
        except SystemError:
            raise PackageVersionNotPresent(package, upstream_version, self)

        restart = get_fn(sources, 'restart', 'Restart')
        restart()
        note("Using apt to look for the upstream tarball.")
        lookup = get_fn(sources, 'lookup', 'Lookup')
        while lookup(package):
            version = get_fn(sources, 'version', 'Version')
            filenames = []
            for (checksum, size, filename, filekind) in sources.files:
                if filekind != "tar":
                    continue
                filename = os.path.basename(filename)
                if filename.startswith("%s_%s.orig" % (package, upstream_version)):
                    filenames.append(filename)
            if filenames:
                if self._run_apt_source(package, version, target_dir):
                    return [os.path.join(target_dir, filename)
                            for filename in filenames]
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


class DebianRulesSource(UpstreamSource):
    """Upstream source that uses rules in debian/rules."""

    def __init__(self, tree, top_level):
        self.tree = tree
        self.top_level = top_level

    def _get_rule_source(self, source_dir, rule, make_vars=None):
        command = ["make", "-f", "debian/rules", rule]
        if make_vars is not None:
            command.extend(["%s=%s" % item for item in make_vars.iteritems()])

        proc = subprocess.Popen(command, cwd=source_dir)
        ret = proc.wait()
        if ret != 0:
            note("Trying to run %s rule failed" % rule)
            return False
        return True

    def _get_current_source(self, source_dir, package, version, target_dir):
        rule = "get-packaged-orig-source"
        note("Trying to use %s to retrieve needed tarball." % rule)
        if not self._get_rule_source(source_dir, rule, {
                "ORIG_VERSION": version,
                "ORIG_PACKAGE": package}):
            rule = "get-orig-source"
            note("Trying to use %s to retrieve needed tarball (deprecated)." % rule)
            if not self._get_rule_source(source_dir, rule):
                return None
        filenames = gather_orig_files(package, version, source_dir)
        if not filenames:
            note("%s did not create file for %s version %s", rule, package, version)
            return None
        if rule == "get-orig-source":
            warning("Using get-orig-source to retrieve the packaged orig tarball "
                    "is deprecated (see debian policy section 4.9). Provide the "
                    "'get-packaged-orig-source' target instead.")
        ret = []
        for filename in filenames:
            repack_tarball(
                filename, os.path.basename(filename), target_dir=target_dir)
            ret.append(os.path.join(target_dir, os.path.basename(filename)))
        return ret

    def _get_rules_id(self):
        if self.top_level:
            rules_name = 'rules'
        else:
            rules_name = 'debian/rules'
        return self.tree.path2id(rules_name)

    def fetch_tarballs(self, package, version, target_dir, components=None):
        rules_id = self._get_rules_id()
        if rules_id is None:
            note("No debian/rules file to use to retrieve upstream tarball.")
            raise PackageVersionNotPresent(package, version, self)
        tmpdir = tempfile.mkdtemp(prefix="builddeb-get-source-")
        try:
            base_export_dir = os.path.join(tmpdir, "export")
            export_dir = base_export_dir
            if self.top_level:
                os.mkdir(export_dir)
                export_dir = os.path.join(export_dir, "debian")
            export(self.tree, export_dir, format="dir")
            tarball_paths = self._get_current_source(base_export_dir,
                    package, version, target_dir)
            if tarball_paths is None:
                raise PackageVersionNotPresent(package, version, self)
            return tarball_paths
        finally:
            shutil.rmtree(tmpdir)


class UScanSource(UpstreamSource):
    """Upstream source that uses uscan."""

    def __init__(self, tree, top_level):
        self.tree = tree
        self.top_level = top_level

    def _export_watchfile(self):
        if self.top_level:
            watchfile = 'watch'
        else:
            watchfile = 'debian/watch'
        watch_id = self.tree.path2id(watchfile)
        if watch_id is None:
            raise WatchFileMissing()
        (tmp, tempfilename) = tempfile.mkstemp()
        try:
            tmp = os.fdopen(tmp, 'wb')
            watch = self.tree.get_file_text(watchfile, watch_id)
            tmp.write(watch)
        finally:
            tmp.close()
        return tempfilename

    @staticmethod
    def _xml_report_extract_upstream_version(text):
        from xml.dom.minidom import parseString
        dom = parseString(text)
        dehs_tags = dom.getElementsByTagName("dehs")
        if len(dehs_tags) != 1:
            return None
        dehs_tag = dehs_tags[0]
        for w in dehs_tag.getElementsByTagName("warnings"):
            warning(w.firstChild.wholeText)
        upstream_version_tags = dehs_tag.getElementsByTagName("upstream-version")
        if len(upstream_version_tags) != 1:
            return None
        upstream_version_tag = upstream_version_tags[0]
        return upstream_version_tag.firstChild.wholeText.encode("utf-8")

    def get_latest_version(self, package, current_version):
        try:
            tempfilename = self._export_watchfile()
        except WatchFileMissing:
            note("No watch file to use to check latest upstream release.")
            return None
        try:
            p = subprocess.Popen(["uscan", "--package=%s" % package, "--report",
                "--no-download", "--dehs", "--watchfile=%s" % tempfilename,
                "--upstream-version=%s" % current_version],
                stdout=subprocess.PIPE)
            (stdout, stderr) = p.communicate()
        finally:
            os.unlink(tempfilename)
        return self._xml_report_extract_upstream_version(stdout)

    def fetch_tarballs(self, package, version, target_dir, components=None):
        note("Using uscan to look for the upstream tarball.")
        try:
            tempfilename = self._export_watchfile()
        except WatchFileMissing:
            note("No watch file to use to retrieve upstream tarball.")
            raise PackageVersionNotPresent(package, version, self)
        try:
            r = subprocess.call(["uscan", "--watchfile=%s" % tempfilename, 
                "--upstream-version=%s" % version,
                "--force-download", "--rename", "--package=%s" % package,
                "--check-dirname-level=0",
                "--download", "--destdir=%s" % target_dir,
                "--download-version=%s" % version])
        finally:
            os.unlink(tempfilename)
        if r != 0:
            note("uscan could not find the needed tarball.")
            raise PackageVersionNotPresent(package, version, self)
        orig_files = gather_orig_files(package, version, target_dir)
        if orig_files is None:
            note("the expected files generated by uscan could not be found in"
                 "%s.", target_dir)
            raise PackageVersionNotPresent(package, version, self)
        return orig_files


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

    def fetch_tarballs(self, package, version, target_dir, components=None):
        note("Using the current branch without the 'debian' directory "
                "to create the tarball")
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
        return "%s(%r)" % (self.__class__.__name__, self._sources)

    def fetch_tarballs(self, package, version, target_dir, components=None):
        for source in self._sources:
            try:
                paths = source.fetch_tarballs(package, version, target_dir,
                    components)
            except PackageVersionNotPresent:
                pass
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
        return None


def gather_orig_files(package, version, path):
    """Grab the orig files for a particular package.

    :param package: package name
    :param version: package upstream version string
    :return: List of orig tarfile paths, or None if none were found
    """
    prefix = "%s_%s.orig" % (package.encode('ascii'), version.encode('ascii'))
    ret = []
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        return None
    for filename in os.listdir(path):
        if filename.startswith(prefix):
            ret.append(os.path.join(path, filename))
    if ret:
        return ret
    return None


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
        self.version = version
        self.store_dir = store_dir
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
            note("Upstream tarball already exists in build directory, "
                    "using that")
            return [(p, component_from_orig_tarball(p,
                self.package, self.version)) for p in in_target]
        if self.already_exists_in_store() is None:
            if not os.path.exists(self.store_dir):
                os.makedirs(self.store_dir)
            try:
                paths = self.source.fetch_tarballs(self.package,
                    self.version, self.store_dir)
            except PackageVersionNotPresent:
                raise MissingUpstreamTarball(self.package, self.version)
            assert isinstance(paths, list)
        else:
            note("Using the upstream tarball that is present in %s" %
                 self.store_dir)
        paths = self.provide_from_store_dir(target_dir)
        assert paths is not None
        return [(p, component_from_orig_tarball(p, self.package, self.version))
                for p in paths]

    def already_exists_in_target(self, target_dir):
        return gather_orig_files(self.package, self.version, target_dir)

    def already_exists_in_store(self):
        return gather_orig_files(self.package, self.version, self.store_dir)

    def provide_from_store_dir(self, target_dir):
        paths = self.already_exists_in_store()
        if paths is None:
            return None
        for path in paths:
            repack_tarball(path, os.path.basename(path),
                    target_dir=target_dir)
        return paths


def extract_tarball_version(path, packagename):
    """Extract a version from a tarball path.

    :param path: Path to the tarball (e.g. "/tmp/bzr-builddeb-2.7.3.tar.gz")
    :param packagename: Name of the package (e.g. "bzr-builddeb")
    """
    basename = os.path.basename(path)
    for extension in [".tar.gz", ".tgz", ".tar.bz2", ".tar.lzma", ".tar.xz",
            ".zip"]:
        if basename.endswith(extension):
            basename = basename[:-len(extension)]
            break
    else:
        # Unknown extension
        return None
    # Debian style tarball
    m = re.match(packagename+"_(.*).orig", basename)
    if m:
        return str(m.group(1))
    # Traditional, PACKAGE-VERSION.tar.gz
    m = re.match(packagename+"-(.*)", basename)
    if m:
        return str(m.group(1))
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

    def get_latest_version(self, package, version):
        if self.version is not None:
            return self.version
        self.version = extract_tarball_version(self.path, package)
        return self.version


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
            package, distribution_name, distroseries_name)
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
        release = self.project.getRelease(version=version)
        if release is None:
            raise PackageVersionNotPresent(package, version, self)
        release_files = []
        for f in release.files:
            if f.file_type == "Code Release Tarball":
                release_files.append(f.file)
        if len(release_files) == 0:
            warning("Release %s for package %s found on Launchpad but no "
                    "associated tarballs.", version, package)
            raise PackageVersionNotPresent(package, version, self)
        elif len(release_files) > 1:
            warning("More than one release file for release %s of package %s"
                    "found on Launchpad. Using the first.", version, package)
        hosted_file = release_files[0]
        tmpdir = tempfile.mkdtemp(prefix="builddeb-launchpad-source-")
        try:
            inf = hosted_file.open()
            try:
                note("Downloading upstream tarball %s from Launchpad",
                     inf.filename)
                filename = inf.filename.encode(osutils._fs_enc)
                filename = filename.replace("/", "")
                tmppath = os.path.join(tmpdir, filename)
                outf = open(tmppath, 'wb')
                try:
                    outf.write(inf.read())
                finally:
                    outf.close()
            finally:
                inf.close()
            dest_name = new_tarball_name(package, version, filename)
            repack_tarball(tmppath, dest_name, target_dir=target_dir)
            return os.path.join(target_dir, dest_name)
        finally:
            shutil.rmtree(tmpdir)

    def get_latest_version(self, package, version):
        versions = []
        for release in self.project_series.releases:
            versions.append((release.date_released, release.version))
        versions.sort()
        return versions[-1][1].encode("utf-8")
