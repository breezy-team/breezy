#    util.py -- Utility functions
#    Copyright (C) 2006 James Westby <jw+debian@jameswestby.net>
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

import errno
import hashlib
import os
import re
import shutil
import signal
import subprocess
import tempfile
from typing import Iterator, Optional, Tuple

from debian import deb822
from debian.changelog import Changelog, ChangelogParseError, Version
from debian.copyright import Copyright, NotMachineReadableError
from debmutate.changelog import (
    changes_by_author,
    find_extra_authors,
    find_last_distribution,
    find_thanks,
    strip_changelog_message,
)
from debmutate.versions import get_snapshot_revision

from ... import (
    bugtracker,
    errors,
    osutils,
    urlutils,
)
from ...export import export
from ...trace import (
    mutter,
    note,
    warning,
)
from ...transport import (
    NoSuchFile,
    do_catching_redirections,
    get_transport,
)
from ...tree import Tree
from . import (
    global_conf,
)
from .config import (
    BUILD_TYPE_MERGE,
    BUILD_TYPE_NATIVE,
    BUILD_TYPE_NORMAL,
    DebBuildConfig,
)
from .errors import (
    BzrError,
)

BUILDDEB_DIR = ".bzr-builddeb"

NEW_LOCAL_CONF = "debian/local.conf.local"
NEW_CONF = "debian/bzr-builddeb.conf"
DEFAULT_CONF = os.path.join(BUILDDEB_DIR, "default.conf")
LOCAL_CONF = os.path.join(BUILDDEB_DIR, "local.conf")


class MissingChangelogError(BzrError):
    _fmt = "Could not find changelog at %(location)s in tree."

    def __init__(self, locations):
        BzrError.__init__(self, location=locations)


_DEBIAN_RELEASES = None
_UBUNTU_RELEASES = None


def _get_release_names():
    global _DEBIAN_RELEASES, _UBUNTU_RELEASES
    try:
        from distro_info import DebianDistroInfo, UbuntuDistroInfo
    except ImportError:
        warning(
            "distro_info not available. Unable to retrieve current " "list of releases."
        )
        _DEBIAN_RELEASES = []
        _UBUNTU_RELEASES = []
    else:
        # distro info is not available
        _DEBIAN_RELEASES = DebianDistroInfo().all
        _UBUNTU_RELEASES = UbuntuDistroInfo().all

    _DEBIAN_RELEASES.extend(["stable", "testing", "unstable", "frozen"])


def debian_releases():
    if _DEBIAN_RELEASES is None:
        _get_release_names()
    return _DEBIAN_RELEASES


def ubuntu_releases():
    if _UBUNTU_RELEASES is None:
        _get_release_names()
    return _UBUNTU_RELEASES


DEBIAN_POCKETS = ("", "-security", "-proposed-updates", "-backports")
UBUNTU_POCKETS = ("", "-proposed", "-updates", "-security", "-backports")


def recursive_copy(fromdir, todir):
    """Copy the contents of fromdir to todir.

    Like shutil.copytree, but the destination directory must already exist
    with this method, rather than not exists for shutil.
    """
    mutter("Copying %s to %s", fromdir, todir)
    for entry in os.listdir(fromdir):
        path = os.path.join(fromdir, entry)
        if os.path.isdir(path):
            tosubdir = os.path.join(todir, entry)
            if not os.path.exists(tosubdir):
                os.mkdir(tosubdir)
            recursive_copy(path, tosubdir)
        else:
            # Python 3 has a follow_symlinks argument to shutil.copy, but
            # Python 2 does not...
            if os.path.islink(path):
                os.symlink(os.readlink(path), os.path.join(todir, entry))
            else:
                shutil.copy(path, todir)


class AddChangelogError(BzrError):
    _fmt = 'Please add "%(changelog)s" to the branch using bzr add.'

    def __init__(self, changelog):
        BzrError.__init__(self, changelog=changelog)


