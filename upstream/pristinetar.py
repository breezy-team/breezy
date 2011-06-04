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

    def create_delta_revprops(self, tree, tarball):
        """Create the revision properties with the pristine tar delta.

        :param tree: Bazaar Tree to diff against
        :param tarball: The pristine tarball
        :return: Dictionary with extra revision properties
        """
        ret = {}
        delta = self.make_pristine_tar_delta(tree, tarball)
        uuencoded = standard_b64encode(delta)
        if tarball.endswith(".tar.bz2"):
            ret["deb-pristine-delta-bz2"] = uuencoded
        else:
            ret["deb-pristine-delta"] = uuencoded
        return ret
