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

import subprocess


class NoAptSources(Exception):
    """No apt sources were configured."""


class AptSourceError(Exception):
    """An error occured while running 'apt source'."""

    def __init__(self, reason):
        self.reason = reason


class Apt:

    def iter_sources(self, distribution):
        raise NotImplementedError(self.iter_sources)

    def iter_binaries(self, distribution):
        raise NotImplementedError(self.iter_binaries)

    def retrieve_source(self, package_name, target_directory):
        raise NotImplementedError(self.retrieve_source)


class LocalApt(Apt):

    def iter_sources(self, distribution):
        raise NotImplementedError(self.iter_sources)

    def retrieve_source(self, package_name, target):
        try:
            subprocess.run(
                ["apt", "source", package_name],
                cwd=target,
                check=True,
                stderr=subprocess.PIPE,
            )
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


class RemoteApt(Apt):

    def __init__(self, mirror_uri):
        self.mirror_uri = mirror_uri