def find_changelog(t, subpath="", merge=False, max_blocks=1, strict=False):
    """Find the changelog in the given tree.

    First looks for 'debian/changelog'. If "merge" is true will also
    look for 'changelog'.

    The returned changelog is created with 'allow_empty_author=True'
    as some people do this but still want to build.
    'max_blocks' defaults to 1 to try and prevent old broken
    changelog entries from causing the command to fail.

    "top_level" is a subset of "merge" mode. It indicates that the
    '.bzr' dir is at the same level as 'changelog' etc., rather
    than being at the same level as 'debian/'.

    :param t: the Tree to look in.
    :param merge: whether this is a "merge" package.
    :param max_blocks: Number of max_blocks to parse (defaults to 1). Use None
        to parse the entire changelog.
    :return: (changelog, top_level) where changelog is the Changelog,
        and top_level is a boolean indicating whether the file is
        located at 'changelog' (rather than 'debian/changelog') if
        merge was given, False otherwise.
    """
    top_level = False
    with t.lock_read():
        changelog_file = osutils.pathjoin(subpath, "debian/changelog")
        if not t.has_filename(changelog_file):
            checked_files = [changelog_file]
            if merge:
                # Assume LarstiQ's layout (.bzr in debian/)
                changelog_file = osutils.pathjoin(subpath, "changelog")
                top_level = True
                if not t.has_filename(changelog_file):
                    checked_files.append(changelog_file)
                    changelog_file = None
            else:
                changelog_file = None
            if changelog_file is None:
                if getattr(t, "abspath", None):
                    checked_files = [t.abspath(f) for f in checked_files]
                raise MissingChangelogError(" or ".join(checked_files))
        elif merge and t.has_filename(osutils.pathjoin(subpath, "changelog")):
            # If it is a "top_level" package and debian is a symlink to
            # "." then it will have found debian/changelog. Try and detect
            # this.
            debian_file = osutils.pathjoin(subpath, "debian")
            if (
                t.is_versioned(debian_file)
                and t.kind(debian_file) == "symlink"
                and t.get_symlink_target(debian_file) == "."
            ):
                changelog_file = "changelog"
                top_level = True
        mutter("Using '%s' to get package information", changelog_file)
        if not t.is_versioned(changelog_file):
            raise AddChangelogError(changelog_file)
        contents = t.get_file_text(changelog_file)
    changelog = Changelog()
    changelog.parse_changelog(
        contents, max_blocks=max_blocks, allow_empty_author=True, strict=strict
    )
    return changelog, top_level


def tarball_name(package, version, component=None, format=None):
    """Return the name of the .orig.tar.gz for the given package and version.

    :param package: the name of the source package.
    :param version: the upstream version of the package.
    :param component: Component name (None for base)
    :param format: the format for the tarball. If None then 'gz' will be
         used. You probably want on of 'gz', 'bz2', 'lzma' or 'xz'.
    :return: a string that is the name of the upstream tarball to use.
    """
    if format is None:
        format = "gz"
    name = f"{package}_{version!s}.orig"
    if component is not None:
        name += "-" + component
    return f"{name}.tar.{format}"


def suite_to_distribution(suite):
    """Infer the distribution from a suite.

    When passed the name of a suite (anything in the distributions field of
    a changelog) it will infer the distribution from that (i.e. Debian or
    Ubuntu).

    :param suite: the string containing the suite
    :return: "debian", "ubuntu", or None if the distribution couldn't be
        inferred.
    """
    all_debian = [r + t for r in debian_releases() for t in DEBIAN_POCKETS]
    all_ubuntu = [r + t for r in ubuntu_releases() for t in UBUNTU_POCKETS]
    if suite in all_debian:
        return "debian"
    if suite in all_ubuntu:
        return "ubuntu"
    if suite == "kali" or suite.startswith("kali-"):
        return "kali"
    return None


def lookup_distribution(distribution_or_suite):
    """Get the distribution name based on a distribution or suite name.

    :param distribution_or_suite: a string that is either the name of
        a distribution or a suite.
    :return: a string with a distribution name or None.
    """
    if distribution_or_suite.lower() in ("debian", "ubuntu"):
        return distribution_or_suite.lower()
    return suite_to_distribution(distribution_or_suite)


