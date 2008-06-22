# Copyright (C) 2005-2006 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""Subversion delta operations."""

def apply_txdelta_handler(sbuf, target_stream):
    def apply_window(window):
        (sview_offset, sview_len, tview_len, src_ops, ops, new_data) = window
        sview = sbuf[sview_offset:sview_offset+sview_len]
        tview = txdelta_apply_ops(src_ops, ops, new_data, sview)
        assert len(tview) == tview_len
        target_stream.write(tview)
    return apply_window


def txdelta_apply_ops(src_ops, ops, new_data, sview):
    tview = ""
    for (action, offset, length) in ops:
        if action == 0:
            # Copy from source area.
            tview += sview[offset:offset+length]
        elif action == 1:
            for i in xrange(length):
                tview += tview[offset+i]
        elif action == 2:
            tview += new_data[offset:offset+length]
        else:
            raise Exception("Invalid delta instruction code")

    return tview
