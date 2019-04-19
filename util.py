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

from __future__ import absolute_import

import errno
try:
    import hashlib as md5
except ImportError:
    import md5
import signal
import shutil
import subprocess
import tempfile
import os
import re

from debian import deb822
from debian.changelog import Changelog, ChangelogParseError

from ... import (
    bugtracker,
    errors,
    urlutils,
    version_info as bzr_version_info,
    )
from ...sixish import text_type
from ...trace import (
    mutter,
    warning,
    )
from ...transport import (
    do_catching_redirections,
    get_transport,
    )
from . import (
    default_conf,
    local_conf,
    global_conf,
    new_conf,
    new_local_conf,
    )
from .config import (
    DebBuildConfig,
    BUILD_TYPE_MERGE,
    BUILD_TYPE_NATIVE,
    BUILD_TYPE_NORMAL,
    )
from .errors import (
    BzrError,
    MissingChangelogError,
    AddChangelogError,
    InconsistentSourceFormatError,
    NoPreviousUpload,
    TarFailed,
    UnableToFindPreviousUpload,
    UnparseableChangelog,
    )

_DEBIAN_RELEASES = None
_UBUNTU_RELEASES = None

def _get_release_names():
    global _DEBIAN_RELEASES, _UBUNTU_RELEASES
    try:
        from distro_info import DebianDistroInfo, UbuntuDistroInfo
    except ImportError:
        warning("distro_info not available. Unable to retrieve current "
            "list of releases.")
        _DEBIAN_RELEASES = []
        _UBUNTU_RELEASES = []
    else:
        # distro info is not available
        _DEBIAN_RELEASES = DebianDistroInfo().all
        _UBUNTU_RELEASES = UbuntuDistroInfo().all

    _DEBIAN_RELEASES.extend(['stable', 'testing', 'unstable', 'frozen'])


def debian_releases():
    if _DEBIAN_RELEASES is None:
        _get_release_names()
    return _DEBIAN_RELEASES

def ubuntu_releases():
    if _UBUNTU_RELEASES is None:
        _get_release_names()
    return _UBUNTU_RELEASES

DEBIAN_POCKETS = ('', '-security', '-proposed-updates', '-backports')
UBUNTU_POCKETS = ('', '-proposed', '-updates', '-security', '-backports')


def safe_decode(s):
    """Decode a string into a Unicode value."""
    if isinstance(s, text_type): # Already unicode
        mutter('safe_decode() called on an already-decoded string: %r' % (s,))
        return s
    try:
        return s.decode('utf-8')
    except UnicodeDecodeError as e:
        mutter('safe_decode(%r) falling back to iso-8859-1' % (s,))
        # TODO: Looking at BeautifulSoup it seems to use 'chardet' to try to
        #       guess the encoding of a given text stream. We might want to
        #       take a closer look at that.
        # TODO: Another possibility would be to make the fallback encoding
        #       configurable, possibly exposed as a command-line flag, for now,
        #       this seems 'good enough'.
        return s.decode('iso-8859-1')


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
            shutil.copy(path, todir)


def find_changelog(t, merge=False, max_blocks=1):
    """Find the changelog in the given tree.

    First looks for 'debian/changelog'. If "merge" is true will also
    look for 'changelog'.

    The returned changelog is created with 'allow_empty_author=True'
    as some people do this but still want to build.
    'max_blocks' defaults to 1 to try and prevent old broken
    changelog entries from causing the command to fail, 

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
        changelog_file = 'debian/changelog'
        if not t.has_filename(changelog_file):
            checked_files = ['debian/changelog']
            if merge:
                # Assume LarstiQ's layout (.bzr in debian/)
                changelog_file = 'changelog'
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
        elif merge and t.has_filename('changelog'):
            # If it is a "top_level" package and debian is a symlink to
            # "." then it will have found debian/changelog. Try and detect
            # this.
            if (t.is_versioned('debian') and
                t.kind('debian') == 'symlink' and
                t.get_symlink_target('debian') == '.'):
                changelog_file = 'changelog'
                top_level = True
        mutter("Using '%s' to get package information", changelog_file)
        if not t.is_versioned(changelog_file):
            raise AddChangelogError(changelog_file)
        contents = t.get_file_text(changelog_file)
    changelog = Changelog()
    try:
        changelog.parse_changelog(contents, max_blocks=max_blocks, allow_empty_author=True)
    except ChangelogParseError as e:
        raise UnparseableChangelog(str(e))
    return changelog, top_level


def strip_changelog_message(changes):
    """Strip a changelog message like debcommit does.

    Takes a list of changes from a changelog entry and applies a transformation
    so the message is well formatted for a commit message.

    :param changes: a list of lines from the changelog entry
    :return: another list of lines with blank lines stripped from the start
        and the spaces the start of the lines split if there is only one logical
        entry.
    """
    if not changes:
        return changes
    while changes and changes[-1] == '':
        changes.pop()
    while changes and changes[0] == '':
        changes.pop(0)

    whitespace_column_re = re.compile(r'  |\t')
    changes = [whitespace_column_re.sub('', line, 1) for line in changes]

    leader_re = re.compile(r'[ \t]*[*+-] ')
    count = len([l for l in changes if leader_re.match(l)])
    if count == 1:
        return [leader_re.sub('', line, 1).lstrip() for line in changes]
    else:
        return changes


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
        format = 'gz'
    name = "%s_%s.orig" % (package, str(version))
    if component is not None:
        name += "-" + component
    return "%s.tar.%s" % (name, format)


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
    return None


def lookup_distribution(distribution_or_suite):
    """Get the distribution name based on a distribtion or suite name.

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
    m = md5.md5()
    f = open(filename, 'rb')
    try:
        for line in f:
            m.update(line)
    finally:
        f.close()
    return m.hexdigest()


