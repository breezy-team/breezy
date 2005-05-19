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

from inventory import Inventory, InventoryEntry
from branch import Branch, ScratchBranch, find_branch
from osutils import format_date
from tree import Tree
from diff import compare_trees
from trace import mutter, warning, open_tracefile
from log import show_log
import add

BZRDIR = ".bzr"

DEFAULT_IGNORE = ['.bzr.log',
                  '*~', '#*#', '*$', '.#*',
                  '.*.swp', '.*.tmp',
                  '*.tmp', '*.bak', '*.BAK', '*.orig',
                  '*.o', '*.obj', '*.a', '*.py[oc]', '*.so', '*.exe', '*.elc', 
                  '{arch}', 'CVS', 'CVS.adm', '.svn', '_darcs', 'SCCS', 'RCS',
                  '*,v',
                  'BitKeeper',
                  'TAGS', '.make.state', '.sconsign', '.tmp*',
                  '.del-*']

IGNORE_FILENAME = ".bzrignore"

import locale
user_encoding = locale.getpreferredencoding()
del locale

__copyright__ = "Copyright 2005 Canonical Development Ltd."
__author__ = "Martin Pool <mbp@canonical.com>"
__version__ = '0.0.5pre'


# in python2.4 there is a 'set' builtin type; in 2.3 we need to use
# the slower pure-python 'sets' module.
import sys
if sys.version_info < (2, 4):
    import sets
    set = sets.Set
    frozenset = sets.ImmutableSet
    del sets
else:
    import __builtin__
    set = __builtin__.set
    frozenset = __builtin__.frozenset
    del __builtin__
    
