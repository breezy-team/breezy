# Copyright (C) 2005, 2006 Canonical Development Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""bzr library"""


# please keep these sorted (in C locale order) to aid merging
DEFAULT_IGNORE = [
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
                  '*.o',
                  '*.obj',
                  '*.orig',
                  '*.py[oc]',
                  '*.so',
                  '*.tmp',
                  '.*.tmp',
                  '*~',
                  '.#*',
                  '.*.sw[nop]',
                  '.sw[nop]',    # vim editing nameless file
                  '.DS_Store',
                  '.arch-ids',
                  '.arch-inventory',
                  '.bzr.log',
                  '.del-*',
                  '.hg',
                  '.git',
                  '.jamdeps'
                  '.libs',
                  '.make.state',
                  '.sconsign*',
                  '.svn',
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

IGNORE_FILENAME = ".bzrignore"

import os
import sys
if sys.platform == 'darwin':
    # work around egregious python 2.4 bug
    sys.platform = 'posix'
    import locale
    sys.platform = 'darwin'
else:
    import locale
user_encoding = locale.getpreferredencoding() or 'ascii'
del locale

__copyright__ = "Copyright 2005, 2006 Canonical Development Ltd."

# same format as sys.version_info: A tuple containing the five components of
# the version number: major, minor, micro, releaselevel, and serial. All
# values except releaselevel are integers; the release level is 'alpha',
# 'beta', 'candidate', or 'final'. The version_info value corresponding to the
# Python version 2.0 is (2, 0, 0, 'final', 0).

version_info = (0, 8, 1, 'final', 0)

if version_info[3] == 'final':
    version_string = '%d.%d.%d' % version_info[:3]
else:
    version_string = '%d.%d.%d%s%d' % version_info
__version__ = version_string 

from bzrlib.symbol_versioning import deprecated_function, zero_seven

@deprecated_function(zero_seven)
def get_bzr_revision():
    """If bzr is run from a branch, return (revno,revid) or None."""
    import bzrlib.errors
    from bzrlib.branch import Branch
    
    try:
        branch = Branch.open(os.path.dirname(__path__[0]))
        rh = branch.revision_history()
        if rh:
            return len(rh), rh[-1]
        else:
            return None
    except bzrlib.errors.BzrError:
        return None
    
def test_suite():
    import tests
    return tests.test_suite()
