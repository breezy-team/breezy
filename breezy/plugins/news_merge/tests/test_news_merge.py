# Copyright (C) 2010 by Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

# FIXME: This is totally incomplete but I'm only the patch pilot :-)
# -- vila 100120
# Note that the single test from this file is now in
# test_merge.TestConfigurableFileMerger -- rbc 20100129.

from breezy import (
    option,
    tests,
    )
from breezy.merge import Merger
from breezy.plugins import news_merge
