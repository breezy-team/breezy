#    __init__.py -- The plugin for bzr
#    Copyright (C) 2005 Jamie Wilkinson <jaq@debian.org> 
#                  2006, 2007 James Westby <jw+debian@jameswestby.net>
#                  2007 Reinhard Tartler <siretart@tauware.de>
#                  2008 Canonical Ltd.
#
#    This file is part of brz-debian.
#
#    brz-debian is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    brz-debian is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with brz-debian; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

"""manage versioned Debian packages."""

import os

import breezy
from ...commands import plugin_cmds
from ...hooks import install_lazy_named_hook
from ... import trace

from .info import (
    brz_plugin_version as version_info,
    )


from ...i18n import load_plugin_translations
translation = load_plugin_translations("brz-debian")
gettext = translation.gettext


commands = {
        "builddeb_do": ["bd-do"],
        "builddeb": ["bd", "debuild"],
        "get_orig_source": [],
        "dep3_patch": [],
        "import_dsc": [],
        "import_upstream": [],
        "merge_upstream": ["mu"],
        "debrelease": [],
        }

for command, aliases in commands.items():
    plugin_cmds.register_lazy(
        'cmd_' + command, aliases, __name__ + ".cmds")


def global_conf():
    from ...bedding import config_dir
    return os.path.join(config_dir(), 'builddeb.conf')


default_build_dir = '../build-area'
default_orig_dir = '..'
default_result_dir = '..'


try:
    from ...registry import register_lazy
except ImportError:
    from ...directory_service import (
        AliasDirectory,
        directories,
        )

    directories.register_lazy(
        "apt:", __name__ + '.directory',
        'AptDirectory',
        "Directory that uses Vcs-* control fields in apt to look up branches")
    directories.register_lazy(
        "dgit:", __name__ + '.directory',
        'DgitDirectory',
        "Directory that uses Debian Dgit control fields to look up branches")
    directories.register_lazy(
        "vcs:", __name__ + '.directory',
        'VcsDirectory',
        "Directory that uses local Debian Vcs-* control fields to look up "
        "branches")

    branch_aliases = getattr(AliasDirectory, "branch_aliases", None)
    if branch_aliases is not None:
        branch_aliases.register_lazy(
            "upstream", __name__ + ".directory", "upstream_branch_alias",
            help="upstream branch (for packaging branches)")

    from ...tag import tag_sort_methods
    tag_sort_methods.register_lazy(
        "debversion", __name__ + ".tagging", "sort_debversion",
        "Sort like Debian versions.")

    from ...revisionspec import revspec_registry
    revspec_registry.register_lazy(
        "package:", __name__ + ".revspec", "RevisionSpec_package")
    revspec_registry.register_lazy(
        "upstream:", __name__ + ".revspec", "RevisionSpec_upstream")
else:
    register_lazy(
        "breezy.directory", "directories", "apt:",
        __name__ + '.directory', 'VcsDirectory',
        help="Directory that uses Debian Vcs-* control "
             "fields to look up branches")
    register_lazy(
        "breezy.directory", "AliasDirectory.branch_aliases", "upstream",
        __name__ + ".directory", "upstream_branch_alias",
        help="upstream branch (for packaging branches)")
    register_lazy(
        "breezy.tag", "tag_sort_methods", "debversion",
        __name__ + ".tagging", "sort_debversion",
        "Sort like Debian versions.")
    register_lazy(
        "breezy.revisionspec", "revspec_registry", "package:",
        __name__ + ".revspec", "RevisionSpec_package")
    register_lazy(
        "breezy.revisionspec", "revspec_registry", "upstream:",
        __name__ + ".revspec", "RevisionSpec_upstream")


def debian_changelog_commit_message(commit, start_message):
    if start_message is not None:
        return start_message
    cl_path = "debian/changelog"
    if not commit.work_tree.has_filename(cl_path):
        return start_message
    if not commit.work_tree.is_versioned(cl_path):
        return start_message
    if cl_path in commit.exclude:
        return start_message
    if commit.specific_files and cl_path not in commit.specific_files:
        return start_message
    from .changelog import changelog_changes
    changes = changelog_changes(
        commit.work_tree, commit.work_tree.basis_tree(), cl_path)
    if not changes:
        return start_message

    from .util import strip_changelog_message
    changes = strip_changelog_message(changes)

    return ''.join(changes)


