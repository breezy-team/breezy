# Copyright (C) 2009, 2010, 2011 Canonical Ltd
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

"""A collection of commonly used 'Features' to optionally run tests."""

import importlib
import os
import stat
import subprocess
import sys
import tempfile
import warnings

from .. import osutils, symbol_versioning


class Feature:
    """An operating system Feature."""

    def __init__(self):
        self._available = None

    def available(self):
        """Is the feature available?

        :return: True if the feature is available.
        """
        if self._available is None:
            self._available = self._probe()
        return self._available

    def _probe(self):
        """Implement this method in concrete features.

        :return: True if the feature is available.
        """
        raise NotImplementedError

    def __str__(self):
        if getattr(self, "feature_name", None):
            return self.feature_name()
        return self.__class__.__name__


class SymlinkFeature(Feature):
    """Whether symlinks can be created by the current user."""

    def __init__(self, path):
        super().__init__()
        self.path = path

    def _probe(self):
        return osutils.supports_symlinks(self.path)

    def feature_name(self):
        return "symlinks"


class HardlinkFeature(Feature):
    def __init__(self, path):
        super().__init__()
        self.path = path

    def _probe(self):
        return osutils.supports_hardlinks(self.path)

    def feature_name(self):
        return "hardlinks"


class _OsFifoFeature(Feature):
    def _probe(self):
        return getattr(os, "mkfifo", None)

    def feature_name(self):
        return "filesystem fifos"


OsFifoFeature = _OsFifoFeature()


class _UnicodeFilenameFeature(Feature):
    """Does the filesystem support Unicode filenames?"""

    def _probe(self):
        try:
            # Check for character combinations unlikely to be covered by any
            # single non-unicode encoding. We use the characters
            # - greek small letter alpha (U+03B1) and
            # - braille pattern dots-123456 (U+283F).
            os.stat("\u03b1\u283f")
        except UnicodeEncodeError:
            return False
        except OSError:
            # The filesystem allows the Unicode filename but the file doesn't
            # exist.
            return True
        else:
            # The filesystem allows the Unicode filename and the file exists,
            # for some reason.
            return True


UnicodeFilenameFeature = _UnicodeFilenameFeature()


class _CompatabilityThunkFeature(Feature):
    """This feature is just a thunk to another feature.

    It issues a deprecation warning if it is accessed, to let you know that you
    should really use a different feature.
    """

    def __init__(
        self, dep_version, module, name, replacement_name, replacement_module=None
    ):
        super().__init__()
        self._module = module
        if replacement_module is None:
            replacement_module = module
        self._replacement_module = replacement_module
        self._name = name
        self._replacement_name = replacement_name
        self._dep_version = dep_version
        self._feature = None

    def _ensure(self):
        if self._feature is None:
            from breezy import pyutils

            depr_msg = self._dep_version % ("{}.{}".format(self._module, self._name))
            use_msg = " Use {}.{} instead.".format(
                self._replacement_module, self._replacement_name
            )
            symbol_versioning.warn(depr_msg + use_msg, DeprecationWarning, stacklevel=5)
            # Import the new feature and use it as a replacement for the
            # deprecated one.
            self._feature = pyutils.get_named_object(
                self._replacement_module, self._replacement_name
            )

    def _probe(self):
        self._ensure()
        return self._feature._probe()


class ModuleAvailableFeature(Feature):
    """This is a feature than describes a module we want to be available.

    Declare the name of the module in __init__(), and then after probing, the
    module will be available as 'self.module'.

    :ivar module: The module if it is available, else None.
    """

    def __init__(self, module_name, ignore_warnings=None):
        super().__init__()
        self.module_name = module_name
        if ignore_warnings is None:
            ignore_warnings = ()
        self.ignore_warnings = ignore_warnings

    def _probe(self):
        sentinel = object()
        module = sys.modules.get(self.module_name, sentinel)
        if module is sentinel:
            with warnings.catch_warnings():
                for warning_category in self.ignore_warnings:
                    warnings.simplefilter("ignore", warning_category)
                try:
                    self._module = importlib.import_module(self.module_name)
                except ImportError:
                    return False
                return True
        else:
            self._module = module
            return True

    @property
    def module(self):
        if self.available():
            return self._module
        return None

    def feature_name(self):
        return self.module_name


