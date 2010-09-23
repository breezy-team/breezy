# Copyright (C) 2009, 2010 Canonical Ltd
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

import os

from bzrlib import tests
from bzrlib.symbol_versioning import deprecated_in


class _NotRunningAsRoot(tests.Feature):

    def _probe(self):
        try:
            uid = os.getuid()
        except AttributeError:
            # If there is no uid, chances are there is no root either
            return True
        return uid != 0

    def feature_name(self):
        return 'Not running as root'


not_running_as_root = _NotRunningAsRoot()
apport = tests.ModuleAvailableFeature('apport')
ApportFeature = tests._CompatabilityThunkFeature('bzrlib.tests.features',
    'ApportFeature', 'bzrlib.tests.features.apport', deprecated_in((2,1,0)))
paramiko = tests.ModuleAvailableFeature('paramiko')
pycurl = tests.ModuleAvailableFeature('pycurl')
subunit = tests.ModuleAvailableFeature('subunit')