def debian_changelog_commit(commit, start_message):
    """hooked into breezy.msgeditor set_commit_message.
     Set the commit message from debian/changelog and set any LP: #1234 to bug
     fixed tags."""
    from .util import find_bugs_fixed

    changes = debian_changelog_commit_message(commit, start_message)
    if changes is None:
        return None

    bugs_fixed = find_bugs_fixed([changes], commit.work_tree.branch)
    commit.builder._revprops["bugs"] = "\n".join(bugs_fixed)

    return changes


def changelog_merge_hook_factory(merger):
    from . import merge_changelog
    return merge_changelog.ChangeLogFileMerge(merger)


def tree_debian_tag_name(tree, branch, subpath='', vendor=None):
    from .config import BUILD_TYPE_MERGE
    from .import_dsc import (
        DistributionBranch, DistributionBranchSet)
    from .util import (
        debuild_config, find_changelog, MissingChangelogError,
        suite_to_distribution)
    config = debuild_config(tree, subpath=subpath)
    try:
        (changelog, top_level) = find_changelog(
            tree, subpath=subpath,
            merge=(config.build_type == BUILD_TYPE_MERGE))
    except MissingChangelogError:
        # Not a debian package
        return None
    if changelog.distributions == 'UNRELEASED':
        # The changelog still targets 'UNRELEASED', so apparently hasn't been
        # uploaded. XXX: Give a warning of some sort here?
        return None
    if vendor is None:
        vendor = suite_to_distribution(changelog.distributions)
        # TODO(jelmer): Default to local vendor?
    db = DistributionBranch(branch, None)
    dbs = DistributionBranchSet()
    dbs.add_branch(db)
    return db.tag_name(changelog.version, vendor)


def debian_tag_name(branch, revid):
    subpath = ''
    t = branch.repository.revision_tree(revid)
    return tree_debian_tag_name(t, branch, subpath, vendor=None)


def pre_merge_fix_ancestry(merger):
    from .config import BUILD_TYPE_NATIVE
    from .util import debuild_config
    from .merge_package import fix_ancestry_as_needed
    from ...workingtree import WorkingTree
    if not isinstance(merger.this_tree, WorkingTree):
        return
    if getattr(merger, "other_branch", None) is None:
        return
    # This only works for packages that live in the root. That seems fine,
    # though?
    if (not merger.this_tree.is_versioned("debian/changelog") or
            not merger.other_tree.is_versioned("debian/changelog")):
        return
    this_config = debuild_config(merger.this_tree, '')
    other_config = debuild_config(merger.other_tree, '')
    if not (this_config.build_type == BUILD_TYPE_NATIVE or
            other_config.build_type == BUILD_TYPE_NATIVE):
        from .upstream import PackageVersionNotPresent
        try:
            fix_ancestry_as_needed(
                merger.this_tree, merger.other_branch,
                source_revid=merger.other_tree.get_revision_id())
        except PackageVersionNotPresent as e:
            trace.warning(
                gettext(
                    "Not attempting to fix packaging branch ancestry, "
                    "missing pristine tar data for version %s."),
                e.version)


install_lazy_named_hook(
    "breezy.msgeditor", "hooks", "commit_message_template",
    debian_changelog_commit_message,
    "Use changes documented in debian/changelog to suggest "
    "the commit message")
install_lazy_named_hook(
    "breezy.merge", "Merger.hooks",
    'merge_file_content', changelog_merge_hook_factory,
    'Debian Changelog file merge')
install_lazy_named_hook(
    "breezy.branch", "Branch.hooks",
    "automatic_tag_name", debian_tag_name,
    "Automatically determine tag names from Debian version")
install_lazy_named_hook(
    "breezy.merge", "Merger.hooks",
    'pre_merge_fix_ancestry', pre_merge_fix_ancestry,
    'Debian ancestry fixing')


def load_tests(loader, basic_tests, pattern):
    basic_tests.addTest(
        loader.loadTestsFromModuleNames([__name__ + '.tests']))
    return basic_tests
