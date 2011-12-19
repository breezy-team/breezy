# Copyright (C) 2006-2011 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Lists of ignore files, etc."""

from __future__ import absolute_import

import errno
import os
from cStringIO import StringIO

import bzrlib
from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    atomicfile,
    config,
    globbing,
    trace,
    )
""")

# ~/.bazaar/ignore will be filled out using
# this ignore list, if it does not exist
# please keep these sorted (in C locale order) to aid merging
USER_DEFAULTS = [
    '*.a',
    '*.o',
    '*.py[co]',
    '*.so',
    '*.sw[nop]',
    '*~',
    '.#*',
    '[#]*#',
    '__pycache__',
    'bzr-orphans',
]



def parse_ignore_file(f):
    """Read in all of the lines in the file and turn it into an ignore list
    
    Continue in the case of utf8 decoding errors, and emit a warning when 
    such and error is found. Optimise for the common case -- no decoding 
    errors.
    """
    ignored = set()
    ignore_file = f.read()
    try:
        # Try and parse whole ignore file at once.
        unicode_lines = ignore_file.decode('utf8').split('\n')
    except UnicodeDecodeError:
        # Otherwise go though line by line and pick out the 'good'
        # decodable lines
        lines = ignore_file.split('\n')
        unicode_lines = []
        for line_number, line in enumerate(lines):
            try:
                unicode_lines.append(line.decode('utf-8'))
            except UnicodeDecodeError:
                # report error about line (idx+1)
                trace.warning(
                        '.bzrignore: On Line #%d, malformed utf8 character. '
                        'Ignoring line.' % (line_number+1))

    # Append each line to ignore list if it's not a comment line
    for line in unicode_lines:
        line = line.rstrip('\r\n')
        if not line or line.startswith('#'):
            continue
        ignored.add(globbing.normalize_pattern(line))
    return ignored


def get_user_ignores():
    """Get the list of user ignored files, possibly creating it."""
    path = config.user_ignore_config_filename()
    patterns = set(USER_DEFAULTS)
    try:
        f = open(path, 'rb')
    except (IOError, OSError), e:
        # open() shouldn't return an IOError without errno, but just in case
        err = getattr(e, 'errno', None)
        if err not in (errno.ENOENT,):
            raise
        # Create the ignore file, and just return the default
        # We want to ignore if we can't write to the file
        # since get_* should be a safe operation
        try:
            _set_user_ignores(USER_DEFAULTS)
        except (IOError, OSError), e:
            if e.errno not in (errno.EPERM,):
                raise
        return patterns

    try:
        return parse_ignore_file(f)
    finally:
        f.close()


def _set_user_ignores(patterns):
    """Fill out the user ignore file with the given patterns

    This may raise an error if it doesn't have permission to
    write to the user ignore file.
    This is mostly used for testing, since it would be
    bad form to rewrite a user's ignore list.
    bzrlib only writes this file if it does not exist.
    """
    ignore_path = config.user_ignore_config_filename()
    config.ensure_config_dir_exists()

    # Create an empty file
    f = open(ignore_path, 'wb')
    try:
        for pattern in patterns:
            f.write(pattern.encode('utf8') + '\n')
    finally:
        f.close()


def add_unique_user_ignores(new_ignores):
    """Add entries to the user's ignore list if not present.

    :param new_ignores: A list of ignore patterns
    :return: The list of ignores that were added
    """
    ignored = get_user_ignores()
    to_add = []
    for ignore in new_ignores:
        ignore = globbing.normalize_pattern(ignore)
        if ignore not in ignored:
            ignored.add(ignore)
            to_add.append(ignore)

    if not to_add:
        return []

    f = open(config.user_ignore_config_filename(), 'ab')
    try:
        for pattern in to_add:
            f.write(pattern.encode('utf8') + '\n')
    finally:
        f.close()

    return to_add


_runtime_ignores = set()


def add_runtime_ignores(ignores):
    """Add some ignore patterns that only exists in memory.

    This is used by some plugins that want bzr to ignore files,
    but don't want to change a users ignore list.
    (Such as a conversion script that needs to ignore temporary files,
    but does not want to modify the project's ignore list.)

    :param ignores: A list or generator of ignore patterns.
    :return: None
    """
    global _runtime_ignores
    _runtime_ignores.update(set(ignores))


def get_runtime_ignores():
    """Get the current set of runtime ignores."""
    return _runtime_ignores


def tree_ignores_add_patterns(tree, name_pattern_list):
    """Add more ignore patterns to the ignore file in a tree.
    If ignore file does not exist then it will be created.
    The ignore file will be automatically added under version control.

    :param tree: Working tree to update the ignore list.
    :param name_pattern_list: List of ignore patterns.
    :return: None
    """
    # read in the existing ignores set
    ifn = tree.abspath(bzrlib.IGNORE_FILENAME)
    if tree.has_filename(ifn):
        f = open(ifn, 'rU')
        try:
            file_contents = f.read()
            # figure out what kind of line endings are used
            newline = getattr(f, 'newlines', None)
            if type(newline) is tuple:
                newline = newline[0]
            elif newline is None:
                newline = os.linesep
        finally:
            f.close()
    else:
        file_contents = ""
        newline = os.linesep
    
    sio = StringIO(file_contents)
    try:
        ignores = parse_ignore_file(sio)
    finally:
        sio.close()
    
    # write out the updated ignores set
    f = atomicfile.AtomicFile(ifn, 'wb')
    try:
        # write the original contents, preserving original line endings
        f.write(newline.join(file_contents.split('\n')))
        if len(file_contents) > 0 and not file_contents.endswith('\n'):
            f.write(newline)
        for pattern in name_pattern_list:
            if not pattern in ignores:
                f.write(pattern.encode('utf-8'))
                f.write(newline)
        f.commit()
    finally:
        f.close()

    if not tree.path2id(bzrlib.IGNORE_FILENAME):
        tree.add([bzrlib.IGNORE_FILENAME])
