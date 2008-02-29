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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

# Queryable plugin variables, from a proposal by Robert Collins.

bzr_plugin_name = 'bisect'

version_info = (1, 1, 0, 'pre', 0)
__version__ = '.'.join([str(x) for x in version_info[:3]])
if version_info[3] != 'final':
    __version__ = "%s%s%d" % (__version__, version_info[3], version_info[4])

bzr_minimum_api = (0, 18, 0)

bzr_commands = [ 'bisect' ]
