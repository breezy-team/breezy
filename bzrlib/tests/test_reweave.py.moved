# Copyright (C) 2005 by Canonical Ltd
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

"""Test reweave code.

Reweave takes two weaves containing a partial view of history and combines
them into a single weave containing all the information.  This can include 

 - versions recorded in only one file

 - versions with different (but not contradictory) lists of parent 
   revisions

It is an error if either of these conditions occur:

 - contradictory ancestry graphs, e.g.
   - v1 is an ancestor of v2 in one weave, and vice versa in the other
   - different text for any version 
"""

import os
import sys