def md5sum_filename(filename):
    """Calculate the md5sum of a file by name.

    :param filename: Path of the file to checksum
    :return: MD5 Checksum as hex digest
    """
    m = hashlib.md5()  # noqa: S324
    with open(filename, "rb") as f:
        for line in f:
            m.update(line)
    return m.hexdigest()


def move_file_if_different(source, target, md5sum):
    """Overwrite a file if its new contents would be different from the current
    contents.

    :param source: Path of the source file
    :param target: Path of the target file
    :param md5sum: MD5Sum (as hex digest) of the source file
    """
    if os.path.exists(target):
        if os.path.samefile(source, target):
            return
        t_md5sum = md5sum_filename(target)
        if t_md5sum == md5sum:
            return
    shutil.move(source, target)


def write_if_different(contents, target):
    """(Over)write a file with `contents` if they are different from its
    current content.

    :param contents: The contents to write, as a string
    :param target: Path of the target file
    """
    md5sum = hashlib.md5()  # noqa: S324
    md5sum.update(contents)
    fd, temp_path = tempfile.mkstemp("builddeb-rename-")
    fobj = os.fdopen(fd, "wb")
    try:
        try:
            fobj.write(contents)
        finally:
            fobj.close()
        move_file_if_different(temp_path, target, md5sum.hexdigest())
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def _download_part(name, base_transport, target_dir, md5sum):
    part_base_dir, part_path = urlutils.split(name)
    f_t = base_transport
    if part_base_dir != "":
        f_t = base_transport.clone(part_base_dir)
    with f_t.get(part_path) as f_f:
        target_path = os.path.join(target_dir, part_path)
        fd, temp_path = tempfile.mkstemp(prefix="builddeb-")
        fobj = os.fdopen(fd, "wb")
        try:
            try:
                shutil.copyfileobj(f_f, fobj)
            finally:
                fobj.close()
            move_file_if_different(temp_path, target_path, md5sum)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


def open_file(url):
    """Open a file from a URL.

    :param url: URL to open
    :return: A file-like object.
    """
    filename, transport = open_transport(url)
    return open_file_via_transport(filename, transport)


def open_transport(path):
    """Obtain an appropriate transport instance for the given path."""
    base_dir, path = urlutils.split(path)
    transport = get_transport(base_dir)
    return (path, transport)


def open_file_via_transport(filename, transport):
    """Open a file using the transport, follow redirects as necessary."""

    def open_file(transport):
        return transport.get(filename)

    def follow_redirection(transport, e, redirection_notice):
        mutter(redirection_notice)
        _filename, redirected_transport = open_transport(e.target)
        return redirected_transport

    result = do_catching_redirections(open_file, transport, follow_redirection)
    return result


def _dget(cls, dsc_location, target_dir):
    """Copy all files referenced by a .dsc file.

    Args:
      cls: Parser class
      dsc_location: Source file location
      target_dir: Target directory
    Return:
      path to target source file
    """
    if not os.path.isdir(target_dir):
        raise errors.NotADirectory(target_dir)
    path, dsc_t = open_transport(dsc_location)
    with open_file_via_transport(path, dsc_t) as f:
        dsc_contents = f.read()
    dsc = cls(dsc_contents)
    for file_details in dsc["files"]:
        name = file_details["name"]
        _download_part(name, dsc_t, target_dir, file_details["md5sum"])
    target_file = os.path.join(target_dir, path)
    write_if_different(dsc_contents, target_file)
    return target_file


def dget(dsc_location, target_dir):
    return _dget(deb822.Dsc, dsc_location, target_dir)


def dget_changes(changes_location, target_dir):
    return _dget(deb822.Changes, changes_location, target_dir)


def get_parent_dir(target):
    parent = os.path.dirname(target)
    if os.path.basename(target) == "":
        parent = os.path.dirname(parent)
    return parent


