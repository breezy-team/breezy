# Copyright (C) 2009-2012 Canonical Ltd
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

"""Launchpad URIs."""


# We use production as the default because edge has been deprecated circa
# 2010-11 (see bug https://bugs.launchpad.net/bzr/+bug/583667)
DEFAULT_INSTANCE = 'production'

LAUNCHPAD_DOMAINS = {
    'production': 'launchpad.net',
    'staging': 'staging.launchpad.net',
    'qastaging': 'qastaging.launchpad.net',
    'demo': 'demo.launchpad.net',
    'test': 'launchpad.test',
    }

LAUNCHPAD_BAZAAR_DOMAINS = [
    'bazaar.%s' % domain
    for domain in LAUNCHPAD_DOMAINS.values()]
