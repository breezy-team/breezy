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
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Miscellaneous useful stuff."""


def escape_commit_message(message):
    """Replace xml-incompatible control characters."""
    # This really ought to be provided by bzrlib.
    # Code copied from bzrlib.commit.

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
    # Based on code from bzrlib/info.py ...
    from bzrlib import bzrdir
    repo_format = repo._format
    candidates  = []
    non_aliases = set(bzrdir.format_registry.keys())
    non_aliases.difference_update(bzrdir.format_registry.aliases())
    for key in non_aliases:
        format = bzrdir.format_registry.make_bzrdir(key)
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
    from bzrlib import bzrdir, errors, trace, transport
    try:
        control, relpath = bzrdir.BzrDir.open_containing(location)
        # XXX: Check the relpath is None here?
        return control
    except errors.NotBranchError:
        pass

    # If the directory exists, check it is empty. Otherwise create it.
    if os.path.exists(location):
        contents = os.listdir(location)
        if contents:
            errors.BzrCommandError("Destination must have a .bzr directory, "
                " not yet exist or be empty - files found in %s" % (location,))
    else:
        try:
            os.mkdir(location)
        except IOError, ex:
            errors.BzrCommandError("Unable to create %s: %s" %
                (location, ex))

    # Create a repository for the nominated format.
    trace.note("Creating destination repository ...")
    if format is None:
        format = bzrdir.format_registry.make_bzrdir('default')
    to_transport = transport.get_transport(location)
    to_transport.ensure_base()
    control = format.initialize_on_transport(to_transport)
    repo = control.create_repository(shared=True)
    if verbose:
        from bzrlib.info import show_bzrdir_info
        show_bzrdir_info(repo.bzrdir, verbose=0)
    return control
