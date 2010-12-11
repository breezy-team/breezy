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


import gzip, os, subprocess, sys

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
            retcode = subprocess.call(args, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        except OSError:
            raise MissingDependency(self.tool_name, self.minimum_version, cmd)

    def _check_lib_available(self, lib):
        try:
            __import__(lib)
        except ImportError:
            raise MissingDependency(self.tool_name, self.minimum_version, lib)

    def generate(self, source, destination, verbose=False, custom=None):
        """Generate a fast import stream.

        :param source: the source filename or URL
        :param destination: filename or '-' for standard output
        :param verbose: if True, output additional diagnostics
        :param custom: a list of custom options to be added to the
          command line of the underlying scripts used. If an option
          and its argument are to be separated by a space, pass them
          as consecutive items.
        """
        raise NotImplementedError(self.generate)

    def get_output_info(self, dest):
        """Get the output streams/filenames given a destination filename.

        :return: outf, basename, marks where
          outf is a file-like object for storing the output,
          basename is the name without the .fi and .gz prefixes
          marks is the name of the marks file to use, if any
        """
        if dest == '-':
            return sys.stdout, None, None
        else:
            #if dest.endswith('.gz'):
            #    outf = gzip.open(dest, 'wb')
            #    base = dest[:-3]
            #else:
            outf = open(dest, 'w')
            base = dest
            if base.endswith(".fi"):
                base = dest[:-3]
            marks = "%s.marks" % (base,)
            return outf, base, marks

    def execute(self, args, outf, cwd=None):
        """Execute a command, capture the output and close files.
        
        :param args: list of arguments making up the command
        :param outf: a file-like object for storing the output,
        :param cwd: current working directory to use
        :return: the return code
        """
        if cwd is not None:
            note("Executing %s in directory %s ..." % (" ".join(args), cwd))
        else:
            note("Executing %s ..." % (" ".join(args),))
        try:
            p = subprocess.Popen(args, stdout=outf, cwd=cwd)
            p.wait()
        finally:
            if outf != sys.stdout:
                outf.close()
        return p.returncode

    def report_results(self, retcode, destination):
        """Report whether the export succeeded or otherwise."""
        if retcode == 0:
            note("Export to %s completed successfully." % (destination,))
        else:
            warning("Export to %s exited with error code %d."
                % (destination, retcode))

    def execute_exporter_script(self, args, outf):
        """Execute an exporter script, capturing the output.
        
        The script must be a Python script under the exporters directory.

        :param args: list of arguments making up the script, the first of
          which is the script name relative to the exporters directory.
        :param outf: a file-like object for storing the output,
        :return: the return code
        """
        # Note: currently assume Python is on the path. We could work around
        # this later (for Windows users say) by packaging the scripts as Python
        # modules and calling their internals directly.
        exporters_dir = os.path.dirname(__file__)
        script_abspath = os.path.join(exporters_dir, args[0])
        actual_args = ['python', script_abspath] + args[1:]
        return self.execute(actual_args, outf)


class CvsExporter(_Exporter):

    def __init__(self):
        self.check_install('cvs2svn', '2.30', ['cvs2bzr'])
        self.check_install('CVS', '1.11', ['cvs'])

    def generate(self, source, destination, verbose=False, custom=None):
        """Generate a fast import stream. See _Exporter.generate() for details."""
        # TODO: pass a custom cvs2bzr-default.options file as soon as
        # cvs2bzr handles --options along with others.
        args = ["cvs2bzr", "--dumpfile", destination]
        outf, base, marks = self.get_output_info(destination)
        # Marks aren't supported by cvs2bzr so no need to set that option
        if custom:
            args.extend(custom)
        args.append(source)
        retcode = self.execute(args, outf)
        self.report_results(retcode, destination)


class DarcsExporter(_Exporter):

    def __init__(self):
        self.check_install('Darcs', '2.2', [('darcs', '--version')])

    def generate(self, source, destination, verbose=False, custom=None):
        """Generate a fast import stream. See _Exporter.generate() for details."""
        args = ["darcs/darcs-fast-export"]
        outf, base, marks = self.get_output_info(destination)
        if marks:
            args.append('--export-marks=%s' % marks)
        if custom:
            args.extend(custom)
        args.append(source)
        retcode = self.execute_exporter_script(args, outf)
        self.report_results(retcode, destination)


class MercurialExporter(_Exporter):

    def __init__(self):
        self.check_install('Mercurial', '1.2', None, ['mercurial'])

    def generate(self, source, destination, verbose=False, custom=None):
        """Generate a fast import stream. See _Exporter.generate() for details."""
        # XXX: Should we add --force here?
        args = ["hg-fast-export.py", "-r", source, "-s"]
        outf, base, marks = self.get_output_info(destination)
        if base:
            args.append('--marks=%s.marks' % (base,))
            args.append('--mapping=%s.mapping' % (base,))
            args.append('--heads=%s.heads' % (base,))
            args.append('--status=%s.status' % (base,))
        if custom:
            args.extend(custom)
        retcode = self.execute_exporter_script(args, outf)
        self.report_results(retcode, destination)


class GitExporter(_Exporter):

    def __init__(self):
        self.cmd_name = "git"
        if sys.platform == 'win32':
            self.cmd_name = "git.cmd"
        self.check_install('Git', '1.6', [self.cmd_name])

    def generate(self, source, destination, verbose=False, custom=None):
        """Generate a fast import stream. See _Exporter.generate() for details."""
        args = [self.cmd_name, "fast-export", "--all", "--signed-tags=warn"]
        outf, base, marks = self.get_output_info(destination)
        if marks:
            marks = os.path.abspath(marks)
            # Note: we don't pass import-marks because that creates
            # a stream of incremental changes, not the full thing.
            # We may support incremental output later ...
            #if os.path.exists(marks):
            #    args.append('--import-marks=%s' % marks)
            args.append('--export-marks=%s' % marks)
        if custom:
            args.extend(custom)
        retcode = self.execute(args, outf, cwd=source)
        self.report_results(retcode, destination)


class MonotoneExporter(_Exporter):

    def __init__(self):
        self.check_install('Monotone', '0.43', ['mtn'])

    def generate(self, source, destination, verbose=False, custom=None):
        """Generate a fast import stream. See _Exporter.generate() for details."""
        args = ["mtn", "git_export"]
        outf, base, marks = self.get_output_info(destination)
        if marks:
            marks = os.path.abspath(marks)
            if os.path.exists(marks):
                args.append('--import-marks=%s' % marks)
            args.append('--export-marks=%s' % marks)
        if custom:
            args.extend(custom)
        retcode = self.execute(args, outf, cwd=source)
        self.report_results(retcode, destination)


class PerforceExporter(_Exporter):

    def __init__(self):
        self.check_install('p4', '2009.1', ['p4'])
        self.check_install('Perforce Python API', '2009.1', None, ['P4'])
        self.check_install('bzrp4', '', None, ['bzrlib.plugins.bzrp4'])

    def generate(self, source, destination, verbose=False, custom=None):
        """Generate a fast import stream. See _Exporter.generate() for details."""
        from bzrlib.plugins.bzrp4 import p4_fast_export
        outf, base, marks = self.get_output_info(destination)
        # Marks aren't supported by p4_fast_export so no need to set that
        # option
        original_stdout = sys.stdout
        sys.stdout = outf
        try:
            retcode = p4_fast_export.main([source])
        finally:
            sys.stdout = original_stdout
        self.report_results(retcode, destination)


class SubversionExporter(_Exporter):

    def __init__(self):
        self.check_install('Python Subversion', '1.4', None,
            ['svn.fs', 'svn.core', 'svn.repos'])

    def generate(self, source, destination, verbose=False, custom=None):
        """Generate a fast import stream. See _Exporter.generate() for details."""
        args = ["svn-fast-export.py"]
        outf, base, marks = self.get_output_info(destination)
        # Marks aren't supported by svn-fast-export so no need to set that option
        if custom:
            args.extend(custom)
        args.append(source)
        retcode = self.execute_exporter_script(args, outf)
        self.report_results(retcode, destination)


def fast_export_from(source, destination, tool, verbose=False, custom=None):
    # Get the exporter
    if tool == 'cvs':
        factory = CvsExporter
    elif tool == 'darcs':
        factory = DarcsExporter
    elif tool == 'hg':
        factory = MercurialExporter
    elif tool == 'git':
        factory = GitExporter
    elif tool == 'mtn':
        factory = MonotoneExporter
    elif tool == 'p4':
        factory = PerforceExporter
    elif tool == 'svn':
        factory = SubversionExporter
    try:
        exporter = factory()
    except MissingDependency, ex:
        raise errors.BzrError(ex.get_message())

    # Do the export
    exporter.generate(source, destination, verbose=verbose,
        custom=custom)
