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


from bzrlib import tests
from bzrlib.symbol_versioning import deprecated_in


apport = tests.ModuleAvailableFeature('apport')
ApportFeature = tests._CompatabilityThunkFeature('bzrlib.tests.features',
    'ApportFeature', 'bzrlib.tests.features.apport', deprecated_in((2,1,0)))
paramiko = tests.ModuleAvailableFeature('paramiko')
pycurl = tests.ModuleAvailableFeature('pycurl')
subunit = tests.ModuleAvailableFeature('subunit')
