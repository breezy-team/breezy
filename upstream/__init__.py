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

from base64 import (
    standard_b64decode,
    )


try:
    from debian.changelog import Version
except ImportError:
    # Prior to 0.1.15 the debian module was called debian_bundle
    from debian_bundle.changelog import Version

from bzrlib.errors import (
    NoSuchRevision,
    NoSuchTag,
    )
from bzrlib.trace import (
    note,
    warning,
    )

from bzrlib.plugins.builddeb.errors import (
    MissingUpstreamTarball,
    PackageVersionNotPresent,
    PerFileTimestampsNotSupported,
    PristineTarError,
    WatchFileMissing,
    )
from bzrlib.plugins.builddeb.repack_tarball import repack_tarball
from bzrlib.plugins.builddeb.util import (
    export,
    reconstruct_pristine_tar,
    tarball_name,
    )


class UpstreamSource(object):
    """A source for upstream versions (uscan, get-orig-source, etc)."""

    def get_latest_version(self, package, current_version):
        """Check what the latest upstream version is.

        :param package: Name of the package
        :param version: The current upstream version of the package.
        :return: The version string of the latest available upstream version.
        """
        raise NotImplementedError(self.get_latest_version)

    def version_as_revision(self, package, version):
        """Lookup the revision id for a particular version.

        :param package: Package name
        :package version: Version string
        :raise PackageVersionNotPresent: When the specified version was not
            found
        """
        raise NotImplementedError(self.version_as_revision)

    def has_version(self, package, version, md5=None):
        """Check whether this upstream source contains a particular package.

        :param package: Package name
        :param version: Version string
        :param md5: Optional required MD5sum of the resulting tarball
        """
        raise NotImplementedError(self.has_version)

    def fetch_tarball(self, package, version, target_dir):
        """Fetch the source tarball for a particular version.

        :param package: Name of the package
        :param version: Version string of the version to fetch
        :param target_dir: Directory in which to store the tarball
        :return: Path of the fetched tarball
        """
        raise NotImplementedError(self.fetch_tarball)

    def _tarball_path(self, package, version, target_dir, format=None):
        return os.path.join(target_dir, tarball_name(package, version,
                    format=format))


class PristineTarSource(UpstreamSource):
    """Source that uses the pristine-tar revisions in the packaging branch."""

    def __init__(self, tree, branch):
        self.branch = branch
        self.tree = tree

    def tag_name(self, version, distro=None):
        """Gets the tag name for the upstream part of version.

        :param version: the Version object to extract the upstream
            part of the version number from.
        :return: a String with the name of the tag.
        """
        assert isinstance(version, str)
        if distro is None:
            return "upstream-" + version
        return "upstream-%s-%s" % (distro, version)

    def fetch_tarball(self, package, version, target_dir):
        revid = self.version_as_revision(package, version)
        try:
            rev = self.branch.repository.get_revision(revid)
        except NoSuchRevision:
            raise PackageVersionNotPresent(package, version, self)
        note("Using pristine-tar to reconstruct the needed tarball.")
        if self.has_pristine_tar_delta(rev):
            format = self.pristine_tar_format(rev)
        else:
            format = 'gz'
        target_filename = self._tarball_path(package, version,
                                             target_dir, format=format)
        try:
            self.reconstruct_pristine_tar(revid, package, version, target_filename)
        except PristineTarError:
            raise PackageVersionNotPresent(package, version, self)
        except PerFileTimestampsNotSupported:
            raise PackageVersionNotPresent(package, version, self)
        return target_filename

    def _has_version(self, tag_name, md5=None):
        if not self.branch.tags.has_tag(tag_name):
            return False
        revid = self.branch.tags.lookup_tag(tag_name)
        self.branch.lock_read()
        try:
            graph = self.branch.repository.get_graph()
            if not graph.is_ancestor(revid, self.branch.last_revision()):
                return False
        finally:
            self.branch.unlock()
        if md5 is None:
            return True
        rev = self.branch.repository.get_revision(revid)
        try:
            return rev.properties['deb-md5'] == md5
        except KeyError:
            warning("tag %s present in branch, but there is no "
                "associated 'deb-md5' property" % tag_name)
            return True

    def version_as_revision(self, package, version):
        assert isinstance(version, str)
        for tag_name in self.possible_tag_names(version):
            if self._has_version(tag_name):
                return self.branch.tags.lookup_tag(tag_name)
        tag_name = self.tag_name(version)
        try:
            return self.branch.tags.lookup_tag(tag_name)
        except NoSuchTag:
            raise PackageVersionNotPresent(package, version, self)

    def has_version(self, package, version, md5=None):
        assert isinstance(version, str), str(type(version))
        for tag_name in self.possible_tag_names(version):
            if self._has_version(tag_name, md5=md5):
                return True
        return False

    def possible_tag_names(self, version):
        assert isinstance(version, str)
        tags = [self.tag_name(version),
                self.tag_name(version, distro="debian"),
                self.tag_name(version, distro="ubuntu"),
                "upstream/%s" % version]
        return tags

    def has_pristine_tar_delta(self, rev):
        return ('deb-pristine-delta' in rev.properties
                or 'deb-pristine-delta-bz2' in rev.properties)

    def pristine_tar_format(self, rev):
        if 'deb-pristine-delta' in rev.properties:
            return 'gz'
        elif 'deb-pristine-delta-bz2' in rev.properties:
            return 'bz2'
        assert self.has_pristine_tar_delta(rev)
        raise AssertionError("Not handled new delta type in "
                "pristine_tar_format")

    def pristine_tar_delta(self, rev):
        if 'deb-pristine-delta' in rev.properties:
            uuencoded = rev.properties['deb-pristine-delta']
        elif 'deb-pristine-delta-bz2' in rev.properties:
            uuencoded = rev.properties['deb-pristine-delta-bz2']
        else:
            assert self.has_pristine_tar_delta(rev)
            raise AssertionError("Not handled new delta type in "
                    "pristine_tar_delta")
        return standard_b64decode(uuencoded)

    def reconstruct_pristine_tar(self, revid, package, version,
            dest_filename):
        """Reconstruct a pristine-tar tarball from a bzr revision."""
        tree = self.branch.repository.revision_tree(revid)
        tmpdir = tempfile.mkdtemp(prefix="builddeb-pristine-")
        try:
            dest = os.path.join(tmpdir, "orig")
            rev = self.branch.repository.get_revision(revid)
            if self.has_pristine_tar_delta(rev):
                export(tree, dest, format='dir')
                delta = self.pristine_tar_delta(rev)
                reconstruct_pristine_tar(dest, delta, dest_filename)
            else:
                export(tree, dest_filename, require_per_file_timestamps=True)
        finally:
            shutil.rmtree(tmpdir)


