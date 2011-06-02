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

import bzrlib
from bzrlib.commands import plugin_cmds
from bzrlib.directory_service import directories

from info import (
    bzr_plugin_version as version_info,
    )


commands = {
        "bd_do": [],
        "builddeb": ["bd"],
        "dep3_patch": [],
        "dh_make": ["dh_make"],
        "import_dsc": [],
        "import_upstream": [],
        "mark_uploaded": [],
        "merge_package": [],
        "merge_upstream": ["mu"],
        }

for command, aliases in commands.iteritems():
    plugin_cmds.register_lazy('cmd_' + command, aliases, 
        "bzrlib.plugins.builddeb.cmds")

builddeb_dir = '.bzr-builddeb'
default_conf = os.path.join(builddeb_dir, 'default.conf')
def global_conf():
    from bzrlib.config import config_dir
    return os.path.join(config_dir(), 'builddeb.conf')
local_conf = os.path.join(builddeb_dir, 'local.conf')

default_build_dir = '../build-area'
default_orig_dir = '..'
default_result_dir = '..'


directories.register_lazy("apt:", 'bzrlib.plugins.builddeb.directory', 
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

def debian_changelog_commit(commit, start_message):
    print "debian_changelog_commit()"
    changes = debian_changelog_commit_message(commit, start_message)

    import re
    from bzrlib import bugtracker
    lpmatch = re.findall(r"lp:\s+\#\d+(?:,\s*\#\d+)*", changes, re.I)
    bugs = re.findall(r"\#?\s?(\d+)", ' '.join(lpmatch), re.I)
    print bugs
    bugs_revision_property = ''
    for bug in bugs:
        print "bug: " + bug
        print "url: " + bugtracker.get_bug_url("lp", commit.work_tree.branch, bug)
        bugs_revision_property = bugs_revision_property + bugtracker.get_bug_url("lp", commit.work_tree.branch, bug) + " fixed\n"
    print bugs_revision_property
    commit.builder._revprops["bugs"] = bugs_revision_property
    #commit.builder._revprops["bugs"] = "https://launchpad.net/bugs/6543 fixed\nhttps://launchpad.net/bugs/5431 fixed"
    #print "bugtracker: " + bugtracker.get_bug_url("lp", commit.work_tree.branch, "1234")
    return debian_changelog_commit_message(commit, start_message)

def changelog_merge_hook_factory(merger):
    from bzrlib.plugins.builddeb import merge_changelog
    return merge_changelog.ChangeLogFileMerge(merger)


def debian_tag_name(branch, revid):
    from bzrlib.plugins.builddeb.config import BUILD_TYPE_MERGE
    from bzrlib.plugins.builddeb.errors import MissingChangelogError
    from bzrlib.plugins.builddeb.import_dsc import (DistributionBranch,
        DistributionBranchSet)
    from bzrlib.plugins.builddeb.util import (debuild_config, find_changelog)
    t = branch.repository.revision_tree(revid)
    config = debuild_config(t, False)
    try:
        (changelog, larstiq) = find_changelog(t, config.build_type == BUILD_TYPE_MERGE)
    except MissingChangelogError:
        # Not a debian package
        return None
    if changelog.distributions == 'UNRELEASED':
        # The changelog still targets 'UNRELEASED', so apparently hasn't been 
        # uploaded. XXX: Give a warning of some sort here?
        return None
    db = DistributionBranch(branch, None)
    dbs = DistributionBranchSet()
    dbs.add_branch(db)
    return db.tag_name(changelog.version)


try:
    from bzrlib.hooks import install_lazy_named_hook
except ImportError: # Compatibility with bzr < 2.4
    from bzrlib import (
        branch as _mod_branch,
        errors,
        merge,
        msgeditor,
        )
    msgeditor.hooks.install_named_hook("commit_message_template",
            debian_changelog_commit_message,
            "Use changes documented in debian/changelog to suggest "
            "the commit message")
    if getattr(merge, 'ConfigurableFileMerger', None) is None:
        raise ImportError(
            'need at least bzr 2.1.0rc2 (you use %r)', bzrlib.version_info)
    else:
        merge.Merger.hooks.install_named_hook(
            'merge_file_content', changelog_merge_hook_factory,
            'Debian Changelog file merge')
    try:
        _mod_branch.Branch.hooks.install_named_hook("automatic_tag_name",
             debian_tag_name,
             "Automatically determine tag names from Debian version")
    except errors.UnknownHook:
        pass # bzr < 2.2 doesn't have this hook.
else:
    install_lazy_named_hook(
        "bzrlib.msgeditor", "hooks", "commit_message_template",
            debian_changelog_commit_message,
            "Use changes documented in debian/changelog to suggest "
            "the commit message")
    if bzrlib.version_info[0] >= 2 and bzrlib.version_info[1] >= 4:
        install_lazy_named_hook(
            "bzrlib.msgeditor", "hooks", "set_commit_message",
                debian_changelog_commit,
                "Use changes documented in debian/changelog to set "
                "the commit message and bugs fixed")
    install_lazy_named_hook(
        "bzrlib.merge", "Merger.hooks",
        'merge_file_content', changelog_merge_hook_factory,
        'Debian Changelog file merge')
    install_lazy_named_hook(
        "bzrlib.branch", "Branch.hooks",
        "automatic_tag_name", debian_tag_name,
         "Automatically determine tag names from Debian version")

try:
    from bzrlib.revisionspec import revspec_registry
    revspec_registry.register_lazy("package:",
        "bzrlib.plugins.builddeb.revspec", "RevisionSpec_package")
except ImportError:
    from bzrlib.revisionspec import SPEC_TYPES
    from bzrlib.plugins.builddeb.revspec import RevisionSpec_package
    SPEC_TYPES.append(RevisionSpec_package)

try:
    from bzrlib.tag import tag_sort_methods
except ImportError:
    pass # bzr tags --sort= can not be extended
else:
    tag_sort_methods.register_lazy("debversion",
        "bzrlib.plugins.builddeb.tagging", "sort_debversion",
        "Sort like Debian versions.")


def load_tests(standard_tests, module, loader):
    return loader.loadTestsFromModuleNames(['bzrlib.plugins.builddeb.tests'])