class PluginLoadedFeature(Feature):
    """Check whether a plugin with specific name is loaded.

    This is different from ModuleAvailableFeature, because
    plugins can be available but explicitly disabled
    (e.g. through BRZ_DISABLE_PLUGINS=blah).

    :ivar plugin_name: The name of the plugin
    """

    def __init__(self, plugin_name):
        super().__init__()
        self.plugin_name = plugin_name

    def _probe(self):
        from breezy.plugin import get_loaded_plugin

        return get_loaded_plugin(self.plugin_name) is not None

    @property
    def plugin(self):
        from breezy.plugin import get_loaded_plugin

        return get_loaded_plugin(self.plugin_name)

    def feature_name(self):
        return "{} plugin".format(self.plugin_name)


class _HTTPSServerFeature(Feature):
    """Some tests want an https Server, check if one is available."""

    def _probe(self):
        try:
            import ssl  # noqa: F401

            return True
        except ModuleNotFoundError:
            return False

    def feature_name(self):
        return "HTTPSServer"


HTTPSServerFeature = _HTTPSServerFeature()


class _ByteStringNamedFilesystem(Feature):
    """Is the filesystem based on bytes?"""

    def _probe(self):
        return os.name == "posix"


ByteStringNamedFilesystem = _ByteStringNamedFilesystem()


class _UTF8Filesystem(Feature):
    """Is the filesystem UTF-8?"""

    def _probe(self):
        return sys.getfilesystemencoding().upper() in ("UTF-8", "UTF8")


UTF8Filesystem = _UTF8Filesystem()


class _BreakinFeature(Feature):
    """Does this platform support the breakin feature?"""

    def _probe(self):
        from breezy import breakin

        if breakin.determine_signal() is None:
            return False
        if sys.platform == "win32":
            # Windows doesn't have os.kill, and we catch the SIGBREAK signal.
            # We trigger SIGBREAK via a Console api so we need ctypes to
            # access the function
            try:
                import ctypes  # noqa: F401
            except OSError:
                return False
        return True

    def feature_name(self):
        return "SIGQUIT or SIGBREAK w/ctypes on win32"


BreakinFeature = _BreakinFeature()


class _CaseInsCasePresFilenameFeature(Feature):
    """Is the file-system case insensitive, but case-preserving?"""

    def _probe(self):
        fileno, name = tempfile.mkstemp(prefix="MixedCase")
        try:
            # first check truly case-preserving for created files, then check
            # case insensitive when opening existing files.
            name = osutils.normpath(name)
            base, rel = osutils.split(name)
            found_rel = osutils.canonical_relpath(base, name)
            return (
                found_rel == rel
                and os.path.isfile(name.upper())
                and os.path.isfile(name.lower())
            )
        finally:
            os.close(fileno)
            os.remove(name)

    def feature_name(self):
        return "case-insensitive case-preserving filesystem"


CaseInsCasePresFilenameFeature = _CaseInsCasePresFilenameFeature()


class _CaseInsensitiveFilesystemFeature(Feature):
    """Check if underlying filesystem is case-insensitive but *not* case
    preserving.
    """

    # Note that on Windows, Cygwin, MacOS etc, the file-systems are far
    # more likely to be case preserving, so this case is rare.

    def _probe(self):
        if CaseInsCasePresFilenameFeature.available():
            return False

        from breezy import tests

        if tests.TestCaseWithMemoryTransport.TEST_ROOT is None:
            root = tempfile.mkdtemp(prefix="testbzr-", suffix=".tmp")
            tests.TestCaseWithMemoryTransport.TEST_ROOT = root
        else:
            root = tests.TestCaseWithMemoryTransport.TEST_ROOT
        tdir = tempfile.mkdtemp(prefix="case-sensitive-probe-", suffix="", dir=root)
        name_a = osutils.pathjoin(tdir, "a")
        name_A = osutils.pathjoin(tdir, "A")
        os.mkdir(name_a)
        result = osutils.isdir(name_A)
        tests._rmtree_temp_dir(tdir)
        return result

    def feature_name(self):
        return "case-insensitive filesystem"


CaseInsensitiveFilesystemFeature = _CaseInsensitiveFilesystemFeature()


class _CaseSensitiveFilesystemFeature(Feature):
    def _probe(self):
        if CaseInsCasePresFilenameFeature.available():
            return False
        return not CaseInsensitiveFilesystemFeature.available()

    def feature_name(self):
        return "case-sensitive filesystem"


# new coding style is for feature instances to be lowercase
case_sensitive_filesystem_feature = _CaseSensitiveFilesystemFeature()


class _NotRunningAsRoot(Feature):
    def _probe(self):
        try:
            uid = os.getuid()
        except AttributeError:
            # If there is no uid, chances are there is no root either
            return True
        return uid != 0

    def feature_name(self):
        return "Not running as root"


