# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import svn.core

NODE_NONE = svn.core.svn_node_none
NODE_FILE = svn.core.svn_node_file
NODE_DIR = svn.core.svn_node_dir
NODE_UNKNOWN = svn.core.svn_node_unknown

SubversionException = svn.core.SubversionException
time_to_cstring = svn.core.svn_time_to_cstring
get_config = svn.core.svn_config_get_config
