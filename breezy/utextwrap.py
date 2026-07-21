# Copyright (C) 2011 Canonical Ltd
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

"""Text wrapping utilities with support for East Asian character widths.

The implementation lives in :mod:`breezy._cmd_rs.utextwrap`; this module
re-exports its public surface so existing ``breezy.utextwrap`` callers keep
working.
"""

from ._cmd_rs.utextwrap import fill, wrap

__all__ = ["fill", "wrap"]
