# Copyright (C) 2009, 2010 Canonical Ltd
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
import platform
import pprint
import sys
import time
from StringIO import StringIO

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
        except ImportError, e:
            trace.mutter("couldn't find apport bug-reporting library: %s" % e)
            pass
        except Exception, e:
            # this should only happen if apport is installed but it didn't
            # work, eg because of an io error writing the crash file
            sys.stderr.write("bzr: failed to report crash using apport:\n "
                "    %r\n" % e)
            pass
    report_bug_legacy(exc_info, stderr)


def report_bug_legacy(exc_info, err_file):
    """Report a bug by just printing a message to the user."""
    trace.print_exception(exc_info, err_file)
    err_file.write('\n')
    err_file.write('bzr %s on python %s (%s)\n' % \
                       (bzrlib.__version__,
                        bzrlib._format_version_tuple(sys.version_info),
                        platform.platform(aliased=1)))
    err_file.write('arguments: %r\n' % sys.argv)
    err_file.write(
        'encoding: %r, fsenc: %r, lang: %r\n' % (
            osutils.get_user_encoding(), sys.getfilesystemencoding(),
            os.environ.get('LANG')))
    err_file.write("plugins:\n")
    err_file.write(_format_plugin_list())
    err_file.write(
        "\n\n"
        "*** Bazaar has encountered an internal error.  This probably indicates a\n"
        "    bug in Bazaar.  You can help us fix it by filing a bug report at\n"
        "        https://bugs.launchpad.net/bzr/+filebug\n"
        "    including this traceback and a description of the problem.\n"
        )


def report_bug_to_apport(exc_info, stderr):
    """Report a bug to apport for optional automatic filing.
    """
    # this function is based on apport_package_hook.py, but omitting some of the
    # Ubuntu-specific policy about what to report and when

    # if the import fails, the exception will be caught at a higher level and
    # we'll report the error by other means
    import apport

    crash_filename = _write_apport_report_to_file(exc_info)

    trace.print_exception(exc_info, stderr)
    if crash_filename is None:
        stderr.write("\n"
            "apport is set to ignore crashes in this version of bzr.\n"
            )
    else:
        stderr.write("\n"
            "You can report this problem to Bazaar's developers by running\n"
            "    apport-bug %s\n"
            "if a bug-reporting window does not automatically appear.\n"
            % (crash_filename))
        # XXX: on Windows, Mac, and other platforms where we might have the
        # apport libraries but not have an apport always running, we could
        # synchronously file now


def _write_apport_report_to_file(exc_info):
    import traceback
    from apport.report import Report

    exc_type, exc_object, exc_tb = exc_info

    pr = Report()
    # add_proc_info gets the executable and interpreter path, which is needed,
    # plus some less useful stuff like the memory map
    pr.add_proc_info()
    pr.add_user_info()

    # Package and SourcePackage are needed so that apport will report about even
    # non-packaged versions of bzr; also this reports on their packaged
    # dependencies which is useful.
    pr['SourcePackage'] = 'bzr'
    pr['Package'] = 'bzr'

    pr['CommandLine'] = pprint.pformat(sys.argv)
    pr['BzrVersion'] = bzrlib.__version__
    pr['PythonVersion'] = bzrlib._format_version_tuple(sys.version_info)
    pr['Platform'] = platform.platform(aliased=1)
    pr['UserEncoding'] = osutils.get_user_encoding()
    pr['FileSystemEncoding'] = sys.getfilesystemencoding()
    pr['Locale'] = os.environ.get('LANG')
    pr['BzrPlugins'] = _format_plugin_list()
    pr['PythonLoadedModules'] = _format_module_list()
    pr['BzrDebugFlags'] = pprint.pformat(debug.debug_flags)

    tb_file = StringIO()
    traceback.print_exception(exc_type, exc_object, exc_tb, file=tb_file)
    pr['Traceback'] = tb_file.getvalue()

    # We want to use the 'bzr' crashdb so that it gets sent directly upstream,
    # which is a reasonable default for most internal errors.  However, if we
    # set it here then apport will crash later if it doesn't know about that
    # crashdb.  Instead, we rely on the bzr package installing both a
    # source hook telling crashes to go to this crashdb, and a crashdb
    # configuration describing it.

    # strip username, hostname, etc
    pr.anonymize()

    if pr.check_ignored():
        # eg configured off in ~/.apport-ignore.xml
        return None
    else:
        crash_file = _open_crash_file()
        pr.write(crash_file)
        crash_file.close()
        return crash_file.name


def _open_crash_file():
    crash_dir = config.crash_dir()
    if not osutils.isdir(crash_dir):
        # on unix this should be /var/crash and should already exist; on
        # Windows or if it's manually configured it might need to be created,
        # and then it should be private
        os.makedirs(crash_dir, mode=0600)
    date_string = time.strftime('%Y-%m-%dT%H:%M', time.gmtime())
    filename = 'bzr.%d.%s.crash' % (
        os.getuid(),
        date_string)
    return open(osutils.pathjoin(crash_dir, filename), 'wt')


def _format_plugin_list():
    plugin_lines = []
    for name, a_plugin in sorted(plugin.plugins().items()):
        plugin_lines.append("  %-20s %s [%s]" %
            (name, a_plugin.path(), a_plugin.__version__))
    return '\n'.join(plugin_lines)


def _format_module_list():
    return pprint.pformat(sys.modules)
