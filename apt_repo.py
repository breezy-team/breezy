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

import os
import pwd
import shutil
import subprocess
import tempfile
from typing import Optional

from debian.deb822 import Dsc, Deb822

from breezy.errors import DependencyNotPresent
from breezy.trace import note


class NoAptSources(Exception):
    """No apt sources were configured."""


class AptSourceError(Exception):
    """An error occured while running 'apt source'."""

    def __init__(self, reason):
        self.reason = reason


class Apt:

    def iter_source_by_name(self, source_name):
        for source in self.iter_sources():
            if source['Package'] == source_name:
                yield source

    def iter_sources(self):
        raise NotImplementedError(self.iter_sources)

    def iter_binaries(self):
        raise NotImplementedError(self.iter_binaries)

    def retrieve_orig(self, source_name, target_directory,
                      orig_version=None):
        raise NotImplementedError(self.retrieve_source)

    def retrieve_source(self, source_name, target_directory,
                        source_version=None):
        raise NotImplementedError(self.retrieve_source)


class LocalApt(Apt):

    def __init__(self, rootdir=None):
        self.apt_pkg = None
        self._rootdir = rootdir

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, self._rootdir)

    def __enter__(self):
        try:
            import apt_pkg
        except ImportError as e:
            raise DependencyNotPresent('apt_pkg', e)
        import apt
        self.apt_pkg = apt_pkg
        self.apt_pkg.init()
        self.cache = apt.Cache(rootdir=self._rootdir)
        if self._rootdir is not None:
            self.apt_pkg.config.set("Dir", self._rootdir)
        return self

    def __exit__(self, exc_tp, exc_val, exc_tb):
        return False

    def iter_sources(self):
        try:
            sources = self.apt_pkg.SourceRecords()
        except SystemError:
            raise NoAptSources()

        sources.restart()
        while sources.step():
            yield Dsc(sources.record)

    def iter_source_by_name(self, source_name):
        try:
            sources = self.apt_pkg.SourceRecords()
        except SystemError:
            raise NoAptSources()

        sources.restart()
        while sources.lookup(source_name):
            yield Dsc(sources.record)

    def iter_binaries(self):
        for pkg in self.cache:
            for version in pkg.versions:
                yield Deb822(version._records.record)

    def retrieve_source(self, package_name, target, source_version=None,
                        tar_only=False):
        self._run_apt_source(package_name, target, source_version,
                             tar_only=tar_only)

    def _get_command(self, package, version_str=None, tar_only=False):
        args = ['apt', 'source', '-d']
        if self._rootdir is not None:
            args.append('-oDir=%s' % self._rootdir)
        if tar_only:
            args.append('--tar-only')
        args.extend([
            '-y', '--only-source',
            ('%s=%s' % (package, version_str))
            if version_str is not None else package])
        return args

    def _run_apt_source(self, package: str, target_dir,
                        version_str: Optional[str] = None,
                        tar_only: bool = False):
        command = self._get_command(package, version_str, tar_only=tar_only)
        try:
            subprocess.run(
                command, cwd=target_dir, stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                check=True)
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.splitlines()
            if stderr[-1] == (
                b"E: You must put some 'source' URIs in your sources.list"
            ):
                raise NoAptSources()
            CS = b"\x1b[1;31mE: \x1b[0m"
            CE = b"\x1b[0m"
            if stderr[-1] == (
                CS + b"You must put some 'deb-src' URIs in your sources.list" +
                CE
            ):
                raise NoAptSources()
            if stderr[-1].startswith(b"E: "):
                raise AptSourceError(stderr[-1][3:].decode())
            if stderr[-1].startswith(CS):
                raise AptSourceError(stderr[-1][len(CS): -len(CE)].decode())
            raise AptSourceError(
                [line.decode("utf-8", "surrogateescape") for line in stderr]
            )


class RemoteApt(LocalApt):

    def __init__(self, mirror_uri, distribution=None, components=None,
                 key_path=None):
        super(RemoteApt, self).__init__()
        self.mirror_uri = mirror_uri
        self.distribution = distribution
        self.components = components
        self.key_path = key_path
        self._rootdir = None

    def __repr__(self):
        return "%s(%r, distribution=%r, components=%r, key_path=%r)" % (
            type(self).__name__, self.mirror_uri, self.distribution,
            self.components, self.key_path)

    def __enter__(self):
        self._rootdir = tempfile.mkdtemp()
        aptdir = os.path.join(self._rootdir, 'etc', 'apt')
        os.makedirs(aptdir)
        if self.key_path:
            tag = "[signed-by=%s]" % self.key_path
        else:
            tag = "[trusted=yes]"
        with open(os.path.join(aptdir, 'sources.list'), 'w') as f:
            f.write('deb %s %s %s %s\n' % (
                tag, self.mirror_uri, self.distribution,
                ' '.join(self.components)))
            f.write('deb-src %s %s %s %s\n' % (
                tag, self.mirror_uri, self.distribution,
                ' '.join(self.components)))
        try:
            import apt
        except ImportError as e:
            raise DependencyNotPresent('apt', e)
        self.cache = apt.Cache(rootdir=self._rootdir)
        self.cache.update()
        try:
            import apt_pkg
        except ImportError as e:
            raise DependencyNotPresent('apt_pkg', e)
        self.apt_pkg = apt_pkg
        self.apt_pkg.init()
        try:
            username = pwd.getpwuid(os.getuid()).pw_name
        except KeyError:
            pass
        else:
            self.apt_pkg.config.set("APT::Sandbox::User", username)
        self.apt_pkg.config.set("Dir", self._rootdir)
        return self

    def __exit__(self, exc_tp, exc_val, exc_tb):
        shutil.rmtree(self._rootdir)
        return False

    @classmethod
    def from_string(cls, text, key_path=None):
        (mirror_uri, distribution, rest) = text.split(' ', 3)
        return cls(mirror_uri, distribution, rest.split(), key_path=key_path)
