#!/usr/bin/python3
# Copyright (C) 2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

import errno
import os
import pwd
import shutil
import subprocess
import tempfile
from threading import Semaphore
from typing import Optional

from debian.deb822 import Deb822, Dsc

from breezy.errors import DependencyNotPresent


class NoAptSources(Exception):
    """No apt sources were configured."""


class AptSourceError(Exception):
    """An error occured while running 'apt source'."""

    def __init__(self, reason):
        self.reason = reason


def _convert_apt_pkg_error(e):
    if "28: No space left on device":
        return OSError(errno.ENOSPC, str(e))
    return e


class Apt:
    def __enter__(self):
        raise NotImplementedError(self.__enter__)

    def __exit__(self, exc_tp, exc_val, exc_tb):
        raise NotImplementedError(self.__exit__)

    def iter_source_by_name(self, source_name):
        for source in self.iter_sources():
            if source["Package"] == source_name:
                yield source

    def iter_sources(self):
        raise NotImplementedError(self.iter_sources)

    def iter_binaries(self):
        raise NotImplementedError(self.iter_binaries)

    def iter_binary_by_name(self, binary_name):
        for binary in self.iter_binaries():
            if binary["Package"] == binary_name:
                yield binary

    def retrieve_orig(self, source_name, target_directory, orig_version=None):
        raise NotImplementedError(self.retrieve_orig)

    def retrieve_source(self, source_name, target_directory, source_version=None):
        raise NotImplementedError(self.retrieve_source)


_apt_semaphore = Semaphore()


class LocalApt(Apt):
    def __init__(self, rootdir=None):
        self.apt_pkg = None
        self._rootdir = rootdir

    def __repr__(self):
        return f"{type(self).__name__}({self._rootdir!r})"

    def __enter__(self):
        try:
            import apt_pkg
        except ImportError as e:
            raise DependencyNotPresent("apt_pkg", e) from e
        import apt

        self.apt_pkg = apt_pkg
        self.apt_pkg.init()
        try:
            self.cache = apt.Cache(rootdir=self._rootdir)
        except apt_pkg.Error as e:
            raise _convert_apt_pkg_error(e) from e
        return self

    def _set_dir(self):
        if self._rootdir is not None:
            self.apt_pkg.config.set("Dir", self._rootdir)
        else:
            self.apt_pkg.config.set("Dir", "/")

    def __exit__(self, exc_tp, exc_val, exc_tb):
        return False

    def iter_sources(self):
        with _apt_semaphore:
            self._set_dir()
            try:
                sources = self.apt_pkg.SourceRecords()
            except SystemError as e:
                raise NoAptSources() from e

            sources.restart()
            while sources.step():
                yield Dsc(sources.record)

    def iter_source_by_name(self, source_name):
        with _apt_semaphore:
            self._set_dir()
            try:
                sources = self.apt_pkg.SourceRecords()
            except SystemError as e:
                raise NoAptSources() from e

            sources.restart()
            while sources.lookup(source_name):
                yield Dsc(sources.record)

    def iter_binaries(self):
        with _apt_semaphore:
            self._set_dir()

            for pkg in self.cache:
                for version in pkg.versions:
                    yield Deb822(version._records.record)

    def iter_binary_by_name(self, binary_name):
        with _apt_semaphore:
            self._set_dir()

            try:
                pkg = self.cache[binary_name]
            except KeyError:
                pass
            else:
                for version in pkg.versions:
                    yield Deb822(version._records.record)

    def retrieve_source(
        self, package_name, target, source_version=None, tar_only=False
    ):
        self._run_apt_source(package_name, target, source_version, tar_only=tar_only)

    def _get_command(self, package, version_str=None, tar_only=False):
        args = ["apt", "source", "-d"]
        if self._rootdir is not None:
            args.append("-oDir={}".format(self._rootdir))
        if tar_only:
            args.append("--tar-only")
        args.extend(
            [
                "-y",
                "--only-source",
                (f"{package}={version_str}") if version_str is not None else package,
            ]
        )
        return args

    def _run_apt_source(
        self,
        package: str,
        target_dir,
        version_str: Optional[str] = None,
        tar_only: bool = False,
    ):
        command = self._get_command(package, version_str, tar_only=tar_only)
        try:
            subprocess.run(command, cwd=target_dir, capture_output=True, check=True)
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.splitlines()
            if stderr[-1] == (
                b"E: You must put some 'source' URIs in your sources.list"
            ):
                raise NoAptSources() from e
            CS = b"\x1b[1;31mE: \x1b[0m"
            CE = b"\x1b[0m"
            if stderr[-1] == (
                CS + b"You must put some 'deb-src' URIs in your sources.list" + CE
            ):
                raise NoAptSources() from e
            if stderr[-1].startswith(b"E: "):
                raise AptSourceError(stderr[-1][3:].decode()) from e
            if stderr[-1].startswith(CS):
                raise AptSourceError(stderr[-1][len(CS) : -len(CE)].decode()) from e
            raise AptSourceError(
                [line.decode("utf-8", "surrogateescape") for line in stderr]
            ) from e


class RemoteApt(LocalApt):
    def __init__(self, mirror_uri, distribution=None, components=None, key_path=None):
        super().__init__()
        self.mirror_uri = mirror_uri
        self.distribution = distribution
        self.components = components
        self.key_path = key_path
        self._rootdir = None

    def __repr__(self):
        return "{}({!r}, distribution={!r}, components={!r}, key_path={!r})".format(
            type(self).__name__,
            self.mirror_uri,
            self.distribution,
            self.components,
            self.key_path,
        )

    def __enter__(self):
        self._rootdir = tempfile.mkdtemp()
        aptdir = os.path.join(self._rootdir, "etc", "apt")
        os.makedirs(aptdir)
        if self.key_path:
            tag = "[signed-by={}]".format(self.key_path)
        else:
            tag = "[trusted=yes]"
        with open(os.path.join(aptdir, "sources.list"), "w") as f:
            f.write(
                "deb {} {} {} {}\n".format(
                    tag, self.mirror_uri, self.distribution, " ".join(self.components)
                )
            )
            f.write(
                "deb-src {} {} {} {}\n".format(
                    tag, self.mirror_uri, self.distribution, " ".join(self.components)
                )
            )
        try:
            import apt
        except ImportError as e:
            raise DependencyNotPresent("apt", e) from e
        try:
            import apt_pkg
        except ImportError as e:
            raise DependencyNotPresent("apt_pkg", e) from e
        self.apt_pkg = apt_pkg
        self.apt_pkg.init()
        try:
            self.cache = apt.Cache(rootdir=self._rootdir)
        except apt_pkg.Error as e:
            raise _convert_apt_pkg_error(e) from e
        self._set_dir()
        self.cache.update()
        return self

    def _set_dir(self):
        try:
            username = pwd.getpwuid(os.getuid()).pw_name
        except KeyError:
            pass
        else:
            self.apt_pkg.config.set("APT::Sandbox::User", username)
        self.apt_pkg.config.set("Dir", self._rootdir)

    def __exit__(self, exc_tp, exc_val, exc_tb):
        shutil.rmtree(self._rootdir)
        return False

    @classmethod
    def from_string(cls, text, key_path=None):
        (mirror_uri, distribution, rest) = text.split(" ", 2)
        return cls(mirror_uri, distribution, rest.split(), key_path=key_path)
