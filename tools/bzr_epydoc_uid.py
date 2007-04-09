# Copyright (C) 2007 Canonical Ltd
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

"""Monkey patch to make epydoc work with bzrlib's lazy imports."""

import epydoc.uid

import bzrlib.lazy_import


_ObjectUID = epydoc.uid.ObjectUID
_ScopeReplacer = bzrlib.lazy_import.ScopeReplacer


class ObjectUID(_ObjectUID):

    def __init__(self, obj):
        if isinstance(obj, _ScopeReplacer):
            # The isinstance will trigger a replacement if it is a real
            # _BzrScopeReplacer, but the local object won't know about it, so
            # replace it locally.
            obj = object.__getattribute__(obj, '_real_obj')
        _ObjectUID.__init__(self, obj)


epydoc.uid.ObjectUID = ObjectUID


bzrlib.lazy_import._scope_replacer_should_proxy = True

