# Copyright (C) 2008 Canonical Ltd
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

from . import xml8


class InventorySerializer_v6(xml8.InventorySerializer_v8):
    """This serialiser supports rich roots.

    While its inventory format number is 6, its revision format is 5.
    Its inventory_sha1 may be inaccurate-- the inventory may have been
    converted from format 5 or 7 without updating the sha1.
    """

    format_num = b"6"


inventory_serializer_v6 = InventorySerializer_v6()
