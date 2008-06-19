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

# Deal with Subversion 1.5 and the patched Subversion 1.4 (which are 
# slightly different).

from cStringIO import StringIO
import svn.delta

if getattr(svn.delta, 'tx_invoke_window_handler', None):
    def apply_txdelta_handler(sbuf, target_stream):
        src_stream = StringIO(sbuf)
        assert getattr(src_stream, 'read', None) is not None
        assert getattr(target_stream, 'write', None) is not None
        window_handler, baton = svn.delta.tx_apply(src_stream, target_stream, 
                                                   None)

        def wrapper(window):
            window_handler(window, baton)

        return wrapper
else:
    def apply_txdelta_handler(sbuf, target_stream):
        src_stream = StringIO(sbuf)
        assert getattr(src_stream, 'read', None) is not None
        assert getattr(target_stream, 'write', None) is not None
        ret = svn.delta.svn_txdelta_apply(src_stream, target_stream, None)

        def wrapper(window):
            svn.delta.invoke_txdelta_window_handler(
                ret[1], window, ret[2])

        return wrapper

