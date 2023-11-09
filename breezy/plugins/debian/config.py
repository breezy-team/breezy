#    config.py -- Configuration of bzr-builddeb from files
#    Copyright (C) 2006 James Westby <jw+debian@jameswestby.net>
#
#    This file is part of breezy-debian.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

import yaml

from breezy.transport import NoSuchFile

from ...config import (
    ConfigObj,
    TreeConfig,
    configobj,
)
from ...errors import BzrError
from ...trace import mutter, warning

BUILD_TYPE_NORMAL = "normal"
BUILD_TYPE_NATIVE = "native"
BUILD_TYPE_MERGE = "merge"
BUILD_TYPE_SPLIT = "split"


class SvnBuildPackageMappedConfig:
    """Config object that provides a bzr-builddeb configuration
    based on a svn-buildpackage configuration.
    """

    def __init__(self, bp_config):
        self.bp_config = bp_config

    def get_option(self, option, section=None):
        """Retrieve the contents of an option, mapped from the equivalent
        svn-buildpackage option.
        """
        if section == "BUILDDEB":
            if option == "merge":
                return self.bp_config.get_merge_with_upstream()
            elif option == "orig-dir":
                return self.bp_config.get("origDir")
            elif option == "build-dir":
                return self.bp_config.get("buildArea")
        return None


class UpstreamMetadataSyntaxError(BzrError):
    """There is a syntax error in the debian/upstream/metadata file."""

    _fmt = "Unable to parse upstream metadata file %(path)s: %(error)s"

    def __init__(self, path, error):
        self.path = path
        self.error = error


class UpstreamMetadataConfig:
    """Config object that represents debian/upstream/metadata."""

    filename = "debian/upstream/metadata"

    def __init__(self, text):
        try:
            self.metadata = yaml.safe_load(text)
        except yaml.composer.ComposerError as e:
            all_metadata = [x for x in yaml.safe_load_all(text) if x is not None]
            if len(all_metadata) != 1:
                raise UpstreamMetadataSyntaxError(
                    "debian/upstream/metadata", Exception("multiple documents found")
                ) from e
            warning("ignoring empty extra documents in debian/upstream/metadata")
            self.metadata = all_metadata[0]
        except (
            yaml.scanner.ScannerError,
            yaml.parser.ParserError,
        ) as e:
            raise UpstreamMetadataSyntaxError("debian/upstream/metadata", e) from e
        if isinstance(self.metadata, str):
            raise UpstreamMetadataSyntaxError(
                "debian/upstream/metadata", TypeError(self.metadata)
            )
        if isinstance(self.metadata, list):
            raise UpstreamMetadataSyntaxError(
                "debian/upstream/metadata", TypeError(self.metadata)
            )

    def get_value(self, section, option):
        if section == "BUILDDEB":
            if option == "upstream-branch":
                return self.metadata.get("Repository")
            if option == "export-upstream-revision":
                tag_prefix = self.metadata.get("Repository-Tag-Prefix")
                if tag_prefix is not None:
                    return "tag:" + tag_prefix + "$UPSTREAM_VERSION"
        raise KeyError

    def __getitem__(self, key):
        return self.get_value(key, "BUILDDEB")

    def get_bool(self, section, option):
        raise KeyError

    def as_bool(self, option):
        raise KeyError


