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
    ignored = []
    for line in f.read().decode('utf8').split('\n'):
        line = line.rstrip('\r\n')
        if not line or line.startswith('#'):
            continue
        ignored.append(line)
    return ignored


def _create_user_ignores():
    """Create ~/.bazaar/ignore, and fill it with the defaults"""

    # We need to create the file
    path = config.user_ignore_config_filename()
    config.ensure_config_dir_exists()
    try:
        f = open(path, 'wb')
    except (IOError, OSError), e:
        if e.errno not in (errno.EPERM,):
            raise
        # if EPERM, we don't have write access to home dir
        # so we won't save anything
    else:
        try:
            for pattern in USER_DEFAULTS:
                f.write(pattern.encode('utf8') + '\n')
        finally:
            f.close()


def get_user_ignores():
    """Get the list of user ignored files, possibly creating it."""
    path = config.user_ignore_config_filename()
    patterns = USER_DEFAULTS[:]
    try:
        f = open(path, 'rb')
    except (IOError, OSError), e:
        if e.errno not in (errno.ENOENT,):
            raise
        # Create the ignore file, and just return the default
        _create_user_ignores()
        return patterns

    try:
        return parse_ignore_file(f)
    finally:
        f.close()
