'''apport package hook for Breezy'''

# Copyright (c) 2009, 2010 Canonical Ltd.
# Author: Matt Zimmerman <mdz@canonical.com>
#         and others

from apport.hookutils import *
import os

brz_log = os.path.expanduser('~/.brz.log')
dot_brz = os.path.expanduser('~/.config/breezy')

def _add_log_tail(report):
    # may have already been added in-process
    if 'BrzLogTail' in report:
        return

    with open(brz_log) as f:
        brz_log_lines = f.readlines()
    brz_log_lines.reverse()

    brz_log_tail = []
    blanks = 0
    for line in brz_log_lines:
        if line == '\n':
            blanks += 1
        brz_log_tail.append(line)
        if blanks >= 2:
            break

    brz_log_tail.reverse()
    report['BrzLogTail'] = ''.join(brz_log_tail)


def add_info(report):
    _add_log_tail(report)
    if 'BrzPlugins' not in report:
        # may already be present in-process
        report['BrzPlugins'] = command_output(['brz', 'plugins', '-v'])

    # by default assume brz crashes are upstream bugs; this relies on
    # having a brz entry under /etc/apport/crashdb.conf.d/
    report['CrashDB'] = 'brz'

    # these may contain some sensitive info (smtp_passwords)
    # TODO: strip that out and attach the rest

    #attach_file_if_exists(report,
    #	os.path.join(dot_brz, 'breezy.conf', 'BrzConfig')
    #attach_file_if_exists(report,
    #	os.path.join(dot_brz, 'locations.conf', 'BrzLocations')


# vim: expandtab shiftwidth=4
