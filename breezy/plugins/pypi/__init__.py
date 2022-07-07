# Copyright (C) 2021 Breezy Developers
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

"""Support for looking up URLs from pypi.
"""

from __future__ import absolute_import

from ... import (
    version_info,  # noqa: F401
    )
from ...directory_service import directories

directories.register_lazy('pypi:', __name__ + '.directory',
                          'PypiDirectory',
                          'Pypi-based directory service',)
