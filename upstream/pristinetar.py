#    pristinetar.py -- Providers of upstream source
#    Copyright (C) 2009-2011 Canonical Ltd.
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

from base64 import (
    standard_b64decode,
    standard_b64encode,
    )
import errno
import os
import shutil
import subprocess
import tempfile

from bzrlib.plugins.builddeb.errors import (
    MultipleUpstreamTarballsNotSupported,
    PackageVersionNotPresent,
    PerFileTimestampsNotSupported,
    )
from bzrlib.plugins.builddeb.upstream import UpstreamSource
from bzrlib.plugins.builddeb.util import (
    export,
    subprocess_setup,
    )

from bzrlib import osutils
from bzrlib.errors import (
    BzrError,
    NoSuchRevision,
    NoSuchTag,
    )
from bzrlib.trace import (
    note,
    warning,
    )


class PristineTarError(BzrError):
    _fmt = 'There was an error using pristine-tar: %(error)s.'

    def __init__(self, error):
        BzrError.__init__(self, error=error)


def reconstruct_pristine_tar(dest, delta, dest_filename):
    """Reconstruct a pristine tarball from a directory and a delta.

    :param dest: Directory to pack
    :param delta: pristine-tar delta
    :param dest_filename: Destination filename
    """
    command = ["pristine-tar", "gentar", "-",
               os.path.abspath(dest_filename)]
    try:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE,
                cwd=dest, preexec_fn=subprocess_setup,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError, e:
        if e.errno == errno.ENOENT:
            raise PristineTarError("pristine-tar is not installed")
        else:
            raise
    (stdout, stderr) = proc.communicate(delta)
    if proc.returncode != 0:
        raise PristineTarError("Generating tar from delta failed: %s" % stdout)


def make_pristine_tar_delta(dest, tarball_path):
    """Create a pristine-tar delta for a tarball.

    :param dest: Directory to generate pristine tar delta for
    :param tarball_path: Path to the tarball
    :return: pristine-tarball
    """
    # If tarball_path is relative, the cwd=dest parameter to Popen will make
    # pristine-tar faaaail. pristine-tar doesn't use the VFS either, so we
    # assume local paths.
    tarball_path = osutils.abspath(tarball_path)
    command = ["pristine-tar", "gendelta", tarball_path, "-"]
    try:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                cwd=dest, preexec_fn=subprocess_setup,
                stderr=subprocess.PIPE)
    except OSError, e:
        if e.errno == errno.ENOENT:
            raise PristineTarError("pristine-tar is not installed")
        else:
            raise
    (stdout, stderr) = proc.communicate()
    if proc.returncode != 0:
        raise PristineTarError("Generating delta from tar failed: %s" % stderr)
    return stdout


