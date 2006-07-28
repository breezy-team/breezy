# Copyright (C) 2005, 2006 Canonical Development Ltd
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

"""Lists of ignore files, etc."""

import errno

from bzrlib import config

# This was the full ignore list for bzr 0.8
# please keep these sorted (in C locale order) to aid merging
OLD_DEFAULTS = [
    '#*#',
    '*$',
    '*,v',
    '*.BAK',
    '*.a',
    '*.bak',
    '*.elc',
    '*.exe',
    '*.la',
    '*.lo',
    '*.o',
    '*.obj',
    '*.orig',
    '*.py[oc]',
    '*.so',
    '*.tmp',
    '*~',
    '.#*',
    '.*.sw[nop]',
    '.*.tmp',
    # Our setup tests dump .python-eggs in the bzr source tree root
    './.python-eggs',
    '.DS_Store',
    '.arch-ids',
    '.arch-inventory',
    '.bzr.log',
    '.del-*',
    '.git',
    '.hg',
    '.jamdeps'
    '.libs',
    '.make.state',
    '.sconsign*',
    '.svn',
    '.sw[nop]',    # vim editing nameless file
    '.tmp*',
    'BitKeeper',
    'CVS',
    'CVS.adm',
    'RCS',
    'SCCS',
    'TAGS',
    '_darcs',
    'aclocal.m4',
    'autom4te*',
    'config.h',
    'config.h.in',
    'config.log',
    'config.status',
    'config.sub',
    'stamp-h',
    'stamp-h.in',
    'stamp-h1',
    '{arch}',
]


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
]


def parse_ignore_file(f):
    """Read in all of the lines in the file and turn it into an ignore list"""
    ignored = set()
    for line in f.read().decode('utf8').split('\n'):
        line = line.rstrip('\r\n')
        if not line or line.startswith('#'):
            continue
        ignored.add(line)
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
    (Such as a conversion script, that needs to ignore some files,
    but must preserve as much of the exact content boing converted.)

    :param ignores: A list or generator of ignore patterns.
    :return: None
    """
    global _runtime_ignores
    _runtime_ignores.update(set(ignores))


def get_runtime_ignores():
    """Get the current set of runtime ignores."""
    return _runtime_ignores
