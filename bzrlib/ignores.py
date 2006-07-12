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
