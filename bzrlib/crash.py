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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


"""Handling and reporting crashes.
"""

# for interactive testing, try the 'bzr assert-fail' command 
# or see http://code.launchpad.net/~mbp/bzr/bzr-fail

import os
import pprint
import sys
import time

import bzrlib
from bzrlib import (
    config,
    debug,
    osutils,
    plugin,
    trace,
    )


def report_bug(exc_info, stderr):
    if 'no_apport' not in debug.debug_flags:
        try:
            report_bug_to_apport(exc_info, stderr)
            return
        except Exception, e:
            sys.stderr.write("failed to report crash using apport: %r"  % e)
            pass
    report_bug_legacy(exc_info, stderr)


def report_bug_legacy(exc_info, err_file):
    """Report a bug by just printing a message to the user."""
    trace.print_exception(exc_info, err_file)
    err_file.write('\n')
    err_file.write('bzr %s on python %s (%s)\n' % \
                       (bzrlib.__version__,
                        bzrlib._format_version_tuple(sys.version_info),
                        sys.platform))
    err_file.write('arguments: %r\n' % sys.argv)
    err_file.write(
        'encoding: %r, fsenc: %r, lang: %r\n' % (
            osutils.get_user_encoding(), sys.getfilesystemencoding(),
            os.environ.get('LANG')))
    err_file.write("plugins:\n")
    for name, a_plugin in sorted(plugin.plugins().items()):
        err_file.write("  %-20s %s [%s]\n" %
            (name, a_plugin.path(), a_plugin.__version__))
    err_file.write(
"""\
*** Bazaar has encountered an internal error.
    Please report a bug at https://bugs.launchpad.net/bzr/+filebug
    including this traceback, and a description of what you
    were doing when the error occurred.
""")


def report_bug_to_apport(exc_info, stderr):
    """Report a bug to apport for optional automatic filing.
    
    :returns: True if the bug was filed or otherwise handled; 
        False to use a fallback method.
    """
    import platform

    # this is based on apport_package_hook.py, but omitting some of the
    # Ubuntu-specific policy about what to report and when
    try:
        from apport.report import Report
    except ImportError, e:
        trace.warning("couldn't find apport bug-reporting library: %s" % e)
        return False

    pr = Report()
    # add_proc_info gives you the memory map of the process: this seems rarely
    # useful for Bazaar and it does make the report harder to scan, though it
    # does tell you what binary modules are loaded.
    # pr.add_proc_info()
    pr.add_user_info()
    pr['BzrVersion'] = bzrlib.__version__
    pr['PythonVersion'] = bzrlib._format_version_tuple(sys.version_info)
    pr['Platform'] = platform.platform(aliased=1)
    pr['UserEncoding'] = osutils.get_user_encoding()
    pr['FileSystemEncoding'] = sys.getfilesystemencoding()
    pr['Locale'] = os.environ.get('LANG')
    pr['BzrPlugins'] = _format_plugin_list()
    pr['PythonLoadedModules'] = _format_module_list()

    crash_file = _open_crash_file()
    try:
        pr.write(crash_file)
    finally:
        crash_file.close()

    stderr.write("Bazaar has encountered an internal error:\n"
        "    %s.%s: %s\n"
        "Details have been written to\n"
        "    %s\n"
        "\n"
        "This probably indicates a bug in Bazaar.  You can help us fix it\n"
        "by filing a bug report at\n"
        "    https://bugs.launchpad.net/bzr/+filebug\n"
        "attaching the crash file, and including a description of the problem.\n"
        % (exc_info[0].__module__, exc_info[0].__name__, exc_info[1],
           crash_file.name))
    return True


def _open_crash_file():
    crash_dir = config.crash_dir()
    # user-readable only, just in case the contents are sensitive.
    if not osutils.isdir(crash_dir):
        os.makedirs(crash_dir, mode=0700)
    filename = 'bzr-%s-%s.crash' % (
        osutils.compact_date(time.time()),
        os.getpid(),)
    return open(osutils.pathjoin(crash_dir, filename), 'wt')


def _format_plugin_list():
    plugin_lines = []
    for name, a_plugin in sorted(plugin.plugins().items()):
        plugin_lines.append("  %-20s %s [%s]" %
            (name, a_plugin.path(), a_plugin.__version__))
    return '\n'.join(plugin_lines)


def _format_module_list():
    return pprint.pformat(sys.modules)