def find_bugs_fixed(changes, branch, _lplib=None):
    """Find the bugs marked fixed in a changelog entry.

    :param changes: A list of the contents of the changelog entry.
    :param branch: Bazaar branch associated with the package
    :return: String with bugs closed, as appropriate for a Bazaar "bugs"
        revision property.
    """
    if _lplib is None:
        from . import launchpad as _lplib
    bugs = []
    for _new_author, _linenos, lines in changes_by_author(changes):
        for match in re.finditer(
            "closes:\\s*(?:bug)?\\#?\\s?\\d+" "(?:,\\s*(?:bug)?\\#?\\s?\\d+)*",
            "".join(lines),
            re.IGNORECASE,
        ):
            closes_list = match.group(0)
            for match in re.finditer("\\d+", closes_list):
                bug_url = bugtracker.get_bug_url("deb", branch, match.group(0))
                bugs.append(bug_url + " fixed")
                lp_bugs = _lplib.ubuntu_bugs_for_debian_bug(match.group(0))
                if len(lp_bugs) == 1:
                    bug_url = bugtracker.get_bug_url("lp", branch, lp_bugs[0])
                    bugs.append(bug_url + " fixed")
        for match in re.finditer(
            "lp:\\s+\\#\\d+(?:,\\s*\\#\\d+)*", "".join(lines), re.IGNORECASE
        ):
            closes_list = match.group(0)
            for match in re.finditer("\\d+", closes_list):
                bug_url = bugtracker.get_bug_url("lp", branch, match.group(0))
                bugs.append(bug_url + " fixed")
                deb_bugs = _lplib.debian_bugs_for_ubuntu_bug(match.group(0))
                if len(deb_bugs) == 1:
                    bug_url = bugtracker.get_bug_url("deb", branch, deb_bugs[0])
                    bugs.append(bug_url + " fixed")
    return bugs


def get_commit_info_from_changelog(changelog, branch, _lplib=None):
    """Retrieves the messages from the last section of debian/changelog.

    Reads the latest stanza of debian/changelog and returns the
    text of the changes in that section. It also returns other
    information about the change, including the authors of the change,
    anyone that is thanked, and the bugs that are declared fixed by it.

    :return: a tuple (message, authors, thanks, bugs). message is the
        commit message that should be used. authors is a list of strings,
        with those that contributed to the change, thanks is a list
        of string, with those who were thanked in the changelog entry.
        bugs is a list of bug URLs like for --fixes.
        If the information is not available then any can be None.
    """
    message = None
    authors = []
    thanks = []
    bugs = []
    if changelog._blocks:
        block = changelog._blocks[0]
        authors = [block.author]
        authors += find_extra_authors(block.changes())
        changes = strip_changelog_message(block.changes())
        bugs = find_bugs_fixed(block.changes(), branch, _lplib=_lplib)
        thanks = find_thanks(block.changes())
        message = "\n".join(changes).replace("\r", "")
    return (message, authors, thanks, bugs)


def subprocess_setup():
    # Python installs a SIGPIPE handler by default. This is usually not what
    # non-Python subprocesses expect.
    # Many, many thanks to Colin Watson
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)


def debuild_config(tree, subpath):
    """Obtain the Debuild configuration object.

    :param tree: A Tree object, can be a WorkingTree or RevisionTree.
    """
    config_files = []
    user_config = None
    if subpath in (".", None):
        subpath = ""
    new_local_conf = osutils.pathjoin(subpath, NEW_LOCAL_CONF)
    local_conf = osutils.pathjoin(subpath, LOCAL_CONF)
    new_conf = osutils.pathjoin(subpath, NEW_CONF)
    default_conf = osutils.pathjoin(subpath, DEFAULT_CONF)

    if tree.has_filename(new_local_conf):
        if not tree.is_versioned(new_local_conf):
            config_files.append((tree.get_file(new_local_conf), True, "local.conf"))
        else:
            warning(
                "Not using configuration from %s as it is versioned.", new_local_conf
            )
    if tree.has_filename(local_conf):
        if not tree.is_versioned(local_conf):
            config_files.append((tree.get_file(local_conf), True, "local.conf"))
        else:
            warning("Not using configuration from %s as it is versioned.", local_conf)
    config_files.append((global_conf(), True))
    user_config = global_conf()
    if tree.is_versioned(new_conf):
        config_files.append((tree.get_file(new_conf), False, "bzr-builddeb.conf"))
    if tree.is_versioned(default_conf):
        config_files.append((tree.get_file(default_conf), False, "default.conf"))
    config = DebBuildConfig(config_files, tree=tree)
    config.set_user_config(user_config)
    return config


