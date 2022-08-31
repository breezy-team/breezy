# Copyright (C) 2008 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Miscellaneous useful stuff."""

import stat

from ... import (
    controldir,
    )


def escape_commit_message(message):
    """Replace xml-incompatible control characters."""
    # This really ought to be provided by breezy.
    # Code copied from breezy.commit.

    # Python strings can include characters that can't be
    # represented in well-formed XML; escape characters that
    # aren't listed in the XML specification
    # (http://www.w3.org/TR/REC-xml/#NT-Char).
    import re
    message, _ = re.subn(
        u'[^\x09\x0A\x0D\u0020-\uD7FF\uE000-\uFFFD]+',
        lambda match: match.group(0).encode('unicode_escape'),
        message)
    return message


def best_format_for_objects_in_a_repository(repo):
    """Find the high-level format for branches and trees given a repository.

    When creating branches and working trees within a repository, Bazaar
    defaults to using the default format which may not be the best choice.
    This routine does a reverse lookup of the high-level format registry
    to find the high-level format that a shared repository was most likely
    created via.

    :return: the BzrDirFormat or None if no matches were found.
    """
    # Based on code from breezy/info.py ...
    repo_format = repo._format
    candidates = []
    non_aliases = set(controldir.format_registry.keys())
    non_aliases.difference_update(controldir.format_registry.aliases())
    for key in non_aliases:
        format = controldir.format_registry.make_controldir(key)
        # LocalGitBzrDirFormat has no repository_format
        if hasattr(format, "repository_format"):
            if format.repository_format == repo_format:
                candidates.append((key, format))
    if len(candidates):
        # Assume the first one. Is there any reason not to do that?
        name, format = candidates[0]
        return format
    else:
        return None


def open_destination_directory(location, format=None, verbose=True):
    """Open a destination directory and return the BzrDir.

    If destination has a control directory, it will be returned.
    Otherwise, the destination should be empty or non-existent and
    a shared repository will be created there.

    :param location: the destination directory
    :param format: the format to use or None for the default
    :param verbose: display the format used if a repository is created.
    :return: BzrDir for the destination
    """
    import os
    from ... import controldir, errors, trace, transport
    try:
        control, relpath = controldir.ControlDir.open_containing(location)
        # XXX: Check the relpath is None here?
        return control
    except errors.NotBranchError:
        pass

    # If the directory exists, check it is empty. Otherwise create it.
    if os.path.exists(location):
        contents = os.listdir(location)
        if contents:
            errors.CommandError("Destination must have a .bzr directory, "
                                " not yet exist or be empty - files found in %s" % (location,))
    else:
        try:
            os.mkdir(location)
        except IOError as ex:
            raise errors.CommandError(
                "Unable to create %s: %s" % (location, ex))

    # Create a repository for the nominated format.
    trace.note("Creating destination repository ...")
    if format is None:
        format = controldir.format_registry.make_controldir('default')
    to_transport = transport.get_transport(location)
    to_transport.ensure_base()
    control = format.initialize_on_transport(to_transport)
    repo = control.create_repository(shared=True)
    if verbose:
        from ...info import show_bzrdir_info
        show_bzrdir_info(repo.controldir, verbose=0)
    return control


def kind_to_mode(kind, executable):
    if kind == "file":
        if executable is True:
            return stat.S_IFREG | 0o755
        elif executable is False:
            return stat.S_IFREG | 0o644
        else:
            raise AssertionError("Executable %r invalid" % executable)
    elif kind == "symlink":
        return stat.S_IFLNK
    elif kind == "directory":
        return stat.S_IFDIR
    elif kind == "tree-reference":
        return 0o160000
    else:
        raise AssertionError("Unknown file kind '%s'" % kind)


def mode_to_kind(mode):
    # Note: Output from git-fast-export slightly different to spec
    if mode in (0o644, 0o100644):
        return 'file', False
    elif mode in (0o755, 0o100755):
        return 'file', True
    elif mode == 0o040000:
        return 'directory', False
    elif mode == 0o120000:
        return 'symlink', False
    elif mode == 0o160000:
        return 'tree-reference', False
    else:
        raise AssertionError("invalid mode %o" % mode)


def binary_stream(stream):
    """Ensure a stream is binary on Windows.

    :return: the stream
    """
    try:
        import os
        if os.name == 'nt':
            fileno = getattr(stream, 'fileno', None)
            if fileno:
                no = fileno()
                if no >= 0:     # -1 means we're working as subprocess
                    import msvcrt
                    msvcrt.setmode(no, os.O_BINARY)
    except ImportError:
        pass
    return stream


def single_plural(n, single, plural):
    """Return a single or plural form of a noun based on number."""
    if n == 1:
        return single
    else:
        return plural