class DebBuildConfig:
    """Holds the configuration settings for builddeb. These are taken from
    a hierarchy of config files. .bzr-builddeb/local.conf then
    debian/bzr-builddeb.conf.local,
    ~/.bazaar/builddeb.conf, debian/bzr-builddeb.conf,
    finally .bzr-builddeb/default.conf. The value is
    taken from the first file in which it is specified.
    """

    section = "BUILDDEB"

    def __init__(self, files, branch=None, tree=None):
        """Creates a config to read from config files in a hierarchy.

        Pass it a list of tuples (file, secure) where file is the location of a
        config file (that doesn't have to exist, and trusted is True or false,
        and states whether the file can be trusted for sensitive values.

        The value will be returned from the first in the list that has it,
        unless that key is marked as needing a trusted file and the file isn't
        trusted.

        If branch is not None then it will be used in preference to all others.
        It will not be considered trusted.

        The sample files used in this test are included in the builddeb source
        tree.

        >>> import os
        >>> import breezy.plugins.debian
        >>> d = os.path.dirname(breezy.plugins.debian.__file__) + '/'
        >>> c = DebBuildConfig([
        ...      (d + 'local.conf', False),
        ...      (d + 'user.conf', True),
        ...      (d + 'default.conf', False)])
        >>> print(c.orig_dir)
        None
        >>> print(c.merge)
        True
        >>> print(c.build_dir)
        defaultbuild
        >>> print(c.result_dir)
        userresult
        >>> print(c.builder)
        userbuild
        """
        self._config_files = []
        for input in files:
            try:
                config = ConfigObj(input[0])
            except configobj.ParseError as e:
                if len(input) > 2:
                    content = input[2]
                else:
                    content = input[0]
                warning("There was an error parsing '%s': %s", content, e.msg)
                continue
            if len(input) > 2:
                config.filename = input[2]
            self._config_files.append((config, input[1]))
        if branch is not None:
            self._branch_config = TreeConfig(branch)
        else:
            self._branch_config = None
        self._tree_config = None
        if tree is not None:
            try:
                # Imported here, since not everybody will have bzr-svn
                # installed
                from ..svn.config import (
                    NoSubversionBuildPackageConfig,
                    SubversionBuildPackageConfig,
                )

                try:
                    self._tree_config = SvnBuildPackageMappedConfig(
                        SubversionBuildPackageConfig(tree)
                    )
                except NoSubversionBuildPackageConfig:
                    pass  # Not a svn tree
            except ImportError:
                pass  # No svn, apparently
            try:
                try:
                    upstream_metadata_text = tree.get_file_text(
                        UpstreamMetadataConfig.filename
                    )
                except IsADirectoryError:
                    upstream_metadata_text = tree.get_file_text("debian/upstream")
            except NoSuchFile:
                pass
            else:
                try:
                    self._config_files.append(
                        (UpstreamMetadataConfig(upstream_metadata_text), False)
                    )
                except UpstreamMetadataSyntaxError as e:
                    warning("Ignoring upstream metadata due to %s", e)
        self.user_config = None

    def set_user_config(self, user_conf):
        if user_conf is not None:
            self.user_config = ConfigObj(user_conf)

    def _user_config_value(self, key):
        if self.user_config is not None:
            try:
                return self.user_config.get_value(self.section, key)
            except KeyError:
                pass
        return None

    def _get_opt(self, config, key, section=None):
        """Returns the value for key from config, of None if it is not defined
        in the file.
        """
        if section is None:
            section = self.section
        try:
            return config.get_value(section, key)
        except KeyError:
            pass
        if config.filename is not None:
            try:
                config[key]
                warning(
                    "'{}' defines a value for '{}', but it is not in a '{}' "
                    "section, so it is ignored".format(config.filename, key, section)
                )
            except KeyError:
                pass
        return None

    def _get_best_opt(self, key, trusted=False, section=None):
        """Returns the value for key, obeying precedence.

        Returns the value for the key from the first file in which it is
        defined, or None if none of the files define it.

        If trusted is True then the the value will only be taken from a file
        marked as trusted.

        """
        if section is None:
            section = self.section
        if not trusted:
            if self._branch_config is not None:
                value = self._branch_config.get_option(key, section=self.section)
                if value is not None:
                    mutter("Using %s for %s, taken from the branch", value, key)
                    return value
            if self._tree_config is not None:
                value = self._tree_config.get_option(key, section=self.section)
                if value is not None:
                    mutter("Using %s for %s, taken from the tree", value, key)
                    return value
        for config_file in self._config_files:
            if not trusted or config_file[1]:
                value = self._get_opt(config_file[0], key, section=section)
                if value is not None:
                    mutter(
                        "Using %s for %s, taken from %s",
                        value,
                        key,
                        config_file[0].filename,
                    )
                    return value
        return None

    def get_hook(self, hook_name):
        return self._get_best_opt(hook_name, section="HOOKS")

    def _get_bool(self, config, key):
        try:
            return True, config.get_bool("BUILDDEB", key)
        except KeyError:
            pass
        if config.filename is not None:
            try:
                config.as_bool(key)
                warning(
                    "'{}' defines a value for '{}', but it is not in a "
                    "'BUILDDEB' section, so it is ignored".format(config.filename, key)
                )
            except KeyError:
                pass
        return False, False

    def _get_best_bool(self, key, trusted=False, default=False):
        """Returns the value of key, obeying precedence.

        Returns the value for the key from the first file in which it is
        defined, or default if none of the files define it.

        If trusted is True then the the value will only be taken from a file
        marked as trusted.

        """
        if not trusted:
            if self._branch_config is not None:
                value = self._branch_config.get_option(key, section=self.section)
                if value is not None:
                    mutter("Using %s for %s, taken from the branch", value, key)
                    return value
            if self._tree_config is not None:
                value = self._tree_config.get_option(key, section=self.section)
                if value is not None:
                    mutter("Using %s for %s, taken from the tree", value, key)
                    return value
        for config_file in self._config_files:
            if not trusted or config_file[1]:
                (found, value) = self._get_bool(config_file[0], key)
                if found:
                    mutter(
                        "Using %s for %s, taken from %s",
                        str(value),
                        key,
                        config_file[0].filename,
                    )
                    return value
        return default

    @staticmethod
    def _opt_property(name: str, help=None, trusted=False) -> property:
        return property(
            lambda self: self._get_best_opt(name, trusted), None, None, help
        )

    @staticmethod
    def _bool_property(name, help=None, trusted=False, default=False) -> property:
        return property(
            lambda self: self._get_best_bool(name, trusted, default), None, None, help
        )

    build_dir = _opt_property("build-dir", "The dir to build in")

    user_build_dir = property(lambda self: self._user_config_value("build-dir"))

    orig_dir = _opt_property("orig-dir", "The dir to get upstream tarballs from")

    user_orig_dir = property(lambda self: self._user_config_value("orig-dir"))

    builder = _opt_property("builder", "The command to build with", True)

    result_dir = _opt_property("result-dir", "The dir to put the results in")

    user_result_dir = property(lambda self: self._user_config_value("result-dir"))

    merge = _bool_property("merge", "Run in merge mode")

    @property
    def build_type(self):
        if self.merge:
            return BUILD_TYPE_MERGE
        elif self.native:
            return BUILD_TYPE_NATIVE
        elif self.split:
            return BUILD_TYPE_SPLIT
        else:
            return None

    quick_builder = _opt_property(
        "quick-builder", "A quick command to build with", True
    )

    native = _bool_property("native", "Build a native package")

    split = _bool_property("split", "Split a full source package")

    upstream_branch = _opt_property(
        "upstream-branch", "The upstream branch to merge from"
    )

    export_upstream_revision = _opt_property(
        "export-upstream-revision", "The revision of the upstream source to use."
    )


def _test():
    import doctest

    doctest.testmod()


if __name__ == "__main__":
    _test()