class UnableToFindPreviousUpload(BzrError):
    _fmt = "Unable to determine the previous upload for --package-merge."


def find_previous_upload(tree, subpath, merge=False):
    """Given a tree, find the previous upload to the distribution.

    When e.g. Ubuntu merges from Debian they want to build with
    -vPREV_VERSION. Here's where we find that previous version.

    We look at the last changelog entry and find the upload target.
    We then search backwards until we find the same target. That's
    the previous version that we return.

    We require there to be a previous version, otherwise we throw
    an error.

    It's not a simple string comparison to find the same target in
    a previous version, as we should consider old series in e.g.
    Ubuntu.
    """
    try:
        cl, _top_level = find_changelog(tree, subpath, merge, max_blocks=None)
    except ChangelogParseError as ex:
        raise UnableToFindPreviousUpload() from ex
    return changelog_find_previous_upload(cl)


class NoPreviousUpload(BzrError):
    _fmt = "There was no previous upload to %(distribution)s."

    def __init__(self, distribution):
        BzrError.__init__(self, distribution=distribution)


def changelog_find_previous_upload(cl):
    """Find the version of the previous upload.

    :param cl: Changelog object
    :return: Version object for the previous upload
    :raise NoPreviousUpload: Raised when there is no previous upload
    """
    current_target = find_last_distribution(cl)
    all_debian = [r + t for r in debian_releases() for t in DEBIAN_POCKETS]
    all_ubuntu = [r + t for r in ubuntu_releases() for t in UBUNTU_POCKETS]
    if current_target in all_debian:
        match_targets = (current_target,)
    elif current_target in all_ubuntu:
        match_targets = ubuntu_releases()
        if "-" in current_target:
            match_targets += tuple(
                [current_target.split("-", 1)[0] + t for t in UBUNTU_POCKETS]
            )
    else:
        # If we do not recognize the current target in order to apply special
        # rules to it, then just assume that only previous uploads to exactly
        # the same target count.
        match_targets = (current_target,)
    for block in cl._blocks[1:]:
        if block.distributions.split(" ")[0] in match_targets:
            return block.version
    raise NoPreviousUpload(current_target)


def tree_contains_upstream_source(tree, subpath=""):
    """Guess if the specified tree contains the upstream source.

    :param tree: A RevisionTree.
    :return: Boolean indicating whether or not the tree contains the upstream
        source. None if the tree is empty
    """
    present_files = {
        f[0] for f in tree.list_files(recursive=False, from_dir=subpath) if f[1] == "V"
    }
    if len(present_files) == 0:
        return None
    packaging_files = frozenset(["debian", ".bzr-builddeb", ".bzrignore", ".gitignore"])
    return len(present_files - packaging_files) > 0


def tree_get_source_format(tree, subpath=""):
    """Retrieve the source format name from a package.

    :param path: Path to the package
    :return: String with package format
    """
    filename = osutils.pathjoin(subpath, "debian/source/format")
    try:
        text = tree.get_file_text(filename)
    except OSError as ex:
        if ex.errno == errno.ENOENT:
            return FORMAT_1_0
        raise
    except NoSuchFile:
        return FORMAT_1_0
    return text.strip().decode("ascii")


FORMAT_1_0 = "1.0"
FORMAT_3_0_QUILT = "3.0 (quilt)"
FORMAT_3_0_NATIVE = "3.0 (native)"

NATIVE_SOURCE_FORMATS = [FORMAT_3_0_NATIVE]
NORMAL_SOURCE_FORMATS = [FORMAT_3_0_QUILT]


