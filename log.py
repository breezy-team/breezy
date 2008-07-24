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

from bzrlib.errors import InvalidRevisionId

from bzrlib.plugins.svn import mapping

def show_subversion_properties(rev):
    data = None
    ret = {}
    if getattr(rev, "svn_revision", None) is not None:
        data = (rev.svn_revision, rev.svn_branch)
    else:
        try:
            (uuid, bp, revnum, mapp) = mapping.parse_revision_id(rev.revision_id)
        except InvalidRevisionId:
            pass
        else:
            data = (revnum, bp)

    if data is not None:
        return { "svn revno": "%d (on /%s)" % data}
    return {}