class AptSource(UpstreamSource):
    """Upstream source that uses apt-source."""

    def fetch_tarball(self, package, upstream_version, target_dir, 
            _apt_pkg=None):
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
            if upstream_version == Version(version).upstream_version:
                if self._run_apt_source(package, version, target_dir):
                    return self._tarball_path(package, version, target_dir)
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


class GetOrigSourceSource(UpstreamSource):
    """Upstream source that uses the get-orig-source rule in debian/rules."""

    def __init__(self, tree, larstiq):
        self.tree = tree
        self.larstiq = larstiq

    def _get_orig_source(self, source_dir, desired_tarball_names,
                        target_dir):
        note("Trying to use get-orig-source to retrieve needed tarball.")
        command = ["make", "-f", "debian/rules", "get-orig-source"]
        proc = subprocess.Popen(command, cwd=source_dir)
        ret = proc.wait()
        if ret != 0:
            note("Trying to run get-orig-source rule failed")
            return None
        for desired_tarball_name in desired_tarball_names:
            fetched_tarball = os.path.join(source_dir, desired_tarball_name)
            if os.path.exists(fetched_tarball):
                repack_tarball(fetched_tarball, desired_tarball_name,
                               target_dir=target_dir, force_gz=False)
                return fetched_tarball
        note("get-orig-source did not create %s", desired_tarball_name)
        return None

    def fetch_tarball(self, package, version, target_dir):
        if self.larstiq:
            rules_name = 'rules'
        else:
            rules_name = 'debian/rules'
        rules_id = self.tree.path2id(rules_name)
        if rules_id is not None:
            desired_tarball_names = [tarball_name(package, version),
                    tarball_name(package, version, 'bz2'),
                    tarball_name(package, version, 'lzma')]
            tmpdir = tempfile.mkdtemp(prefix="builddeb-get-orig-source-")
            try:
                base_export_dir = os.path.join(tmpdir, "export")
                export_dir = base_export_dir
                if self.larstiq:
                    os.mkdir(export_dir)
                    export_dir = os.path.join(export_dir, "debian")
                export(self.tree, export_dir, format="dir")
                tarball_path = self._get_orig_source(base_export_dir,
                        desired_tarball_names, target_dir)
                if tarball_path is None:
                    raise PackageVersionNotPresent(package, version, self)
                return tarball_path
            finally:
                shutil.rmtree(tmpdir)
        note("No debian/rules file to try and use for a get-orig-source rule")
        raise PackageVersionNotPresent(package, version, self)