class InconsistentSourceFormatError(BzrError):
    _fmt = (
        "Inconsistency between source format and version: "
        "version %(version)s is %(version_bool)snative, "
        "format '%(format)s' is %(format_bool)snative."
    )

    def __init__(self, version_native, format_native, version_str, format_str):
        if version_native:
            version_bool = ""
        else:
            version_bool = "not "
        if format_native:
            format_bool = ""
        else:
            format_bool = "not "
        BzrError.__init__(
            self,
            version_bool=version_bool,
            format_bool=format_bool,
            version=version_str,
            format=format_str,
        )


def guess_build_type(tree, version, subpath="", contains_upstream_source=True):
    """Guess the build type based on the contents of a tree.

    :param tree: A `Tree` object.
    :param version: `Version` of the upload.
    :param contains_upstream_source: Whether this branch contains the upstream
        source.
    :return: A build_type value.
    """
    source_format = tree_get_source_format(tree, subpath)
    if source_format in NATIVE_SOURCE_FORMATS:
        format_native = True
    elif source_format in NORMAL_SOURCE_FORMATS:
        format_native = False
    else:
        format_native = None

    if version is not None:
        version_native = not version.debian_version
    else:
        version_native = None

    # If the package doesn't have a debian revision then it is very probably
    # native, but it *could* be native.
    if isinstance(version_native, bool) and isinstance(format_native, bool):
        if version_native is True and format_native is False:
            raise InconsistentSourceFormatError(
                version_native, format_native, version, source_format
            )
        if version_native is False and format_native is True:
            warning(
                "Version (%s) suggests non-native package, "
                "but format (%s) is for native.",
                version,
                source_format,
            )

    if version_native or format_native:
        return BUILD_TYPE_NATIVE
    if contains_upstream_source is False:
        # Default to merge mode if there's only a debian/ directory
        return BUILD_TYPE_MERGE
    else:
        return BUILD_TYPE_NORMAL


def component_from_orig_tarball(tarball_filename, package, version):
    tarball_filename = os.path.basename(tarball_filename)
    prefix = f"{package}_{version}.orig"
    if not tarball_filename.startswith(prefix):
        raise ValueError(
            f"invalid orig tarball file {tarball_filename} "
            f"does not have expected prefix {prefix}"
        )
    base = tarball_filename[len(prefix) :]
    for ext in (".tar.gz", ".tar.bz2", ".tar.lzma", ".tar.xz"):
        if tarball_filename.endswith(ext):
            base = base[: -len(ext)]
            break
    else:
        raise ValueError(f"orig tarball file {tarball_filename} has unknown extension")
    if base == "":
        return None
    elif base[0] == "-":
        # Extra component
        return base[1:]
    else:
        raise ValueError(
            f"Invalid extra characters in tarball filename {tarball_filename}"
        )


class TarFailed(BzrError):
    _fmt = (
        "There was an error executing tar to %(operation)s %(tarball)s: " "%(error)s."
    )

    def __init__(self, operation, tarball, error):
        BzrError.__init__(self, operation=operation, tarball=tarball, error=error)


def needs_strip_components(tf):
    top_level_directories = set()
    for name in tf.getnames():
        top_level_directories.add(name.split("/")[0])
    return len(top_level_directories) == 1


