# Copyright (C) 2005-2012, 2016 Canonical Ltd
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

"""Marker package for the bzr smart-over-HTTP WSGI app.

The HTTP transport itself lives in :mod:`dromedary.http.urllib`; bzr-smart
medium dispatch is handled by :mod:`breezy.bzr.smart.transport`. This
package only exists so :mod:`breezy.transport.http.wsgi` keeps its import
path.
"""
