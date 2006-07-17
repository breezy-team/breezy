# Copyright (C) 2006 by Canonical Ltd
#
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

"""Check third-party libraries used by bzr
installed for std. python or bundled into bzr.exe
Written by Alexander Belchenko
"""

import os
import sys

# bzr.exe has special flag
if hasattr(sys, 'frozen'):
    print 'bzr is frozen:', sys.frozen

# python interpreter
print 'Python', sys.version

# os id
print 'System:', (sys.platform, os.name)

# ctypes (for win32)
try:
    import ctypes
    print 'ctypes:', ctypes.__version__
except ImportError:
    print 'ctypes: None'

# elementtree
try:
    import elementtree.ElementTree
    print 'ElementTree:', elementtree.ElementTree.VERSION
    try:
        import cElementTree
        print 'cElementTree:', cElementTree.VERSION
    except ImportError:
        print 'cElementTree: None'
except ImportError:
    print 'ElementTree: None'

# pycurl
try:
    import pycurl
    print 'PyCurl:', pycurl.version
except ImportError:
    print 'PyCurl: None'

# paramiko
try:
    import paramiko
    print 'Paramiko:', paramiko.__version__
except ImportError:
    print 'Paramiko: None'

# pycrypto
try:
    import Crypto
    print 'PyCrypto:', Crypto.__version__
except ImportError:
    print 'PyCrypto: None'
