# Copyright (C) 2009 Canonical Ltd
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

from bzrlib import symbol_versioning

dep_warning = symbol_versioning.deprecated_in((1, 16, 0)) % (
    'bzrlib.util.bencode',) + '\n  Use bzrlib.bencode instead'

symbol_versioning.warn(dep_warning, DeprecationWarning, stacklevel=2)

from bzrlib.bencode import *
