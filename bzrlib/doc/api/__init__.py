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

"""API Documentation for bzrlib.

This documentation is made up of doctest testable examples.

Look for bzrlib/doc/api/*.txt to read it.

This documentation documents the current best practice in using the library.
For details on specific apis, see pydoc on the api, or read the source.
"""

import doctest
import os
    
def test_suite():
    candidates = os.listdir(os.path.dirname(__file__))
    scripts = [candidate for candidate in candidates 
               if candidate.endswith('.txt')]
    return doctest.DocFileSuite(*scripts)
