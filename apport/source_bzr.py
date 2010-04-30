'''apport package hook for Bazaar'''

# Copyright (c) 2009, 2010 Canonical Ltd.
# Author: Matt Zimmerman <mdz@canonical.com>
#         and others

from apport.hookutils import *
import os

bzr_log = os.path.expanduser('~/.bzr.log')
dot_bzr = os.path.expanduser('~/.bazaar')

def _add_log_tail(report):
    # may have already been added in-process
    if 'BzrLogTail' in report:
        return

    bzr_log_lines = open(bzr_log).readlines()
    bzr_log_lines.reverse()

    bzr_log_tail = []
    blanks = 0
    for line in bzr_log_lines:
        if line == '\n':
            blanks += 1
        bzr_log_tail.append(line)
        if blanks >= 2: 
            break

    bzr_log_tail.reverse()
    report['BzrLogTail'] = ''.join(bzr_log_tail)


def add_info(report):
    _add_log_tail(report)
    if 'BzrPlugins' not in report:
        # may already be present in-process
        report['BzrPlugins'] = command_output(['bzr', 'plugins', '-v'])
        
    # by default assume bzr crashes are upstream bugs; this relies on
    # having a bzr entry under /etc/apport/crashdb.conf.d/
    report['CrashDB'] = 'bzr'

    # these may contain some sensitive info (smtp_passwords)
    # TODO: strip that out and attach the rest

    #attach_file_if_exists(report,
    #	os.path.join(dot_bzr, 'bazaar.conf', 'BzrConfig')
    #attach_file_if_exists(report,
    #	os.path.join(dot_bzr, 'locations.conf', 'BzrLocations')

        
# vim: expandtab shiftwidth=4