not_running_as_root = _NotRunningAsRoot()

# Apport uses deprecated imp module on python3.
apport = ModuleAvailableFeature(
    "apport.report", ignore_warnings=[DeprecationWarning, PendingDeprecationWarning]
)
gpg = ModuleAvailableFeature("gpg")
lzma = ModuleAvailableFeature("lzma")
meliae = ModuleAvailableFeature("meliae.scanner")
paramiko = ModuleAvailableFeature("paramiko")
pywintypes = ModuleAvailableFeature("pywintypes")
subunit = ModuleAvailableFeature("subunit")
testtools = ModuleAvailableFeature("testtools")
flake8 = ModuleAvailableFeature("flake8.api.legacy")

lsprof_feature = ModuleAvailableFeature("breezy.lsprof")

pyinotify = ModuleAvailableFeature("pyinotify")


class _BackslashDirSeparatorFeature(Feature):
    def _probe(self):
        try:
            os.lstat(os.getcwd() + "\\")
        except OSError:
            return False
        else:
            return True

    def feature_name(self):
        return "Filesystem treats '\\' as a directory separator."


backslashdir_feature = _BackslashDirSeparatorFeature()


class _ChownFeature(Feature):
    """os.chown is supported."""

    def _probe(self):
        return os.name == "posix" and hasattr(os, "chown")


chown_feature = _ChownFeature()


class ExecutableFeature(Feature):
    """Feature testing whether an executable of a given name is on the PATH."""

    def __init__(self, name):
        super().__init__()
        self.name = name
        self._path = None

    @property
    def path(self):
        # This is a property, so accessing path ensures _probe was called
        self.available()
        return self._path

    def _probe(self):
        self._path = osutils.find_executable_on_path(self.name)
        return self._path is not None

    def feature_name(self):
        return "{} executable".format(self.name)


bash_feature = ExecutableFeature("bash")
diff_feature = ExecutableFeature("diff")
sed_feature = ExecutableFeature("sed")
msgmerge_feature = ExecutableFeature("msgmerge")


class _PosixPermissionsFeature(Feature):
    def _probe(self):
        def has_perms():
            # Create temporary file and check if specified perms are
            # maintained.
            write_perms = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
            f = tempfile.mkstemp(prefix="bzr_perms_chk_")
            fd, name = f
            os.close(fd)
            osutils.chmod_if_possible(name, write_perms)

            read_perms = os.stat(name).st_mode & 0o777
            os.unlink(name)
            return write_perms == read_perms

        return (os.name == "posix") and has_perms()

    def feature_name(self):
        return "POSIX permissions support"


posix_permissions_feature = _PosixPermissionsFeature()


class _StraceFeature(Feature):
    def _probe(self):
        try:
            proc = subprocess.Popen(
                ["strace"], stderr=subprocess.PIPE, stdout=subprocess.PIPE
            )
            proc.communicate()
            return True
        except OSError as e:
            import errno

            if e.errno == errno.ENOENT:
                # strace is not installed
                return False
            else:
                raise

    def feature_name(self):
        return "strace"


strace_feature = _StraceFeature()


class _AttribFeature(Feature):
    def _probe(self):
        if sys.platform not in ("cygwin", "win32"):
            return False
        try:
            proc = subprocess.Popen(["attrib", "."], stdout=subprocess.PIPE)
        except OSError:
            return False
        return proc.wait() == 0

    def feature_name(self):
        return "attrib Windows command-line tool"


AttribFeature = _AttribFeature()


class Win32Feature(Feature):
    """Feature testing whether we're running selftest on Windows
    or Windows-like platform.
    """

    def _probe(self):
        return sys.platform == "win32"

    def feature_name(self):
        return "win32 platform"


win32_feature = Win32Feature()


class _BackslashFilenameFeature(Feature):
    """Does the filesystem support backslashes in filenames?"""

    def _probe(self):
        try:
            fileno, name = tempfile.mkstemp(prefix="bzr\\prefix")
        except OSError:
            return False
        else:
            try:
                os.stat(name)
            except OSError:
                # mkstemp succeeded but the file wasn't actually created
                return False
            os.close(fileno)
            os.remove(name)
            return True


BackslashFilenameFeature = _BackslashFilenameFeature()


class PathFeature(Feature):
    """Feature testing whether a particular path exists."""

    def __init__(self, path):
        super().__init__()
        self.path = path

    def _probe(self):
        return os.path.exists(self.path)

    def feature_name(self):
        return "{} exists".format(self.path)
