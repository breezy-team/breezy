# (C) 2005 Canonical Development Ltd

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

BZRDIR = ".bzr"

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
                  '*~',
                  '.#*',
                  '.*.sw[nop]',
                  '.*.tmp',
                  '.DS_Store',
                  '.arch-ids',
                  '.arch-inventory',
                  '.bzr.log',
                  '.del-*',
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
                  'Makefile.in',
                  'RCS',
                  'SCCS',
                  'TAGS',
                  '_darcs',
                  'aclocal.m4',
                  'autom4te*',
                  'config.guess',
                  'config.h',
                  'config.h.in',
                  'config.log',
                  'config.status',
                  'config.sub',
                  'configure.in',
                  'stamp-h',
                  'stamp-h.in',
                  'stamp-h1',
                  '{arch}',
                  ]

IGNORE_FILENAME = ".bzrignore"

import os
import locale
user_encoding = locale.getpreferredencoding() or 'ascii'
del locale

__copyright__ = "Copyright 2005 Canonical Development Ltd."
__version__ = '0.6pre'


def get_bzr_revision():
    """If bzr is run from a branch, return (revno,revid) or None"""
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
    import selftest
    return selftest.test_suite()
