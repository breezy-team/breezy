# Copyright (C) 2005-2014, 2016 Canonical Ltd
# Copyright (C) 2019 Breezy developers
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

"""Functions for deriving user configuration from system environment."""

from . import _cmd_rs

ensure_config_dir_exists = _cmd_rs.ensure_config_dir_exists
bazaar_config_dir = _cmd_rs.bazaar_config_dir
config_dir = _cmd_rs.config_dir
_config_dir = _cmd_rs._config_dir
config_path = _cmd_rs.config_path
locations_config_path = _cmd_rs.locations_config_path
authentication_config_path = _cmd_rs.authentication_config_path
user_ignore_config_path = _cmd_rs.user_ignore_config_path
crash_dir = _cmd_rs.crash_dir
cache_dir = _cmd_rs.cache_dir
_get_default_mail_domain = _cmd_rs.get_default_mail_domain
default_email = _cmd_rs.default_email
_auto_user_id = _cmd_rs.auto_user_id
