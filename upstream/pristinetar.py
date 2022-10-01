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

from typing import Optional

from base64 import (
    standard_b64decode,
    standard_b64encode,
    )
import configparser
from debian.copyright import globs_to_re
import errno
from io import BytesIO
import os
import re
import subprocess
from tarfile import TarFile
import tempfile

from .... import debug
from . import (
    PackageVersionNotPresent,
    UpstreamSource,
    )
from ..util import (
    export_with_nested,
    subprocess_setup,
    )

from .... import (
    config as _mod_config,
    osutils,
    revision as _mod_revision,
    )
from ....branch import Branch
from ....commit import NullCommitReporter
from ....errors import (
    BzrError,
    DivergedBranches,
    NoSuchRevision,
    NoSuchTag,
    NotBranchError,
    )
from ....revision import NULL_REVISION
from ....trace import (
    mutter,
    note,
    warning,
    )
try:
    from ....transport import NoSuchFile
except ImportError:
    from ....errors import NoSuchFile

from .branch import (
    git_snapshot_data_from_version,
    InvalidRevisionSpec,
    RevisionSpec,
    )
from .tags import (
    is_upstream_tag,
    possible_upstream_tag_names,
    search_for_upstream_version,
    upstream_version_tag_start_revids,
    upstream_tag_version,
    )
from debmutate.vcs import gbp_expand_tag_name
from debmutate.versions import mangle_version_for_git


class PristineTarError(BzrError):
    _fmt = 'There was an error using pristine-tar: %(error)s.'

    def __init__(self, error):
        BzrError.__init__(self, error=error)


class PristineTarDeltaTooLarge(PristineTarError):
    _fmt = 'The delta generated was too large: %(error)s.'


class PristineTarDeltaAbsent(PristineTarError):
    _fmt = 'There is no delta present for %(version)s.'

    def __init__(self, version):
        BzrError.__init__(self, version=version)


class PristineTarDeltaExists(PristineTarError):
    _fmt = 'An existing pristine tar entry exists for %(filename)s'


def git_store_pristine_tar(branch, filename, tree_id, delta, force=False):
    tree = branch.create_memorytree()
    with tree.lock_write():
        id_filename = '%s.id' % filename
        delta_filename = '%s.delta' % filename
        try:
            existing_id = tree.get_file_text(id_filename)
            existing_delta = tree.get_file_text(delta_filename)
        except NoSuchFile:
            pass
        else:
            if existing_id.strip(b'\n') == tree_id and delta == existing_delta:
                # Nothing to do.
                return
            if not force:
                raise PristineTarDeltaExists(filename)
        tree.put_file_bytes_non_atomic(id_filename, tree_id + b'\n')
        tree.put_file_bytes_non_atomic(delta_filename, delta)
        tree.add([id_filename, delta_filename], [None, None], ['file', 'file'])
        revid = tree.commit(
            'Add pristine tar data for %s' % filename,
            reporter=NullCommitReporter())
        mutter('Added pristine tar data for %s: %s',
               filename, revid)


