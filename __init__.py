#    __init__.py -- The plugin for bzr
#    Copyright (C) 2005 Jamie Wilkinson <jaq@debian.org> 
#                  2006, 2007 James Westby <jw+debian@jameswestby.net>
#                  2007 Reinhard Tartler <siretart@tauware.de>
#                  2008 Canonical Ltd.
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

"""bzr-builddeb - manage packages in a Bazaar branch."""

import os

from bzrlib import msgeditor
from bzrlib.commands import plugin_cmds
from bzrlib.directory_service import directories

from info import (
    bzr_plugin_version as version_info,
    )

commands = {
        "builddeb": ["bd"],
        "merge_upstream": ["mu"],
        "import_dsc": [],
        "bd_do": [],
        "mark_uploaded": [],
        "merge_package": [],
        }

for command, aliases in commands.iteritems():
    plugin_cmds.register_lazy('cmd_' + command, aliases, 
        "bzrlib.plugins.builddeb.cmds")

builddeb_dir = '.bzr-builddeb'
default_conf = os.path.join(builddeb_dir, 'default.conf')
global_conf = os.path.expanduser('~/.bazaar/builddeb.conf')
local_conf = os.path.join(builddeb_dir, 'local.conf')

default_build_dir = '../build-area'
default_orig_dir = '..'
default_result_dir = '..'


directories.register_lazy("deb:", 'bzrlib.plugins.builddeb.directory', 
        'VcsDirectory', 
        "Directory that uses Debian Vcs-* control fields to look up branches")


def debian_changelog_commit_message(commit, start_message):
    if start_message is not None:
        return start_message
    cl_path = "debian/changelog"
    if not commit.work_tree.has_filename(cl_path):
        return start_message
    if commit.work_tree.path2id(cl_path) is None:
        return start_message
    if cl_path in commit.exclude:
        return start_message
    if commit.specific_files and cl_path not in commit.specific_files:
        return start_message
    changes = []
    for change in commit.work_tree.iter_changes(commit.work_tree.basis_tree(),
            specific_files=[cl_path]):
        # Content not changed
        if not change[2]:
            return start_message
        # Not versioned in new tree
        if not change[3][1]:
            return start_message
        # Not a file in one tree
        if change[6][0] != 'file' or change[6][1] != 'file':
            return start_message
        old_text = commit.work_tree.basis_tree().get_file(change[0],
                path=change[1][0]).readlines()
        new_text = commit.work_tree.get_file(change[0],
                path=change[1][1]).readlines()
        import difflib
        sequencematcher = difflib.SequenceMatcher
        for group in sequencematcher(None, old_text,
                new_text).get_grouped_opcodes(0):
            j1, j2 = group[0][3], group[-1][4]
            for line in new_text[j1:j2]:
                if line.startswith("  "):
                    changes.append(line)
    if not changes:
        return start_message
    from bzrlib.plugins.builddeb.util import strip_changelog_message
    changes = strip_changelog_message(changes)
    return "".join(changes)


msgeditor.hooks.install_named_hook("commit_message_template",
        debian_changelog_commit_message,
        "Use changes documented in debian/changelog to suggest "
        "the commit message")


try:
    from bzrlib.revisionspec import revspec_registry
    revspec_registry.register_lazy("package:", "bzrlib.plugins.builddeb.revspec", "RevisionSpec_package")
except ImportError:
    from bzrlib.revisionspec import SPEC_TYPES
    from bzrlib.plugins.builddeb.revspec import RevisionSpec_package
    SPEC_TYPES.append(RevisionSpec_package)


def load_tests(standard_tests, module, loader):
    return loader.loadTestsFromModuleNames(['bzrlib.plugins.builddeb.tests'])