class UScanSource(UpstreamSource):
    """Upstream source that uses uscan."""

    def __init__(self, tree, larstiq):
        self.tree = tree
        self.larstiq = larstiq

    def _export_watchfile(self):
        if self.larstiq:
            watchfile = 'watch'
        else:
            watchfile = 'debian/watch'
        watch_id = self.tree.path2id(watchfile)
        if watch_id is None:
            raise WatchFileMissing()
        (tmp, tempfilename) = tempfile.mkstemp()
        try:
            tmp = os.fdopen(tmp, 'wb')
            watch = self.tree.get_file_text(watch_id)
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

    def fetch_tarball(self, package, version, target_dir):
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
                "--download", "--repack", "--destdir=%s" % target_dir,
                "--download-version=%s" % version])
        finally:
            os.unlink(tempfilename)
        if r != 0:
            note("uscan could not find the needed tarball.")
            raise PackageVersionNotPresent(package, version, self)
        return self._tarball_path(package, version, target_dir)


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

    def fetch_tarball(self, package, version, target_dir):
        note("Using the current branch without the 'debian' directory "
                "to create the tarball")
        tarball_path = self._tarball_path(package, version, target_dir)
        self._split(package, version, tarball_path)
        return tarball_path


class StackedUpstreamSource(UpstreamSource):
    """An upstream source that checks a list of other upstream sources.

    The first source that can provide a tarball, wins. 
    """

    def __init__(self, sources):
        self._sources = sources

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self._sources)

    def fetch_tarball(self, package, version, target_dir):
        for source in self._sources:
            try:
                path = source.fetch_tarball(package, version, target_dir)
            except PackageVersionNotPresent:
                pass
            else:
                assert isinstance(path, basestring)
                return path
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
        in_target = self.already_exists_in_target(target_dir)
        if in_target is not None:
            note("Upstream tarball already exists in build directory, "
                    "using that")
            return in_target
        if self.already_exists_in_store() is None:
            if not os.path.exists(self.store_dir):
                os.makedirs(self.store_dir)
            try:
                path = self.source.fetch_tarball(self.package,
                    self.version, self.store_dir)
            except PackageVersionNotPresent:
                raise MissingUpstreamTarball(self._tarball_names()[0])
            assert isinstance(path, basestring)
        else:
            note("Using the upstream tarball that is present in %s" %
                 self.store_dir)
        path = self.provide_from_store_dir(target_dir)
        assert path is not None
        return path

    def already_exists_in_target(self, target_dir):
        for tarball_name in self._tarball_names():
            path = os.path.join(target_dir, tarball_name)
            if os.path.exists(path):
                return path
        return None

    def already_exists_in_store(self):
        for tarball_name in self._tarball_names():
            path = os.path.join(self.store_dir, tarball_name)
            if os.path.exists(path):
                return path
        return None

    def provide_from_store_dir(self, target_dir):
        path = self.already_exists_in_store()
        if path is not None:
            repack_tarball(path, os.path.basename(path),
                    target_dir=target_dir, force_gz=False)
            return path
        return path

    def _tarball_names(self):
        return [tarball_name(self.package, self.version),
                tarball_name(self.package, self.version, format='bz2'),
                tarball_name(self.package, self.version, format='lzma')]


def extract_tarball_version(path, packagename):
    """Extract a version from a tarball path.

    :param path: Path to the tarball (e.g. "/tmp/bzr-builddeb-2.7.3.tar.gz")
    :param packagename: Name of the package (e.g. "bzr-builddeb")
    """
    basename = os.path.basename(path)
    for extension in [".tar.gz", ".tgz", ".tar.bz2", ".zip"]:
        if basename.endswith(extension):
            basename = basename[:-len(extension)]
            break
    else:
        # Unknown extension
        return None
    # Debian style tarball
    m = re.match(packagename+"_(.*).orig", basename)
    if m:
        return m.group(1)
    # Traditional, PACKAGE-VERSION.tar.gz
    m = re.match(packagename+"-(.*)", basename)
    if m:
        return m.group(1)
    return None


class TarfileSource(UpstreamSource):
    """Source that uses a single local tarball."""

    def __init__(self, path, version=None):
        self.path = path
        self.version = version

    def fetch_tarball(self, package, version, target_dir):
        if version != self.version:
            raise PackageVersionNotPresent(package, version, self)
        dest_name = tarball_name(package, version)
        repack_tarball(self.path, dest_name, target_dir=target_dir, force_gz=True)
        return os.path.join(target_dir, dest_name)

    def get_latest_version(self, package, version):
        if self.version is not None:
            return self.version
        return extract_tarball_version(self.path, package)
