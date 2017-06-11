# This file is a small part of bzrtools' own bzrtools.py
# The parts copied last changed in bzrtools 1.13.0.

# Copyright (C) 2005, 2006, 2007 Aaron Bentley <aaron@aaronbentley.com>
# Copyright (C) 2007 John Arbash Meinel
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from __future__ import absolute_import

from ... import urlutils
from ...transport import get_transport


def open_from_url(location):
    location = urlutils.normalize_url(location)
    dirname, basename = urlutils.split(location)
    if location.endswith('/') and not basename.endswith('/'):
        basename += '/'
    return get_transport(dirname).get(basename)
