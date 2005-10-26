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

DEFAULT_IGNORE = ['.bzr.log',
                  '*~', '#*#', '*$', '.#*',
                  '.*.sw[nop]', '.*.tmp',
                  '*.tmp', '*.bak', '*.BAK', '*.orig',
                  '*.o', '*.obj', '*.a', '*.py[oc]', '*.so', '*.o', '*.lo', '*.la', '*.exe',
                  '*.elc', 
                  '{arch}', '.arch-ids', '.arch-inventory', 'CVS', 'CVS.adm', '.svn', '_darcs', 
                  'SCCS', 'RCS',
                  '*,v',
                  'BitKeeper',
                  '.git',
                  'TAGS', '.make.state', '.tmp*',
                  '.sconsign*',
                  '.tmp*',
                  'autom4te*', 'config.guess', 'config.h.in', 'config.status', 
                  'config.h', 'config.log', 'config.sub', 'configure.in',
                  'aclocal.m4', 'stamp-h.in', 'Makefile.in', '.libs',
                  'stamp-h1', 'stamp-h',
                  '.jamdeps'
                  '.del-*',
                  '.DS_Store',]

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
