# Copyright (C) 2007 Jelmer Vernooij <jelmer@samba.org>

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
"""Stores per-repository settings."""

from bzrlib import osutils
from bzrlib.config import IniBasedConfig, config_dir, ensure_config_dir_exists, GlobalConfig

import os

from scheme import BranchingScheme

# Settings are stored by UUID. 
# Data stored includes default branching scheme and locations the repository 
# was seen at.

def subversion_config_filename():
    """Return per-user configuration ini file filename."""
    return osutils.pathjoin(config_dir(), 'subversion.conf')


class SvnRepositoryConfig(IniBasedConfig):
    """Per-repository settings."""

    def __init__(self, uuid):
        name_generator = subversion_config_filename
        super(SvnRepositoryConfig, self).__init__(name_generator)
        self.uuid = uuid
        if not self.uuid in self._get_parser():
            self._get_parser()[self.uuid] = {}

    def set_branching_scheme(self, scheme, mandatory=False):
        """Change the branching scheme.

        :param scheme: New branching scheme.
        """
        self.set_user_option('branching-scheme', str(scheme))
        self.set_user_option('branching-scheme-mandatory', str(mandatory))

    def _get_user_option(self, name, use_global=True):
        try:
            return self._get_parser()[self.uuid][name]
        except KeyError:
            if not use_global:
                return None
            return GlobalConfig()._get_user_option(name)

    def get_branching_scheme(self):
        """Get the branching scheme.

        :return: BranchingScheme instance.
        """
        schemename = self._get_user_option("branching-scheme", use_global=False)
        if schemename is not None:
            return BranchingScheme.find_scheme(schemename.encode('ascii'))
        return None

    def get_set_revprops(self):
        """Check whether or not bzr-svn should attempt to store Bazaar
        revision properties in Subversion revision properties during commit."""
        try:
            return self._get_parser().get_bool(self.uuid, "set-revprops")
        except KeyError:
            return None

    def get_supports_change_revprop(self):
        """Check whether or not the repository supports changing existing 
        revision properties."""
        try:
            return self._get_parser().get_bool(self.uuid, "supports-change-revprop")
        except KeyError:
            return None

    def branching_scheme_is_mandatory(self):
        """Check whether or not the branching scheme for this repository 
        is mandatory.
        """
        try:
            return self._get_parser().get_bool(self.uuid, "branching-scheme-mandatory")
        except KeyError:
            return False

    def get_override_svn_revprops(self):
        """Check whether or not bzr-svn should attempt to override Subversion revision 
        properties after committing."""
        try:
            return self._get_parser().get_bool(self.uuid, "override-svn-revprops")
        except KeyError:
            pass
        global_config = GlobalConfig()
        try:
            return global_config._get_parser().get_bool(global_config._get_section(), "override-svn-revprops")
        except KeyError:
            return None

    def get_locations(self):
        """Find the locations this repository has been seen at.

        :return: Set with URLs.
        """
        val = self._get_user_option("locations", use_global=False)
        if val is None:
            return set()
        return set(val.split(";"))

    def add_location(self, location):
        """Add a location for this repository.

        :param location: URL of location to add.
        """
        locations = self.get_locations()
        locations.add(location.rstrip("/"))
        self.set_user_option('locations', ";".join(list(locations)))

    def set_user_option(self, name, value):
        """Change a user option.

        :param name: Name of the option.
        :param value: Value of the option.
        """
        conf_dir = os.path.dirname(self._get_filename())
        ensure_config_dir_exists(conf_dir)
        self._get_parser()[self.uuid][name] = value
        f = open(self._get_filename(), 'wb')
        self._get_parser().write(f)
        f.close()
