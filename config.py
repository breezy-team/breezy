# Copyright (C) 2007-2008 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""Stores per-repository settings."""

from bzrlib import osutils, urlutils, trace
from bzrlib.config import IniBasedConfig, config_dir, ensure_config_dir_exists, GlobalConfig, LocationConfig, Config, STORE_BRANCH, STORE_GLOBAL, STORE_LOCATION

import os

from bzrlib.plugins.svn import properties
from bzrlib.plugins.svn.core import SubversionException

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

    def get_reuse_revisions(self):
        ret = self._get_user_option("reuse-revisions")
        if ret is None:
            return "other-branches"
        assert ret in ("none", "other-branches", "removed-branches")
        return ret

    def get_branching_scheme(self):
        """Get the branching scheme.

        :return: BranchingScheme instance.
        """
        from mapping3.scheme import BranchingScheme
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

    def get_use_cache(self):
        try:
            return self._get_parser().get_bool(self.uuid, "use-cache")
        except KeyError:
            return True

    def get_log_strip_trailing_newline(self):
        """Check whether or not trailing newlines should be stripped in the 
        Subversion log message (where support by the bzr<->svn mapping used)."""
        try:
            return self._get_parser().get_bool(self.uuid, "log-strip-trailing-newline")
        except KeyError:
            return False

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
        def get_list(parser, section):
            try:
                if parser.get_bool(section, "override-svn-revprops"):
                    return [properties.PROP_REVISION_DATE, properties.PROP_REVISION_AUTHOR]
                return []
            except ValueError:
                val = parser.get_value(section, "override-svn-revprops")
                if not isinstance(val, list):
                    return [val]
                return val
            except KeyError:
                return None
        ret = get_list(self._get_parser(), self.uuid)
        if ret is not None:
            return ret
        global_config = GlobalConfig()
        return get_list(global_config._get_parser(), global_config._get_section())

    def get_append_revisions_only(self):
        """Check whether it is possible to remove revisions from the mainline.
        """
        try:
            return self._get_parser().get_bool(self.uuid, "append_revisions_only")
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


class BranchConfig(Config):
    def __init__(self, branch):
        super(BranchConfig, self).__init__()
        self._location_config = None
        self._repository_config = None
        self.branch = branch
        self.option_sources = (self._get_location_config, 
                               self._get_repository_config)

    def _get_location_config(self):
        if self._location_config is None:
            self._location_config = LocationConfig(self.branch.base)
        return self._location_config

    def _get_repository_config(self):
        if self._repository_config is None:
            self._repository_config = SvnRepositoryConfig(self.branch.repository.uuid)
        return self._repository_config

    def get_set_revprops(self):
        return self._get_repository_config().get_set_revprops()

    def get_log_strip_trailing_newline(self):
        return self._get_repository_config().get_log_strip_trailing_newline()

    def get_override_svn_revprops(self):
        return self._get_repository_config().get_override_svn_revprops()

    def _get_user_option(self, option_name):
        """See Config._get_user_option."""
        for source in self.option_sources:
            value = source()._get_user_option(option_name)
            if value is not None:
                return value
        return None

    def get_append_revisions_only(self):
        return self.get_user_option("append_revision_only")

    def _get_user_id(self):
        """Get the user id from the 'email' key in the current section."""
        return self._get_user_option('email')

    def get_option(self, key, section=None):
        if section == "BUILDDEB" and key == "merge":
            revnum = self.branch.get_revnum()
            try:
                props = self.branch.repository.transport.get_dir(urlutils.join(self.branch.get_branch_path(revnum), "debian"), revnum)[2]
                if props.has_key("mergeWithUpstream"):
                    return "True"
                else:
                    return "False"
            except SubversionException:
                return None
        return None

    def set_user_option(self, name, value, store=STORE_LOCATION,
        warn_masked=False):
        if store == STORE_GLOBAL:
            self._get_global_config().set_user_option(name, value)
        elif store == STORE_BRANCH:
            raise NotImplementedError("Saving in branch config not supported for Subversion branches")
        else:
            self._get_location_config().set_user_option(name, value, store)
        if not warn_masked:
            return
        if store in (STORE_GLOBAL, STORE_BRANCH):
            mask_value = self._get_location_config().get_user_option(name)
            if mask_value is not None:
                trace.warning('Value "%s" is masked by "%s" from'
                              ' locations.conf', value, mask_value)
            else:
                if store == STORE_GLOBAL:
                    branch_config = self._get_branch_data_config()
                    mask_value = branch_config.get_user_option(name)
                    if mask_value is not None:
                        trace.warning('Value "%s" is masked by "%s" from'
                                      ' branch.conf', value, mask_value)
