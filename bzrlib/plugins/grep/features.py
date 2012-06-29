# Copyright (C) 2010 Canonical Ltd
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
"""'Features' which are used to skip tests."""

from __future__ import absolute_import

try:
    from bzrlib.tests.features import Feature
except ImportError: # bzr < 2.5
    from bzrlib.tests import Feature
from bzrlib.plugins.grep.termcolor import allow_color

class _ColorFeature(Feature):

    def _probe(self):
        return allow_color()

    def feature_name(self):
        return "Terminal supports color."

color_feature = _ColorFeature()