class PristineTarSource(UpstreamSource):
    """Source that uses the pristine-tar revisions in the packaging branch."""

    def __init__(self, tree, branch):
        self.branch = branch
        self.tree = tree

    def __repr__(self):
        return "<%s at %s>" % (self.__class__.__name__, self.branch.base)

    def tag_name(self, version, component=None, distro=None):
        """Gets the tag name for the upstream part of version.

        :param version: the Version object to extract the upstream
            part of the version number from.
        :param component: Name of the component (None for base)
        :param distro: Optional distribution name
        :return: a String with the name of the tag.
        """
        assert isinstance(version, str)
        if distro is None:
            name = "upstream-" + version
        else:
            name = "upstream-%s-%s" % (distro, version)
        if component is not None:
            name += "/%s" % component
        return name

    def tag_version(self, version, revid, component=None):
        """Tags the upstream branch's last revision with an upstream version.

        Sets a tag on the last revision of the upstream branch and on the main
        branch with a tag that refers to the upstream part of the version
        provided.

        :param version: the upstream part of the version number to derive the 
            tag name from.
        :param component: name of the component that is being imported
            (None for base)
        :param revid: the revid to associate the tag with, or None for the
            tip of self.pristine_upstream_branch.
        :return The tag name, revid of the added tag.
        """
        assert isinstance(version, str)
        tag_name = self.tag_name(version, component=component)
        self.branch.tags.set_tag(tag_name, revid)
        return tag_name, revid

    def import_component_tarball(self, package, version, tree, component=None,
            md5=None, tarball=None, author=None, timestamp=None,
            parent_ids=None):
        """Import a tarball.

        :param package: Package name
        :param version: Upstream version
        :param component: Component name (None for base)
        """
        if component is not None:
            raise BzrError("Importing non-base tarballs not yet supported")
        tree.set_parent_ids(parent_ids)
        revprops = {}
        if md5 is not None:
            revprops["deb-md5"] = md5
            delta = self.make_pristine_tar_delta(tree, tarball)
            uuencoded = standard_b64encode(delta)
            if tarball.endswith(".tar.bz2"):
                revprops["deb-pristine-delta-bz2"] = uuencoded
            elif tarball.endswith(".tar.lzma"):
                revprops["deb-pristine-delta-lzma"] = uuencoded
            else:
                revprops["deb-pristine-delta"] = uuencoded
        if author is not None:
            revprops['authors'] = author
        timezone = None
        if timestamp is not None:
            timezone = timestamp[1]
            timestamp = timestamp[0]
        message = "Import upstream version %s" % (version,)
        if component is not None:
            message += ", component %s" % component
        revid = tree.commit(message, revprops=revprops, timestamp=timestamp,
            timezone=timezone)
        tag_name, _ = self.tag_version(version, revid=revid)
        return tag_name, revid

    def fetch_component_tarball(self, package, version, component, target_dir):
        revid = self.version_component_as_revision(package, version, component)
        try:
            rev = self.branch.repository.get_revision(revid)
        except NoSuchRevision:
            raise PackageVersionNotPresent(package, version, self)
        note("Using pristine-tar to reconstruct the needed tarball.")
        if self.has_pristine_tar_delta(rev):
            format = self.pristine_tar_format(rev)
        else:
            format = 'gz'
        target_filename = self._tarball_path(package, version, component,
                                             target_dir, format=format)
        try:
            self.reconstruct_pristine_tar(revid, package, version, target_filename)
        except PristineTarError:
            raise PackageVersionNotPresent(package, version, self)
        except PerFileTimestampsNotSupported:
            raise PackageVersionNotPresent(package, version, self)
        return target_filename

    def fetch_tarballs(self, package, version, target_dir):
        return [self.fetch_component_tarball(package, version, None, target_dir)]

    def _has_revision(self, revid, md5=None):
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
            warning("tag present in branch, but there is no "
                "associated 'deb-md5' property in associated "
                "revision %s", revid)
            return True

    def version_as_revision(self, package, version, tarballs=None):
        if tarballs is None:
            return self.version_component_as_revision(package, version, component=None)
        elif len(tarballs) > 1:
            raise MultipleUpstreamTarballsNotSupported()
        else:
            return self.version_component_as_revision(package, version, tarballs[0][1],
                tarballs[0][2])

    def version_component_as_revision(self, package, version, component, md5=None):
        assert isinstance(version, str)
        for tag_name in self.possible_tag_names(version, component=component):
            try:
                revid = self.branch.tags.lookup_tag(tag_name)
            except NoSuchTag:
                continue
            else:
                if self._has_revision(revid, md5=md5):
                    return revid
        tag_name = self.tag_name(version, component=component)
        try:
            return self.branch.tags.lookup_tag(tag_name)
        except NoSuchTag:
            raise PackageVersionNotPresent(package, version, self)

    def has_version(self, package, version, tarballs=None):
        if tarballs is None:
            return self.has_version_component(package, version, component=None)
        elif len(tarballs) > 1:
            raise MultipleUpstreamTarballsNotSupported()
        else:
            return self.has_version_component(package, version, tarballs[0][1],
                    tarballs[0][2])

    def has_version_component(self, package, version, component, md5=None):
        assert isinstance(version, str), str(type(version))
        for tag_name in self.possible_tag_names(version, component=component):
            try:
                revid = self.branch.tags.lookup_tag(tag_name)
            except NoSuchTag:
                continue
            else:
                if self._has_revision(revid, md5=md5):
                    return True
        return False

    def possible_tag_names(self, version, component):
        assert isinstance(version, str)
        tags = [self.tag_name(version, component=component),
                self.tag_name(version, component=component, distro="debian"),
                self.tag_name(version, component=component, distro="ubuntu"),
                ]
        if component is None:
            # compatibility with git-buildpackage
            tags += ["upstream/%s" % version]
        return tags

    def has_pristine_tar_delta(self, rev):
        return ('deb-pristine-delta' in rev.properties
                or 'deb-pristine-delta-bz2' in rev.properties
                or 'deb-pristine-delta-lzma' in rev.properties)

    def pristine_tar_format(self, rev):
        if 'deb-pristine-delta' in rev.properties:
            return 'gz'
        elif 'deb-pristine-delta-bz2' in rev.properties:
            return 'bz2'
        elif 'deb-pristine-delta-lzma' in rev.properties:
            return 'lzma'
        assert self.has_pristine_tar_delta(rev)
        raise AssertionError("Not handled new delta type in "
                "pristine_tar_format")

    def pristine_tar_delta(self, rev):
        if 'deb-pristine-delta' in rev.properties:
            uuencoded = rev.properties['deb-pristine-delta']
        elif 'deb-pristine-delta-bz2' in rev.properties:
            uuencoded = rev.properties['deb-pristine-delta-bz2']
        elif 'deb-pristine-delta-lzma' in rev.properties:
            uuencoded = rev.properties['deb-pristine-delta-lzma']
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

    def iter_versions(self):
        """Iterate over all upstream versions.

        :return: Iterator over (tag_name, version, revid) tuples
        """
        for tag_name, tag_revid in self.branch.tags.get_tag_dict().iteritems():
            if not is_upstream_tag(tag_name):
                continue
            yield (tag_name, upstream_tag_version(tag_name), tag_revid)


def is_upstream_tag(tag):
    """Return true if tag is an upstream tag.

    :param tag: The string name of the tag.
    :return: True if the tag name is one generated by upstream tag operations.
    """
    return tag.startswith('upstream-') or tag.startswith('upstream/')


def upstream_tag_version(tag):
    """Return the upstream version portion of an upstream tag name.

    :param tag: The string name of the tag.
    :return: The version portion of the tag.
    """
    assert is_upstream_tag(tag), "Not an upstream tag: %s" % tag
    if tag.startswith('upstream/'):
        tag = tag[len('upstream/'):]
    elif tag.startswith('upstream-'):
        tag = tag[len('upstream-'):]
        if tag.startswith('debian-'):
            tag = tag[len('debian-'):]
        elif tag.startswith('ubuntu-'):
            tag = tag[len('ubuntu-'):]
    return tag
