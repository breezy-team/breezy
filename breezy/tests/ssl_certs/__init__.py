# Copyright (C) 2007-2008 Canonical Ltd
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

"""ssl_certs -- provides access to ssl keys and certificates needed by tests"""

from breezy import (
    osutils,
    )

# Directory containing all ssl files, keys or certificates
base_dir = osutils.dirname(osutils.realpath(__file__))


def build_path(name):
    """Build and return a path in ssl_certs directory for name"""
    return osutils.pathjoin(base_dir, name)
