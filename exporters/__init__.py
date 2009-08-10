# Copyright (C) 2009 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Simplified and unified access to the various xxx-fast-export tools."""


import subprocess

from bzrlib import errors


class MissingDependency(Exception):

    def __init__(self, tool, minimum_version, missing):
        self.tool = tool
        self.minimum_version = minimum_version
        self.missing = missing

    def get_message(self):
        return "%s missing. Please install %s %s or later and try again." % \
            (self.missing, self.tool, self.minimum_version)


class _Exporter(object):

    def check_install(self, tool_name, minimum_version, required_commands=None,
            required_libraries=None):
        """Check dependencies are correctly installed.

        :param tool_name: name of the tool
        :param minimum_version: minimum version required
        :param required_commands: list of commands that must be on the path
        :param required_libraries: list of Python libraries that must be
          available
        :raises MissingDependency: if a required dependency is not found
        """
        self.tool_name = tool_name
        self.minimum_version = minimum_version
        if required_commands:
            for cmd in required_commands:
                self._check_cmd_available(cmd)
        if required_libraries:
            for lib in required_libraries:
                self._check_lib_available(lib)

    def _check_cmd_available(self, cmd):
        try:
            if isinstance(cmd, str):
                args = [cmd]
            else:
                args = cmd
            retcode = subprocess.call(args)
        except OSError:
            raise MissingDependency(self.tool_name, self.minimum_version, cmd)

    def _check_lib_available(self, lib):
        try:
            __import__(lib)
        except ImportError:
            raise MissingDependency(self.tool_name, self.minimum_version, lib)

    def generate(self, source, destination, verbose=False, parameters=None):
        """Generate a fast import stream.

        :param source: the source filename or URL
        :param destination: filename or '-' for standard output
        :param verbose: if True, output additional diagnostics
        :param parameters: a dictionary of custom converison parameters
        """
        #raise NotImplementedError(self.generate)
        raise errors.BzrError("fast-import file generation from %s still under development" % self.tool_name)


class DarcsExporter(_Exporter):

    def __init__(self):
        self.check_install('Darcs', '2.2', [('darcs', '--version')])


class MercurialExporter(_Exporter):

    def __init__(self):
        self.check_install('Mercurial', '1.2', None, ['mercurial'])


class GitExporter(_Exporter):

    def __init__(self):
        self.check_install('Git', '1.6', ['git'])


class SubversionExporter(_Exporter):

    def __init__(self):
        self.check_install('Subversion', '1.4', None, ['svn.fs', 'svn.core', 'svn.repos'])


def fast_export_from(source, destination, tool, verbose=False, parameters=None):
    # Get the exporter
    if tool == 'darcs':
        factory = DarcsExporter
    elif tool == 'hg':
        factory = MercurialExporter
    elif tool == 'git':
        factory = GitExporter
    elif tool == 'svn':
        factory = SubversionExporter
    try:
        exporter = factory()
    except MissingDependency, ex:
        raise errors.BzrError(ex.get_message())

    # Do the export
    exporter.generate(source, destination, verbose, parameters)
