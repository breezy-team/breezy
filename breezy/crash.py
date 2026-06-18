# Copyright (C) 2009-2011 Canonical Ltd
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

A crash is an exception propagated up almost to the top level of Breezy.

If we have apport <https://launchpad.net/apport/>, we store a report of the
crash using apport into its /var/crash spool directory, from where the user
can either manually send it to Launchpad.  In some cases (at least Ubuntu
development releases), Apport may pop up a window asking if they want
to send it.

Without apport, we just write a crash report to stderr and the user can report
this manually if the wish.

We never send crash data across the network without user opt-in.

In principle apport can run on any platform though as of Feb 2010 there seem
to be some portability bugs.

To force this off in brz turn set APPORT_DISABLE in the environment or
-Dno_apport.
"""

# for interactive testing, try the 'brz assert-fail' command
#
# to test with apport it's useful to set
# export APPORT_IGNORE_OBSOLETE_PACKAGES=1

import os
import platform
import pprint
import sys
import time
from io import StringIO

import breezy

from . import bedding, debug, osutils, plugin, trace


def report_bug(exc_info, stderr):
    """Report a bug to the user through either apport or legacy methods.

    This function first tries to report the bug using apport if it's available
    and not disabled. If apport is not available or fails, it falls back to
    the legacy reporting method which prints the error information to stderr.

    Args:
        exc_info: A tuple (exc_type, exc_value, exc_traceback) as returned by
            sys.exc_info(), containing exception information to report.
        stderr: A file-like object where error messages should be written,
            typically sys.stderr.

    Returns:
        None. The function handles bug reporting as a side effect.
    """
    if (debug.debug_flag_enabled("no_apport")) or os.environ.get(
        "APPORT_DISABLE", None
    ):
        return report_bug_legacy(exc_info, stderr)
    try:
        if report_bug_to_apport(exc_info, stderr):
            # wrote a file; if None then report the old way
            return
    except ModuleNotFoundError as e:
        trace.mutter(f"couldn't find apport bug-reporting library: {e}")
    except Exception as e:
        # this should only happen if apport is installed but it didn't
        # work, eg because of an io error writing the crash file
        trace.mutter(f"brz: failed to report crash using apport: {e!r}")
        trace.log_exception_quietly()
    return report_bug_legacy(exc_info, stderr)


def report_bug_legacy(exc_info, err_file):
    """Report a bug by just printing a message to the user.

    This is the legacy method for bug reporting that prints detailed
    information about the crash including the traceback, system information,
    arguments, plugins, and encoding details to help with debugging.

    Args:
        exc_info: A tuple (exc_type, exc_value, exc_traceback) as returned by
            sys.exc_info(), containing exception information to report.
        err_file: A file-like object where the bug report should be written,
            typically sys.stderr.

    Returns:
        None. The function writes the bug report to err_file as a side effect.
    """
    trace.print_exception(exc_info, err_file)
    err_file.write("\n")
    import textwrap

    def print_wrapped(l):
        """Print text wrapped to 78 characters with indented continuation lines."""
        err_file.write(textwrap.fill(l, width=78, subsequent_indent="    ") + "\n")

    print_wrapped(
        "brz {} on python {} ({})\n".format(
            breezy.__version__,
            breezy._format_version_tuple(sys.version_info),
            platform.platform(aliased=1),
        )
    )
    print_wrapped(f"arguments: {sys.argv!r}\n")
    print_wrapped(
        textwrap.fill(
            "plugins: " + plugin.format_concise_plugin_list(),
            width=78,
            subsequent_indent="    ",
        )
        + "\n"
    )
    print_wrapped(
        "encoding: {!r}, fsenc: {!r}, lang: {!r}\n".format(
            osutils.get_user_encoding(),
            sys.getfilesystemencoding(),
            os.environ.get("LANG"),
        )
    )
    # We used to show all the plugins here, but it's too verbose.
    err_file.write(
        "\n"
        "*** Breezy has encountered an internal error.  This probably indicates a\n"
        "    bug in Breezy.  You can help us fix it by filing a bug report at\n"
        "        https://bugs.launchpad.net/brz/+filebug\n"
        "    including this traceback and a description of the problem.\n"
    )


def report_bug_to_apport(exc_info, stderr):
    """Report a bug to apport for optional automatic filing.

    This function attempts to create a crash report using the apport system,
    which can be automatically or manually sent to Launchpad for bug tracking.
    If apport is configured to ignore crashes, no report is generated.

    Args:
        exc_info: A tuple (exc_type, exc_value, exc_traceback) as returned by
            sys.exc_info(), containing exception information to report.
        stderr: A file-like object where error messages should be written,
            typically sys.stderr.

    Returns:
        str or None: The name of the crash file if one was created, or None
            if we didn't write one (e.g., if apport is configured to ignore
            crashes in this version).
    """
    # this function is based on apport_package_hook.py, but omitting some of the
    # Ubuntu-specific policy about what to report and when

    # This import is apparently not used, but we're doing it so that if the
    # import fails, the exception will be caught at a higher level and we'll
    # report the error by other means.
    import apport  # noqa: F401

    crash_filename = _write_apport_report_to_file(exc_info)

    if crash_filename is None:
        stderr.write("\napport is set to ignore crashes in this version of brz.\n")
    else:
        trace.print_exception(exc_info, stderr)
        stderr.write(
            "\n"
            "You can report this problem to Breezy's developers by running\n"
            "    apport-bug {}\n"
            "if a bug-reporting window does not automatically appear.\n".format(
                crash_filename
            )
        )
        # XXX: on Windows, Mac, and other platforms where we might have the
        # apport libraries but not have an apport always running, we could
        # synchronously file now

    return crash_filename


def _write_apport_report_to_file(exc_info):
    """Write a crash report to an apport file.

    This function creates a detailed crash report using the apport Report
    format and writes it to a crash file in the system's crash directory.
    The report includes system information, Python details, Breezy version,
    plugins, loaded modules, and the full traceback.

    Args:
        exc_info: A tuple (exc_type, exc_value, exc_traceback) as returned by
            sys.exc_info(), containing exception information to report.

    Returns:
        str or None: The name of the crash file if one was created, or None
            if the crash was configured to be ignored (e.g., via
            ~/.apport-ignore.xml).
    """
    import traceback

    from apport.report import Report

    exc_type, exc_object, exc_tb = exc_info

    pr = Report()
    # add_proc_info sets the ExecutablePath, InterpreterPath, etc.
    pr.add_proc_info()
    # It also adds ProcMaps which for us is rarely useful and mostly noise, so
    # let's remove it.
    del pr["ProcMaps"]
    pr.add_user_info()

    # Package and SourcePackage are needed so that apport will report about even
    # non-packaged versions of brz; also this reports on their packaged
    # dependencies which is useful.
    pr["SourcePackage"] = "brz"
    pr["Package"] = "brz"

    pr["CommandLine"] = pprint.pformat(sys.argv)
    pr["BrzVersion"] = breezy.__version__
    pr["PythonVersion"] = breezy._format_version_tuple(sys.version_info)
    pr["Platform"] = platform.platform(aliased=1)
    pr["UserEncoding"] = osutils.get_user_encoding()
    pr["FileSystemEncoding"] = sys.getfilesystemencoding()
    pr["Locale"] = os.environ.get("LANG", "C")
    pr["BrzPlugins"] = _format_plugin_list()
    pr["PythonLoadedModules"] = _format_module_list()
    pr["BrzDebugFlags"] = pprint.pformat(debug.debug_flags)

    # actually we'd rather file directly against the upstream product, but
    # apport does seem to count on there being one in there; we might need to
    # redirect it elsewhere anyhow
    pr["SourcePackage"] = "brz"
    pr["Package"] = "brz"

    # tell apport to file directly against the brz package using
    # <https://bugs.launchpad.net/bzr/+bug/391015>
    #
    # XXX: unfortunately apport may crash later if the crashdb definition
    # file isn't present
    pr["CrashDb"] = "brz"

    tb_file = StringIO()
    traceback.print_exception(exc_type, exc_object, exc_tb, file=tb_file)
    pr["Traceback"] = tb_file.getvalue()

    _attach_log_tail(pr)

    # We want to use the 'brz' crashdb so that it gets sent directly upstream,
    # which is a reasonable default for most internal errors.  However, if we
    # set it here then apport will crash later if it doesn't know about that
    # crashdb.  Instead, we rely on the brz package installing both a
    # source hook telling crashes to go to this crashdb, and a crashdb
    # configuration describing it.

    # these may contain some sensitive info (smtp_passwords)
    # TODO: strip that out and attach the rest
    #
    # attach_file_if_exists(report,
    #   os.path.join(dot_brz, 'breezy.conf', 'BrzConfig')
    # attach_file_if_exists(report,
    #   os.path.join(dot_brz, 'locations.conf', 'BrzLocations')

    # strip username, hostname, etc
    pr.anonymize()

    if pr.check_ignored():
        # eg configured off in ~/.apport-ignore.xml
        return None
    else:
        crash_file_name, crash_file = _open_crash_file()
        pr.write(crash_file)
        crash_file.close()
        return crash_file_name


def _attach_log_tail(pr):
    """Attach the tail of the Breezy log file to an apport report.

    This function reads the last 40 lines of the Breezy log file and
    attaches them to the apport report for debugging purposes. If the
    log file cannot be read, the error is recorded in the report.

    Args:
        pr: An apport Report object to which the log tail will be attached.
    """
    try:
        brz_log = open(trace.get_brz_log_filename())
    except OSError as e:
        pr["BrzLogTail"] = repr(e)
        return
    try:
        lines = brz_log.readlines()
        pr["BrzLogTail"] = "".join(lines[-40:])
    finally:
        brz_log.close()


def _open_crash_file():
    """Open a new crash file for writing.

    This function creates a new crash file in the system's crash directory
    with a unique filename based on the current timestamp and user ID.
    The file is created with restricted permissions (0o600) for security.

    Returns:
        tuple: A tuple containing:
            - str: The full path to the crash file
            - file object: An open file object ready for writing the crash report
    """
    crash_dir = bedding.crash_dir()
    if not osutils.isdir(crash_dir):
        # on unix this should be /var/crash and should already exist; on
        # Windows or if it's manually configured it might need to be created,
        # and then it should be private
        os.makedirs(crash_dir, mode=0o600)
    date_string = time.strftime("%Y-%m-%dT%H:%M", time.gmtime())
    # XXX: getuid doesn't work on win32, but the crash directory is per-user
    if sys.platform == "win32":
        user_part = ""
    else:
        user_part = ".%d" % os.getuid()
    filename = osutils.pathjoin(crash_dir, f"brz{user_part}.{date_string}.crash")
    # be careful here that people can't play tmp-type symlink mischief in the
    # world-writable directory
    return filename, os.fdopen(
        os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
    )


def _format_plugin_list():
    """Format the list of loaded Breezy plugins for crash reporting.

    Returns:
        str: A formatted string describing all loaded plugins with their paths.
    """
    return "".join(plugin.describe_plugins(show_paths=True))


def _format_module_list():
    """Format the list of loaded Python modules for crash reporting.

    Returns:
        str: A pretty-printed string representation of all loaded Python modules.
    """
    return pprint.pformat(sys.modules)