def extract_orig_tarball(
    tarball_filename, component, target, strip_components: Optional[int] = None
) -> None:
    """Extract an orig tarball.

    :param tarball: Path to the tarball
    :param component: Component name (or None for top-level)
    :param target: Target path
    """
    from tarfile import TarFile

    tar_args = ["tar"]
    if tarball_filename.endswith(".tar.bz2"):
        tar_args.append("xjf")
        tf = TarFile.bz2open(tarball_filename)
    elif tarball_filename.endswith(".tar.lzma") or tarball_filename.endswith(".tar.xz"):
        tar_args.append("xJf")
        tf = TarFile.xzopen(tarball_filename)
    elif tarball_filename.endswith(".tar"):
        tar_args.append("xf")
        tf = TarFile.open(tarball_filename)
    elif tarball_filename.endswith(".tar.gz") or tarball_filename.endswith(".tgz"):
        tf = TarFile.gzopen(tarball_filename)
        tar_args.append("xzf")
    else:
        note("Unable to figure out type of %s, " "assuming .tar.gz", tarball_filename)
        tf = TarFile.gzopen(tarball_filename)
        tar_args.append("xzf")

    try:
        if strip_components is None:
            if needs_strip_components(tf):
                strip_components = 1
            else:
                strip_components = 0
    finally:
        tf.close()
    if component is not None:
        target_path = os.path.join(target, component)
        os.mkdir(target_path)
    else:
        target_path = target
    tar_args.extend([tarball_filename, "-C", target_path])
    if strip_components is not None:
        tar_args.extend(["--strip-components", str(strip_components)])
    proc = subprocess.Popen(
        tar_args, preexec_fn=subprocess_setup, stderr=subprocess.PIPE
    )
    (stdout, stderr) = proc.communicate()
    if proc.returncode != 0:
        raise TarFailed("extract", tarball_filename, error=stderr)


def extract_orig_tarballs(tarballs, target, strip_components=None):
    """Extract orig tarballs to a directory.

    :param tarballs: List of tarball filenames
    :param target: Target directory (must already exist)
    """
    for tarball_filename, component in tarballs:
        extract_orig_tarball(
            tarball_filename, component, target, strip_components=strip_components
        )


def dput_changes(path: str) -> None:
    """Upload a package."""
    (bd, changes_file) = os.path.split(path)
    subprocess.check_call(["dput", changes_file], cwd=bd)  # noqa: S607


def find_changes_files(
    path: str, package: str, version: Version
) -> Iterator[Tuple[str, os.DirEntry]]:
    non_epoch_version = version.upstream_version
    assert non_epoch_version is not None  # noqa: S101
    if version.debian_version is not None:
        non_epoch_version += "-{}".format(version.debian_version)
    c = re.compile(f"{re.escape(package)}_{re.escape(non_epoch_version)}_(.*).changes")
    for entry in os.scandir(path):
        m = c.match(entry.name)
        if m:
            yield m.group(1), entry


def get_files_excluded(tree, subpath="", top_level=False):
    if top_level:
        path = os.path.join(subpath, "copyright")
    else:
        path = os.path.join(subpath, "debian", "copyright")
    with tree.get_file(path) as f:
        try:
            copyright = Copyright(f, strict=False)
        except NotMachineReadableError:
            return []
        try:
            return copyright.header["Files-Excluded"].split()
        except KeyError:
            return []


def control_files_in_root(tree: Tree, subpath: str) -> bool:
    debian_path = os.path.join(subpath, "debian")
    if tree.has_filename(debian_path):
        return False
    control_path = os.path.join(subpath, "control")
    if tree.has_filename(control_path):
        return True
    if tree.has_filename(control_path + ".in"):
        return True
    return False


def full_branch_url(branch):
    """Get the full URL for a branch.

    Ideally this should just return Branch.user_url,
    but that currently exclude the branch name
    in some situations.
    """
    if branch.name is None:
        return branch.user_url
    url, params = urlutils.split_segment_parameters(branch.user_url)
    if branch.name != "":
        params["branch"] = urlutils.quote(branch.name, "")
    return urlutils.join_segment_parameters(url, params)


def detect_version_kind(upstream_version):
    """Detect the version kind from the upstream version."""
    snapshot_info = get_snapshot_revision(upstream_version)
    if snapshot_info is None:
        return "release"
    return "snapshot"


def export_with_nested(tree, dest, **kwargs):
    with tree.lock_read():
        try:
            return export(tree, dest, recurse_nested=True, **kwargs)
        except BaseException:
            if os.path.isfile(dest):
                os.unlink(dest)
            raise


def debsign(path: str, keyid: Optional[str] = None) -> None:
    (bd, changes_file) = os.path.split(path)
    args = ["debsign"]
    if keyid:
        args.append("-k{}".format(keyid))
    args.append(changes_file)
    subprocess.check_call(args, cwd=bd)
