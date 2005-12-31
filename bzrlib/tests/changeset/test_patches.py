# Copyright (C) 2004-2006 by Canonical Ltd

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

# Just import the tester built-into the patch file

from bzrlib.patches import PatchesTester
import os


# We have to inherit so that unittest will consider it
# Also, the testdata directory is relative to this file
# so override datafile
class TestPatches(PatchesTester):
    
    def datafile(self, filename):
        data_path = os.path.join(os.path.dirname(__file__), "testdata", 
                                 filename)
        return file(data_path, "rb")