def reconstruct_pristine_tar(dest, delta, dest_filename):
    """Reconstruct a pristine tarball from a directory and a delta.

    :param dest: Directory to pack
    :param delta: pristine-tar delta
    :param dest_filename: Destination filename
    """
    command = ["pristine-tar", "gentar", "-",
               os.path.abspath(dest_filename)]
    try:
        proc = subprocess.Popen(
                command, stdin=subprocess.PIPE,
                cwd=dest, preexec_fn=subprocess_setup,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as e:
        if e.errno == errno.ENOENT:
            raise PristineTarError("pristine-tar is not installed")
        else:
            raise
    (stdout, stderr) = proc.communicate(delta)
    if proc.returncode != 0:
        raise PristineTarError("Generating tar from delta failed: %s" % stdout)


def commit_pristine_tar(dest, tarball_path, upstream=None, committer=None):
    tarball_path = osutils.abspath(tarball_path)
    command = ["pristine-tar", "commit", tarball_path]
    if upstream:
        command.append(upstream)
    env = {}
    if committer is not None:
        name, email = _mod_config.parse_username(committer)
        env['GIT_COMMITTER_NAME'] = name
        env['GIT_COMMITTER_EMAIL'] = email
        env['GIT_AUTHOR_NAME'] = name
        env['GIT_AUTHOR_EMAIL'] = email

    try:
        proc = subprocess.Popen(
                command, stdout=subprocess.PIPE,
                cwd=dest, preexec_fn=subprocess_setup,
                stderr=subprocess.PIPE, env=env)
    except OSError as e:
        if e.errno == errno.ENOENT:
            raise PristineTarError("pristine-tar is not installed")
        else:
            raise
    (stdout, stderr) = proc.communicate()
    if proc.returncode != 0:
        if b'excessively large binary delta' in stderr:
            raise PristineTarDeltaTooLarge(stderr)
        elif b'No space left on device' in stderr:
            raise IOError(
                errno.ENOSPC,
                'Generating pristine tar delta failed: '
                'no space left on device')
        else:
            raise PristineTarError(
                "Generating delta from tar failed: %s" % stderr)
    return stdout


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
        proc = subprocess.Popen(
                command, stdout=subprocess.PIPE,
                cwd=dest, preexec_fn=subprocess_setup,
                stderr=subprocess.PIPE)
    except OSError as e:
        if e.errno == errno.ENOENT:
            raise PristineTarError("pristine-tar is not installed")
        else:
            raise
    (stdout, stderr) = proc.communicate()
    if proc.returncode != 0:
        if b'excessively large binary delta' in stderr:
            raise PristineTarDeltaTooLarge(stderr)
        else:
            raise PristineTarError(
                "Generating delta from tar failed: %s" % stderr)
    return stdout


def make_pristine_tar_delta_from_tree(
        tree, tarball_path, subdir=None, exclude=None):
    with tempfile.TemporaryDirectory(prefix="builddeb-pristine-") as tmpdir:
        dest = os.path.join(tmpdir, "orig")
        with tree.lock_read():
            export_with_nested(tree, dest, format='dir', subdir=subdir)
        try:
            return make_pristine_tar_delta(dest, tarball_path)
        except PristineTarDeltaTooLarge:
            raise
        except PristineTarError:  # I.e. not PristineTarDeltaTooLarge
            if 'pristine-tar' in debug.debug_flags:
                revno, revid = tree.branch.last_revision_info()
                preserved = osutils.pathjoin(osutils.dirname(tarball_path),
                                             'orig-%s' % (revno,))
                mutter('pristine-tar failed for delta between %s rev: %s'
                       ' and tarball %s'
                       % (tree.basedir, (revno, revid), tarball_path))
                osutils.copy_tree(
                    dest, preserved)
                mutter('The failure can be reproduced with:\n'
                       '  cd %s\n'
                       '  pristine-tar -vdk gendelta %s -'
                       % (preserved, tarball_path))
            raise


def revision_has_pristine_tar_delta(rev):
    return (u'deb-pristine-delta' in rev.properties
            or u'deb-pristine-delta-bz2' in rev.properties
            or u'deb-pristine-delta-xz' in rev.properties)


def revision_pristine_tar_delta(rev):
    if u'deb-pristine-delta' in rev.properties:
        uuencoded = rev.properties[u'deb-pristine-delta']
    elif u'deb-pristine-delta-bz2' in rev.properties:
        uuencoded = rev.properties[u'deb-pristine-delta-bz2']
    elif u'deb-pristine-delta-xz' in rev.properties:
        uuencoded = rev.properties[u'deb-pristine-delta-xz']
    else:
        assert revision_has_pristine_tar_delta(rev)
        raise AssertionError(
            "Not handled new delta type in pristine_tar_delta")
    return standard_b64decode(uuencoded)


def revision_pristine_tar_format(rev):
    if u'deb-pristine-delta' in rev.properties:
        return 'gz'
    elif u'deb-pristine-delta-bz2' in rev.properties:
        return 'bz2'
    elif u'deb-pristine-delta-xz' in rev.properties:
        return 'xz'
    assert revision_has_pristine_tar_delta(rev)
    raise AssertionError(
        "Not handled new delta type in pristine_tar_format")


class BasePristineTarSource(UpstreamSource):

    branch: Branch

    def _has_revision(self, revid, md5):
        raise NotImplementedError(self._has_revision)

    def possible_tag_names(self, package: Optional[str], version: str,
                           component: Optional[str], try_hard: bool = True):
        raise NotImplementedError(self.possible_tag_names)

    def tag_name(self, version, component=None, distro=None):
        raise NotImplementedError(self.tag_name)

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
        tag_name = self.tag_name(version, component=component)
        self.branch.tags.set_tag(tag_name, revid)
        return tag_name, revid

    def iter_versions(self):
        """Iterate over all upstream versions.

        :return: Iterator over (version, revid) tuples
        """
        ret = self._components_by_version()
        return ret.items()

    def version_as_revisions(self, package, version, tarballs=None):
        if tarballs is None:
            # FIXME: What if there are multiple tarballs?
            return {
                None: self.version_component_as_revision(
                    package, version, component=None)}
        ret = {}
        for (tarball, component, md5) in tarballs:
            ret[component] = self.version_component_as_revision(
                package, version, component, md5)
        return ret

    def has_version(
            self, package: Optional[str], version: str, tarballs=None,
            try_hard=True):
        if tarballs is None:
            return self.has_version_component(
                package, version, component=None, try_hard=try_hard)
        else:
            for (tarball, component, md5) in tarballs:
                if not self.has_version_component(
                        package, version, component, md5, try_hard=try_hard):
                    return False
            return True

    def _components_by_version(self):
        ret = {}
        for tag_name, tag_revid in self.branch.tags.get_tag_dict().items():
            if not is_upstream_tag(tag_name):
                continue
            (component, version) = upstream_tag_version(tag_name)
            ret.setdefault(version, {})[component] = tag_revid
        return ret

    def version_component_as_revision(
            self, package: Optional[str], version: str,
            component: Optional[str], md5: Optional[str] = None):
        with self.branch.lock_read():
            for tag_name in self.possible_tag_names(
                    package, version, component=component):
                try:
                    revid = self.branch.tags.lookup_tag(tag_name)
                except NoSuchTag:
                    continue
                else:
                    if self._has_revision(revid, md5=md5):
                        return revid
            # Note that we don't check *all* possible revids here,
            # since some of them are branch-local (such as revno:)
            (git_id, git_date) = git_snapshot_data_from_version(version)
            if git_id:
                try:
                    revspec = RevisionSpec.from_string('git:%s' % git_id)
                    return revspec.as_revision_id(self.branch)
                except (InvalidRevisionSpec, NoSuchTag):
                    pass
            revid = self._search_for_upstream_version(
                package, version, component, md5)
            tag_name = self.tag_name(version, component=component)
            if revid is not None:
                warning(
                    "Upstream import of %s lacks a tag. Set one by running: "
                    "brz tag -rrevid:%s %s", version, revid.decode('utf-8'),
                    tag_name)
                return revid
            try:
                return self.branch.tags.lookup_tag(tag_name)
            except NoSuchTag:
                raise PackageVersionNotPresent(package, version, self)

    def _search_for_upstream_version(
            self, package, version, component, md5=None):
        raise NotImplementedError(self._search_for_upstream_version)

    def has_version_component(
            self, package: Optional[str], version: str, component,
            md5=None, try_hard=True):
        for tag_name in self.possible_tag_names(
                package, version, component=component, try_hard=try_hard):
            try:
                revid = self.branch.tags.lookup_tag(tag_name)
            except NoSuchTag:
                continue
            else:
                if self._has_revision(revid, md5=md5):
                    return True
        return False


class BzrPristineTarSource(BasePristineTarSource):
    """Source that uses the pristine-tar revisions in the packaging branch."""

    def __init__(self, branch):
        self.branch = branch

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
        if distro is None:
            name = "upstream-" + version
        else:
            name = "upstream-%s-%s" % (distro, version)
        if component is not None:
            name += "/%s" % component
        return name

    def import_component_tarball(
            self, package, version, tree, parent_ids,
            component=None, md5=None, tarball=None, author=None,
            timestamp=None, subdir=None, exclude=None,
            force_pristine_tar=False, committer=None,
            files_excluded=None, reuse_existing=True):
        """Import a tarball.

        :param package: Package name
        :param version: Upstream version
        :param parent_ids: Dictionary mapping component names to revision ids
        :param component: Component name (None for base)
        :param exclude: Exclude directories
        :param force_pristine_tar: Whether to force creating a pristine-tar
            branch if one does not exist.
        :param committer: Committer identity to use
        :param reuse_existing: Whether to reuse existing tarballs, or raise
            an error
        """
        if exclude is None:
            exclude = []
        if files_excluded:
            files_excluded_re = globs_to_re(files_excluded)
        else:
            files_excluded_re = None

        def include_change(c):
            path = c.path[1]
            if path is None:
                return True
            if exclude and osutils.is_inside_any(exclude, path):
                return False
            if files_excluded_re and files_excluded_re.match(path):
                return False
            return True
        message = "Import upstream version %s" % (version,)
        revprops = {}
        supports_custom_revprops = (
            tree.branch.repository._format.supports_custom_revision_properties)
        if component is not None:
            message += ", component %s" % component
            if supports_custom_revprops:
                revprops["deb-component"] = component
        if md5 is not None:
            if supports_custom_revprops:
                revprops["deb-md5"] = md5
            delta = make_pristine_tar_delta_from_tree(
                tree, tarball, subdir=subdir, exclude=exclude)
            if supports_custom_revprops:
                uuencoded = standard_b64encode(delta).decode('ascii')
                if tarball.endswith(".tar.bz2"):
                    revprops[u"deb-pristine-delta-bz2"] = uuencoded
                elif tarball.endswith(".tar.xz"):
                    revprops[u"deb-pristine-delta-xz"] = uuencoded
                else:
                    revprops[u"deb-pristine-delta"] = uuencoded
            else:
                warning('Not setting pristine tar revision properties '
                        'since the repository does not support it.')
                delta = None
        else:
            delta = None
        if author is not None:
            revprops['authors'] = author
        timezone = None
        if timestamp is not None:
            timezone = timestamp[1]
            timestamp = timestamp[0]
        if len(parent_ids) == 0:
            base_revid = _mod_revision.NULL_REVISION
        else:
            base_revid = parent_ids[0]
        basis_tree = tree.branch.repository.revision_tree(base_revid)
        with tree.lock_write():
            builder = tree.branch.get_commit_builder(
                    parents=parent_ids, revprops=revprops, timestamp=timestamp,
                    timezone=timezone, committer=committer)
            try:
                changes = [c for c in tree.iter_changes(basis_tree) if
                           include_change(c)]
                list(builder.record_iter_changes(tree, base_revid, changes))
                builder.finish_inventory()
            except BaseException:
                builder.abort()
                raise
            revid = builder.commit(message)
            tag_name = self.tag_name(version, component=component)
            tree.branch.tags.set_tag(tag_name, revid)
            tree.update_basis_by_delta(revid, builder.get_basis_delta())
        mutter(
            'imported %s version %s component %r as revid %s, tagged %s',
            package, version, component, revid, tag_name)
        return tag_name, revid, delta is not None

    def fetch_component_tarball(self, package, version, component, target_dir):
        revid = self.version_component_as_revision(package, version, component)
        try:
            rev = self.branch.repository.get_revision(revid)
        except NoSuchRevision:
            raise PackageVersionNotPresent(package, version, self)
        if revision_has_pristine_tar_delta(rev):
            format = revision_pristine_tar_format(rev)
        else:
            format = 'gz'
        target_filename = self._tarball_path(package, version, component,
                                             target_dir, format=format)
        note("Using pristine-tar to reconstruct %s.",
             os.path.basename(target_filename))
        try:
            self.reconstruct_pristine_tar(
                revid, package, version, target_filename)
        except PristineTarError as e:
            warning('Unable to reconstruct %s using pristine tar: %s',
                    target_filename, e)
            raise PackageVersionNotPresent(package, version, self)
        return target_filename

    def possible_tag_names(
            self, package: Optional[str], version: str,
            component: Optional[str],
            try_hard: bool = True):
        return possible_upstream_tag_names(
            package, version, component, try_hard=try_hard)

    def get_pristine_tar_delta(self, package, version, dest_filename,
                               revid=None):
        rev = self.branch.repository.get_revision(revid)
        if revision_has_pristine_tar_delta(rev):
            return revision_pristine_tar_delta(rev)
        raise PristineTarDeltaAbsent(version)

    def reconstruct_pristine_tar(self, revid, package, version, dest_filename):
        """Reconstruct a pristine-tar tarball from a bzr revision."""
        tree = self.branch.repository.revision_tree(revid)
        try:
            delta = self.get_pristine_tar_delta(
                package, version, dest_filename, revid)
        except PristineTarDeltaAbsent:
            export_with_nested(tree, dest_filename, per_file_timestamps=True)
        else:
            with tempfile.TemporaryDirectory(prefix="bd-pristine-") as tmpdir:
                dest = os.path.join(tmpdir, "orig")
                export_with_nested(tree, dest, format='dir')
                reconstruct_pristine_tar(dest, delta, dest_filename)

    def _has_revision(self, revid, md5=None):
        with self.branch.lock_read():
            graph = self.branch.repository.get_graph()
            if not graph.is_ancestor(revid, self.branch.last_revision()):
                return False
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

    def fetch_tarballs(self, package, version, target_dir, components=None):
        note("Looking for upstream tarball in local branch.")
        if components is None:
            # Scan tags for components
            try:
                components = self._components_by_version()[version].keys()
            except KeyError:
                components = [None]
        return [
            self.fetch_component_tarball(
                package, version, component, target_dir)
            for component in components]

    def _search_for_upstream_version(
            self, package: str, version: str, component, md5=None):
        start_revids = []
        sources = []
        sources.append('main branch')
        start_revids.append(self.branch.last_revision())
        for tag_name, revid in upstream_version_tag_start_revids(
                self.branch.tags.get_tag_dict(), package, version):
            sources.append('tag %s' % tag_name)
            start_revids.append(revid)
        note('Searching for revision importing %s version %s on %s.',
             package, version, ', '.join(sources))
        revid = search_for_upstream_version(
            self.branch.repository, start_revids,
            package, version, component, md5)
        return revid


def get_pristine_tar_source(packaging_tree, packaging_branch):
    git = getattr(packaging_branch.repository, '_git', None)
    if git:
        return GitPristineTarSource.from_tree(packaging_tree, packaging_branch)
    return BzrPristineTarSource(packaging_branch)


class PristineTarDelta(object):

    def __init__(self, tar):
        self._tar = tar

    @classmethod
    def from_bytes(cls, data):
        tar = TarFile.gzopen(name='delta.tar.gz', fileobj=BytesIO(data))
        return cls(tar)

    def root(self):
        return os.path.commonpath(self.manifest())

    @property
    def version(self):
        return int(self._tar.extractfile('version').read().strip())

    @property
    def type(self):
        return self._tar.extractfile('type').read().strip()

    @property
    def sha256sum(self):
        return self._tar.extractfile('sha256sum').read().strip()

    def manifest(self):
        return self._tar.extractfile('manifest').readlines(False)

    def delta(self):
        return self._tar.extractfile('delta').read()

    def wrapper(self):
        return self._tar.extractfile('wrapper').read()


class GitPristineTarSource(BasePristineTarSource):

    SUFFIXES = ['tar.gz', 'tar.lzma', 'tar.xz', 'tar.bz2']

    def __init__(self, branch, gbp_tag_format=None, pristine_tar=None,
                 packaging_branch=None):
        self.branch = branch
        self.gbp_tag_format = gbp_tag_format
        self.pristine_tar = pristine_tar
        self.packaging_branch = packaging_branch

    def __repr__(self):
        return "<%s at %s>" % (self.__class__.__name__, self.branch.base)

    @classmethod
    def from_tree(cls, tree, packaging_branch=None):
        if tree and tree.has_filename('debian/gbp.conf'):
            parser = configparser.ConfigParser(defaults={
                'pristine-tar': 'false',
                'upstream-branch': 'upstream',
                'upstream-tag': 'upstream/%(version)s'},
                strict=False)
            parser.read_string(
                tree.get_file_text('debian/gbp.conf').decode(
                    'utf-8', errors='replace'),
                'debian/gbp.conf')
            try:
                gbp_tag_format = parser.get(
                    'import-orig', 'upstream-tag', raw=True)
            except configparser.Error:
                try:
                    gbp_tag_format = parser.get(
                        'DEFAULT', 'upstream-tag', raw=True)
                except configparser.Error:
                    gbp_tag_format = None
            try:
                pristine_tar = parser.getboolean(
                    'import-orig', 'pristine-tar')
            except configparser.Error:
                try:
                    pristine_tar = parser.getboolean(
                        'DEFAULT', 'pristine-tar')
                except configparser.Error:
                    pristine_tar = None
            upstream_branch = parser.get(
                'DEFAULT', 'upstream-branch', raw=True)
        else:
            gbp_tag_format = None
            upstream_branch = 'upstream'
            pristine_tar = None
        try:
            branch = tree.controldir.open_branch(upstream_branch)
        except NotBranchError:
            branch = tree.controldir.create_branch(upstream_branch)
        return cls(branch, gbp_tag_format, pristine_tar,
                   packaging_branch=packaging_branch)

    def tag_name(self, version, component=None, distro=None):
        """Gets the tag name for the upstream part of version.

        :param version: the upstream vrsion to use
        :param component: Name of the component (None for base)
        :param distro: Optional distribution name
        :return: a String with the name of the tag.
        """
        if self.gbp_tag_format is not None:
            return gbp_expand_tag_name(
                self.gbp_tag_format, mangle_version_for_git(version))
        # In git, the convention is to use a slash
        if distro is None:
            name = "upstream/" + mangle_version_for_git(version)
        else:
            name = "upstream-%s/%s" % (distro, mangle_version_for_git(version))
        if component is not None:
            name += "/%s" % component
        return name

    def import_component_tarball(
            self, package, version, tree, parent_ids,
            component=None, md5=None, tarball=None, author=None,
            timestamp=None, subdir=None, exclude=None,
            force_pristine_tar=False, committer=None,
            files_excluded=None, reuse_existing=True):
        """Import a tarball.

        :param package: Package name
        :param version: Upstream version
        :param parent_ids: Dictionary mapping component names to revision ids
        :param component: Component name (None for base)
        :param exclude: Exclude directories
        :param force_pristine_tar: Whether to force creating a pristine-tar
            branch if one does not exist.
        :param committer: Committer identity to use
        :param reuse_existing: Whether to reuse existing tarballs, or raise
            an error
        """
        if exclude is None:
            exclude = []
        if files_excluded:
            files_excluded_re = globs_to_re(files_excluded)
        else:
            files_excluded_re = None

        def include_change(c):
            path = c.path[1]
            if path is None:
                return True
            if exclude and osutils.is_inside_any(exclude, path):
                return False
            if files_excluded_re and files_excluded_re.match(path):
                return False
            return True
        message = "Import upstream version %s" % (version,)
        revprops = {}
        if component is not None:
            message += ", component %s" % component
        if author is not None:
            revprops['authors'] = author
        timezone = None
        if timestamp is not None:
            timezone = timestamp[1]
            timestamp = timestamp[0]
        if len(parent_ids) == 0:
            base_revid = _mod_revision.NULL_REVISION
        else:
            base_revid = parent_ids[0]
        basis_tree = tree.branch.repository.revision_tree(base_revid)
        with tree.lock_write():
            builder = tree.branch.get_commit_builder(
                    parents=parent_ids, revprops=revprops, timestamp=timestamp,
                    timezone=timezone, committer=committer)
            try:
                changes = [c for c in tree.iter_changes(basis_tree) if
                           include_change(c)]
                list(builder.record_iter_changes(tree, base_revid, changes))
                builder.finish_inventory()
            except BaseException:
                builder.abort()
                raise
            revid = builder.commit(message)
            tag_name = self.tag_name(version, component=component)
            tree.branch.tags.set_tag(tag_name, revid)
            tree.update_basis_by_delta(revid, builder.get_basis_delta())
        revtree = tree.branch.repository.revision_tree(revid)
        try:
            self.branch.pull(tree.branch, stop_revision=revid)
        except DivergedBranches:
            warning('Upstream version %s (%s) is older than current tip.',
                    version, tag_name)
            with tree.lock_write():
                builder = tree.branch.get_commit_builder(
                    parents=[tree.branch.last_revision(), revid],
                    committer=committer)
                list(builder.record_iter_changes(
                    tree, tree.branch.last_revision(), []))
                builder.finish_inventory()
                builder.commit('Merge %s.' % version)

        tree_id = revtree._lookup_path(u'')[2]
        try:
            pristine_tar_branch = self.branch.controldir.open_branch(
                name='pristine-tar')
        except NotBranchError:
            if force_pristine_tar:
                note('Creating new pristine-tar branch.')
                pristine_tar_branch = self.branch.controldir.create_branch(
                    name='pristine-tar')
            else:
                note('Not storing pristine-tar metadata, '
                     'since there is no pristine-tar branch.')
                pristine_tar_branch = None
        if pristine_tar_branch:
            dest = self.branch.controldir.user_transport.local_abspath('.')
            if committer is None:
                cs = tree.branch.get_config_stack()
                committer = cs.get('email')
            try:
                commit_pristine_tar(
                    dest, tarball, tree_id, committer=committer)
            except PristineTarDeltaExists:
                if reuse_existing:
                    note('Reusing existing tarball, since delta exists.')
                    return tag_name, revid, True
                raise
            else:
                note('Imported %s with pristine-tar.',
                     os.path.basename(tarball))
                pristine_tar_imported = True
        else:
            pristine_tar_imported = False
        mutter(
            'imported %s version %s component %r as revid %s, tagged %s',
            package, version, component, revid, tag_name)
        return tag_name, revid, pristine_tar_imported

    def fetch_component_tarball(self, package, version, component, target_dir):
        note("Using pristine-tar to reconstruct %s/%s.", package, version)
        try:
            target_filename = self.reconstruct_pristine_tar(
                    package, version, component, target_dir)
        except PristineTarError as e:
            warning('Unable to reconstruct %s/%s using pristine tar: %s',
                    package, version, e)
            raise PackageVersionNotPresent(package, version, self)
        return target_filename

    def _has_revision(self, revid, md5=None):
        if not self.branch.repository.has_revision(revid):
            return False
        if self.branch.last_revision() == _mod_revision.NULL_REVISION:
            # there's no explicit upstream branch so.. whatever?
            return True
        with self.branch.lock_read():
            graph = self.branch.repository.get_graph()
            if not graph.is_ancestor(revid, self.branch.last_revision()):
                warning(
                    'Revision %r exists in repository but not in '
                    'upstream branch, ignoring', revid)
                return False
        return True

    def possible_tag_names(self, package: Optional[str], version: str,
                           component: Optional[str], try_hard: bool = True):
        tags = []
        if self.gbp_tag_format:
            tags.append(
                gbp_expand_tag_name(
                    self.gbp_tag_format, mangle_version_for_git(version)))
        tags.extend(possible_upstream_tag_names(
            package, version, component, try_hard=try_hard))

        return tags

    def get_pristine_tar_delta(self, package, version):
        try:
            pristine_tar_branch = self.branch.controldir.open_branch(
                'pristine-tar')
        except NotBranchError:
            pass
        else:
            revtree = pristine_tar_branch.repository.revision_tree(
                pristine_tar_branch.last_revision())
            for suffix in self.SUFFIXES:
                basename = '%s_%s.orig.%s' % (package, version, suffix)
                try:
                    delta_bytes = revtree.get_file_text(basename + '.delta')
                except NoSuchFile:
                    continue
                delta_id = revtree.get_file_text(basename + '.id')
                try:
                    delta_sig = revtree.get_file_text(basename + '.asc')
                except NoSuchFile:
                    delta_sig = None
                return (basename, delta_bytes, delta_id, delta_sig)
        raise PristineTarDeltaAbsent(version)

    def reconstruct_pristine_tar(
            self, package, version, component, target_dir):
        """Reconstruct a pristine-tar tarball from a git revision."""
        try:
            dest_filename, delta_bytes, delta_id, delta_sig = self.get_pristine_tar_delta(
                package, version)
        except PristineTarDeltaAbsent:
            revid = self.version_component_as_revision(
                package, version, component)
            tree = self.branch.repository.revision_tree(revid)
            dest_filename = self._tarball_path(
                package, version, component, target_dir, format='gz')
            export_with_nested(tree, dest_filename, per_file_timestamps=True)
            return dest_filename
        else:
            dest_filename = os.path.join(target_dir, dest_filename)
            try:
                subprocess.check_call(
                    ['pristine-tar', 'checkout', dest_filename],
                    cwd=self.branch.repository.user_transport.local_abspath('.'))
            except subprocess.CalledProcessError as e:
                raise PristineTarError(str(e))
            return dest_filename

    def _components_by_pristine_tar(self, package=None):
        ret = {}
        try:
            pristine_tar_branch = self.branch.controldir.open_branch(
                'pristine-tar')
        except NotBranchError:
            pass
        else:
            revtree = pristine_tar_branch.repository.revision_tree(
                pristine_tar_branch.last_revision())
            for entry in revtree.list_files():
                filename = entry[0]
                # Format: package_version.orig-component.tar.gz.delta
                if not filename.endswith('.delta'):
                    continue
                basename = filename[:-len('.delta')]
                if package is None and not filename.startswith(package + '_'):
                    continue
                try:
                    rest = basename.split('_', 1)[1]
                except IndexError:
                    mutter('Unable to parse filename %r', basename)
                    continue
                for suffix in self.SUFFIXES:
                    if rest.endswith(suffix):
                        rest = rest[:-len(suffix)]
                        break
                else:
                    continue
                if rest.endswith('.orig'):
                    component = None
                    version = rest[:-len('.orig')]
                else:
                    m = re.match('(.*).orig-([^-]+)', rest)
                    if not m:
                        continue
                    component = m.group(2)
                    version = m.group(1)
                ret.setdefault(version, {})[component] = basename
        return ret

    def fetch_tarballs(self, package, version, target_dir, components=None):
        note("Looking for upstream tarball in local branch.")
        if components is None:
            # Scan tags for components
            try:
                components = self._components_by_version()[version].keys()
            except KeyError:
                try:
                    components = self._components_by_pristine_tar(package)[version].keys()
                except KeyError:
                    components = [None]
        return [
            self.fetch_component_tarball(
                package, version, component, target_dir)
            for component in components]

    def _search_for_upstream_version(
            self, package: Optional[str], version: str, component,
            md5=None):
        start_revids = []
        sources = []
        if self.branch.last_revision() != NULL_REVISION:
            sources.append('branch upstream')
            start_revids.append(self.branch.last_revision())
        if self.packaging_branch is not None:
            sources.append('packaging branch')
            start_revids.append(self.packaging_branch.last_revision())
        for tag_name, revid in upstream_version_tag_start_revids(
                self.branch.tags.get_tag_dict(), package, version):
            sources.append('tag %s' % tag_name)
            start_revids.append(revid)

        note('Searching for revision importing %s version %s on %s.',
             package, version, ', '.join(sources))
        revid = search_for_upstream_version(
            self.branch.repository, start_revids, package, version, component,
            md5)
        return revid