def move_file_if_different(source, target, md5sum):
    """Overwrite a file if its new contents would be different from the current contents.

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
    """(Over)write a file with `contents` if they are different from its current content.

    :param contents: The contents to write, as a string
    :param target: Path of the target file
    """
    md5sum = md5.md5()
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
    if part_base_dir != '':
        f_t = base_transport.clone(part_base_dir)
    f_f = f_t.get(part_path)
    try:
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
    finally:
        f_f.close()


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
    dsc_contents = open_file_via_transport(path, dsc_t).read()
    dsc = cls(dsc_contents)
    for file_details in dsc['files']:
        name = file_details['name']
        _download_part(name, dsc_t, target_dir, file_details['md5sum'])
    target_file = os.path.join(target_dir, path)
    write_if_different(dsc_contents, target_file)
    return target_file


def dget(dsc_location, target_dir):
    return _dget(deb822.Dsc, dsc_location, target_dir)


def dget_changes(changes_location, target_dir):
    return _dget(deb822.Changes, changes_location, target_dir)


def get_parent_dir(target):
    parent = os.path.dirname(target)
    if os.path.basename(target) == '':
        parent = os.path.dirname(parent)
    return parent


def find_bugs_fixed(changes, branch, _lplib=None):
    """Find the bugs marked fixed in a changelog entry.

    :param changes: A list of the contents of the changelog entry.
    :param branch: Bazaar branch associated with the package
    :return: String with bugs closed, as appropriate for a Bazaar "bugs" revision 
        property.
    """
    if _lplib is None:
        from . import launchpad as _lplib
    bugs = []
    for change in changes:
        for match in re.finditer("closes:\\s*(?:bug)?\\#?\\s?\\d+"
                "(?:,\\s*(?:bug)?\\#?\\s?\\d+)*", change,
                re.IGNORECASE):
            closes_list = match.group(0)
            for match in re.finditer("\\d+", closes_list):
                bug_url = bugtracker.get_bug_url("deb", branch, match.group(0))
                bugs.append(bug_url + " fixed")
                lp_bugs = _lplib.ubuntu_bugs_for_debian_bug(match.group(0))
                if len(lp_bugs) == 1:
                    bug_url = bugtracker.get_bug_url("lp", branch, lp_bugs[0])
                    bugs.append(bug_url + " fixed")
        for match in re.finditer("lp:\\s+\\#\\d+(?:,\\s*\\#\\d+)*",
                change, re.IGNORECASE):
            closes_list = match.group(0)
            for match in re.finditer("\\d+", closes_list):
                bug_url = bugtracker.get_bug_url("lp", branch, match.group(0))
                bugs.append(bug_url + " fixed")
                deb_bugs = _lplib.debian_bugs_for_ubuntu_bug(match.group(0))
                if len(deb_bugs) == 1:
                    bug_url = bugtracker.get_bug_url("deb", branch, deb_bugs[0])
                    bugs.append(bug_url + " fixed")
    return bugs


def find_extra_authors(changes):
    """Find additional authors from a changelog entry.

    :return: List of fullnames of additional authors, without e-mail address.
    """
    extra_author_re = re.compile(r"\s*\[([^\]]+)]\s*")
    authors = []
    for change in changes:
        # Parse out any extra authors.
        match = extra_author_re.match(change)
        if match is not None:
            new_author = safe_decode(match.group(1).strip())
            already_included = False
            for author in authors:
                if author.startswith(new_author):
                    already_included = True
                    break
            if not already_included:
                authors.append(new_author)
    return authors


def find_thanks(changes):
    """Find all people thanked in a changelog entry.

    :param changes: String with the contents of the changelog entry
    :return: List of people thanked, optionally including email address.
    """
    thanks_re = re.compile(r"[tT]hank(?:(?:s)|(?:you))(?:\s*to)?"
            "((?:\\s+(?:(?:\\w\\.)|(?:\\w+(?:-\\w+)*)))+"
            "(?:\\s+<[^@>]+@[^@>]+>)?)",
            re.UNICODE)
    thanks = []
    changes_str = safe_decode(" ".join(changes))
    for match in thanks_re.finditer(changes_str):
        if thanks is None:
            thanks = []
        thanks_str = match.group(1).strip()
        thanks_str = re.sub(r"\s+", " ", thanks_str)
        thanks.append(thanks_str)
    return thanks


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
        authors = [safe_decode(block.author)]
        changes = strip_changelog_message(block.changes())
        authors += find_extra_authors(changes)
        bugs = find_bugs_fixed(changes, branch, _lplib=_lplib)
        thanks = find_thanks(changes)
        message = safe_decode("\n".join(changes).replace("\r", ""))
    return (message, authors, thanks, bugs)


def find_last_distribution(changelog):
    """Find the last changelog that was used in a changelog.

    This will skip stanzas with the 'UNRELEASED' distribution.

    :param changelog: Changelog to analyze
    """
    for block in changelog._blocks:
        distribution = block.distributions.split(" ")[0]
        if distribution != "UNRELEASED":
            return distribution
    return None


def subprocess_setup():
    # Python installs a SIGPIPE handler by default. This is usually not what
    # non-Python subprocesses expect.
    # Many, many thanks to Colin Watson
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)


def debuild_config(tree, working_tree):
    """Obtain the Debuild configuration object.

    :param tree: A Tree object, can be a WorkingTree or RevisionTree.
    :param working_tree: Whether the tree is a working tree.
    """
    config_files = []
    user_config = None
    if (working_tree and tree.has_filename(new_local_conf)):
        if not tree.is_versioned(new_local_conf):
            config_files.append((tree.get_file(new_local_conf), True,
                        "local.conf"))
        else:
            warning('Not using configuration from %s as it is versioned.',
                    new_local_conf)
    if (working_tree and tree.has_filename(local_conf)):
        if not tree.is_versioned(local_conf):
            config_files.append((tree.get_file(local_conf), True,
                        "local.conf"))
        else:
            warning('Not using configuration from %s as it is versioned.',
                    local_conf)
    config_files.append((global_conf(), True))
    user_config = global_conf()
    if tree.is_versioned(new_conf):
        config_files.append((tree.get_file(new_conf), False,
                    "bzr-builddeb.conf"))
    if tree.is_versioned(default_conf):
        config_files.append((tree.get_file(default_conf), False,
                    "default.conf"))
    config = DebBuildConfig(config_files, tree=tree)
    config.set_user_config(user_config)
    return config


def find_previous_upload(tree, merge=False):
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
        cl, top_level = find_changelog(tree, merge, max_blocks=None)
    except UnparseableChangelog:
        raise UnableToFindPreviousUpload()
    return changelog_find_previous_upload(cl)


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
            match_targets += tuple([current_target.split("-", 1)[0]
                + t for t in UBUNTU_POCKETS])
    else:
        # If we do not recognize the current target in order to apply special
        # rules to it, then just assume that only previous uploads to exactly
        # the same target count.
        match_targets = (current_target,)
    previous_version = None
    for block in cl._blocks[1:]:
        if block.distributions.split(" ")[0] in match_targets:
            return block.version
    raise NoPreviousUpload(current_target)


def tree_contains_upstream_source(tree):
    """Guess if the specified tree contains the upstream source.

    :param tree: A RevisionTree.
    :return: Boolean indicating whether or not the tree contains the upstream
        source. None if the tree is empty
    """
    present_files = set(
        [f[0] for f in tree.list_files(recursive=False)
         if f[1] == 'V'])
    if len(present_files) == 0:
        return None
    packaging_files = frozenset([
        "debian", ".bzr-builddeb", ".bzrignore", ".gitignore"])
    return (len(present_files - packaging_files) > 0)


def tree_get_source_format(tree):
    """Retrieve the source format name from a package.

    :param path: Path to the package
    :return: String with package format
    """
    filename = "debian/source/format"
    try:
        text = tree.get_file_text(filename)
    except IOError as e:
        if e.errno == errno.ENOENT:
            return FORMAT_1_0
        raise
    except errors.NoSuchFile:
        return FORMAT_1_0
    return text.strip().decode('ascii')


FORMAT_1_0 = "1.0"
FORMAT_3_0_QUILT = "3.0 (quilt)"
FORMAT_3_0_NATIVE = "3.0 (native)"

NATIVE_SOURCE_FORMATS = [FORMAT_3_0_NATIVE]
NORMAL_SOURCE_FORMATS = [FORMAT_3_0_QUILT]


def guess_build_type(tree, version, contains_upstream_source):
    """Guess the build type based on the contents of a tree.

    :param tree: A `Tree` object.
    :param version: `Version` of the upload.
    :param contains_upstream_source: Whether this branch contains the upstream source.
    :return: A build_type value.
    """
    source_format = tree_get_source_format(tree)
    if source_format in NATIVE_SOURCE_FORMATS:
        format_native = True
    elif source_format in NORMAL_SOURCE_FORMATS:
        format_native = False
    else:
        format_native = None

    # If the package doesn't have a debian revision then it must be native.
    if version is not None:
        version_native = (not version.debian_version)
    else:
        version_native = None

    if type(version_native) is bool and type(format_native) is bool:
        if version_native != format_native:
            raise InconsistentSourceFormatError(version_native, format_native)

    if version_native or format_native:
        return BUILD_TYPE_NATIVE
    if contains_upstream_source == False:
        # Default to merge mode if there's only a debian/ directory
        return BUILD_TYPE_MERGE
    else:
        return BUILD_TYPE_NORMAL


def component_from_orig_tarball(tarball_filename, package, version):
    tarball_filename = os.path.basename(tarball_filename)
    prefix = "%s_%s.orig" % (package, version)
    if not tarball_filename.startswith(prefix):
        raise ValueError(
            "invalid orig tarball file %s does not have expected prefix %s" % (
                tarball_filename, prefix))
    base = tarball_filename[len(prefix):]
    for ext in (".tar.gz", ".tar.bz2", ".tar.lzma", ".tar.xz"):
        if tarball_filename.endswith(ext):
            base = base[:-len(ext)]
            break
    else:
        raise ValueError(
            "orig tarball file %s has unknown extension" % tarball_filename)
    if base == "":
        return None
    elif base[0] == "-":
        # Extra component
        return base[1:]
    else:
        raise ValueError("Invalid extra characters in tarball filename %s" %
            tarball_filename)


def extract_orig_tarball(tarball_filename, component, target, strip_components=None):
    """Extract an orig tarball.

    :param tarball: Path to the tarball
    :param component: Component name (or None for top-level)
    :param target: Target path
    :param strip_components: Optional number of components to strip
    """
    tar_args = ["tar"]
    if tarball_filename.endswith(".tar.bz2"):
        tar_args.append('xjf')
    elif (tarball_filename.endswith(".tar.lzma") or
          tarball_filename.endswith(".tar.xz")):
        tar_args.append('xJf')
    else:
        tar_args.append('xzf')
    if component is not None:
        target_path = os.path.join(target, component)
        os.mkdir(target_path)
    else:
        target_path = target
    tar_args.extend([tarball_filename, "-C", target_path])
    if strip_components is not None:
        tar_args.extend(["--strip-components", "1"])
    proc = subprocess.Popen(tar_args, preexec_fn=subprocess_setup)
    proc.communicate()
    if proc.returncode != 0:
        raise TarFailed("extract", tarball_filename)


def extract_orig_tarballs(tarballs, target, strip_components=None):
    """Extract orig tarballs to a directory.

    :param tarballs: List of tarball filenames
    :param target: Target directory (must already exist)
    """
    for tarball_filename, component in tarballs:
        extract_orig_tarball(tarball_filename, component, target,
            strip_components=strip_components)


def dput_changes(path):
    """Upload a package."""
    (bd, changes_file) = os.path.split(path)
    subprocess.check_call(["dput", changes_file], cwd=bd)


def debsign(path):
    (bd, changes_file) = os.path.split(path)
    subprocess.check_call(["debsign", changes_file], cwd=bd)


def changes_filename(package, version, arch):
    non_epoch_version = version.upstream_version
    if version.debian_version is not None:
        non_epoch_version += "-%s" % version.debian_version
    return "%s_%s_%s.changes" % (package,
            non_epoch_version, arch)


def get_build_architecture():
    try:
        return subprocess.check_output(
            ['dpkg-architecture', '-qDEB_BUILD_ARCH']).strip().decode()
    except subprocess.CalledProcessError as e:
        raise BzrError(
            "Could not find the build architecture: %s" % e)
