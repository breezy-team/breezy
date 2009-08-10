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


import os, subprocess

from bzrlib import errors
from bzrlib.trace import note, warning


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
            retcode = subprocess.call(args, stdout=subprocess.PIPE)
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
        :param parameters: a dictionary of custom conversion parameters
        """
        #raise errors.BzrError("fast-import file generation from %s still under development" % self.tool_name)
        raise NotImplementedError(self.generate)

    def get_output_info(self, dest):
        """Get the output streams/filenames given a destination filename.

        :return: outf, logf, marks, logname where
          outf is a file-like object for storing the output,
          logf is a file-like object for storing the log,
          marks is the name of the marks file to use, if any
          logname is the name of the log stream
        """
        if dest == '-':
            return sys.stdout, sys.stderr, None, "standard error"
        else:
            # TODO: implicitly compress the output if dest ends in '.gz'
            outf = open(dest, 'w')
            base = dest
            if base.endswith(".fi"):
                base = dest[:-3]
            log = "%s.log" % (base,)
            logf = open(log, 'w')
            marks = "%s.marks" % (base,)
            #print "%s output info is %s, %s" % (dest, log, marks)
            return outf, logf, marks, log

    def execute(self, args, outf, logf, cwd=None):
        """Execute a command, capturing the output.
        
        :param args: list of arguments making up the command
        :param outf: a file-like object for storing the output,
        :param logf: a file-like object for storing the log,
        :param cwd: current working directory to use
        :return: the return code
        """
        if cwd is not None:
            note("Executing %s in directory %s ..." % (" ".join(args), source))
        else:
            note("Executing %s ..." % (" ".join(args),))
        p = subprocess.Popen(args, stdout=outf, stderr=logf, cwd=cwd)
        p.wait()
        return p.returncode

    def report_results(self, retcode, destination, logname):
        """Report whether the export succeeded or otherwise."""
        if retcode == 0:
            note("Export to %s completed successfully." % (destination,))
        else:
            warning("Export to %s exited with error code %d."
                " See %s for details." % (destination, retcode, logname))

    def execute_exporter_script(self, args, outf, logf):
        """Execute an exporter script, capturing the output.
        
        The script must be a Python script under the exporters directory.

        :param args: list of arguments making up the script, the first of
          which is the script name relative to the exporters directory.
        :param outf: a file-like object for storing the output,
        :param logf: a file-like object for storing the log,
        :param cwd: current working directory to use
        :return: the return code
        """
        # Note: currently assume Python is on the path. We could work around
        # this later (for Windows users say) by packaging the scripts as Python
        # modules and calling their internals directly.
        exporters_dir = os.path.dirname(__file__)
        script_abspath = os.path.join(exporters_dir, args[0])
        actual_args = ['python', script_abspath] + args[1:]
        return self.execute(actual_args, outf, logf)


class DarcsExporter(_Exporter):

    def __init__(self):
        self.check_install('Darcs', '2.2', [('darcs', '--version')])


class MercurialExporter(_Exporter):

    def __init__(self):
        self.check_install('Mercurial', '1.2', None, ['mercurial'])

    def generate(self, source, destination, verbose=False, parameters=None):
        """Generate a fast import stream. See _Exporter.generate() for details."""
        args = ["hg-fast-export.py", "-s", "--force"]
        args.append('-r %s' % source)
        outf, logf, marks, logname = self.get_output_info(destination)
        if marks:
            args.append('--marks=%s' % marks)
        retcode = self.execute_exporter_script(args, outf, logf)
        self.report_results(retcode, destination, logname)


class GitExporter(_Exporter):

    def __init__(self):
        self.check_install('Git', '1.6', ['git'])

    def generate(self, source, destination, verbose=False, parameters=None):
        """Generate a fast import stream. See _Exporter.generate() for details."""
        args = ["git", "fast-export", "--all", "--signed-tags=warn"]
        outf, logf, marks, logname = self.get_output_info(destination)
        if marks:
            marks = os.path.abspath(marks)
            # Note: we don't pass import-marks because that creates
            # a stream of incremental changes, not the full thing.
            # We may support incremental output later ...
            #if os.path.exists(marks):
            #    args.append('--import-marks=%s' % marks)
            args.append('--export-marks=%s' % marks)
        retcode = self.execute(args, outf, logf, cwd=source)
        self.report_results(retcode, destination, logname)


class SubversionExporter(_Exporter):

    def __init__(self):
        self.check_install('Python Subversion', '1.4', None,
            ['svn.fs', 'svn.core', 'svn.repos'])


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
    exporter.generate(source, destination, verbose=verbose,
        parameters=parameters)
