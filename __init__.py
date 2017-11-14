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

"""brz-debian - manage packages in a Bazaar branch."""

from __future__ import absolute_import

import os

import breezy
from ...commands import plugin_cmds

from .info import (
    bzr_plugin_version as version_info,
    )


from ...i18n import load_plugin_translations
translation = load_plugin_translations("brz-debian")
gettext = translation.ugettext


commands = {
        "builddeb_do": ["bd-do"],
        "builddeb": ["bd", "debuild"],
        "get_orig_source": [],
        "dep3_patch": [],
        "dh_make": ["dh_make"],
        "import_dsc": [],
        "import_upstream": [],
        "mark_uploaded": [],
        "merge_upstream": ["mu"],
        }

for command, aliases in commands.iteritems():
    plugin_cmds.register_lazy('cmd_' + command, aliases, 
        __name__ + ".cmds")

builddeb_dir = '.bzr-builddeb'
default_conf = os.path.join(builddeb_dir, 'default.conf')
def global_conf():
    from ...config import config_dir
    return os.path.join(config_dir(), 'builddeb.conf')
local_conf = os.path.join(builddeb_dir, 'local.conf')
new_local_conf = 'debian/local.conf.local'
new_conf = 'debian/bzr-builddeb.conf'

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

    directories.register_lazy("apt:", __name__ + '.directory',
            'VcsDirectory',
            "Directory that uses Debian Vcs-* control fields to look up branches")

    branch_aliases = getattr(AliasDirectory, "branch_aliases", None)
    if branch_aliases is not None:
        branch_aliases.register_lazy("upstream",
                __name__ + ".directory", "upstream_branch_alias",
                help="upstream branch (for packaging branches)")

    from ...tag import tag_sort_methods
    tag_sort_methods.register_lazy("debversion",
        __name__ + ".tagging", "sort_debversion",
        "Sort like Debian versions.")

    from ...revisionspec import revspec_registry
    revspec_registry.register_lazy("package:",
        __name__ + ".revspec", "RevisionSpec_package")
    revspec_registry.register_lazy("upstream:",
        __name__ + ".revspec", "RevisionSpec_upstream")
else:
    register_lazy("breezy.directory", "directories", "apt:",
            __name__ + '.directory', 'VcsDirectory',
            help="Directory that uses Debian Vcs-* control fields to look up branches")
    register_lazy("breezy.directory", "AliasDirectory.branch_aliases", "upstream",
            __name__ + ".directory", "upstream_branch_alias",
            help="upstream branch (for packaging branches)")
    register_lazy("breezy.tag", "tag_sort_methods", "debversion",
        __name__ + ".tagging", "sort_debversion",
        "Sort like Debian versions.")
    register_lazy("breezy.revisionspec", "revspec_registry", "package:",
        __name__ + ".revspec", "RevisionSpec_package")
    register_lazy("breezy.revisionspec", "revspec_registry", "upstream:",
        __name__ + ".revspec", "RevisionSpec_upstream")


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
        old_text = commit.work_tree.basis_tree().get_file(
                change[1][0], file_id=change[0]).readlines()
        new_text = commit.work_tree.get_file(
                change[1][1], file_id=change[0]).readlines()
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
    from .util import strip_changelog_message
    changes = strip_changelog_message(changes)
    return "".join(changes)


def debian_changelog_commit(commit, start_message):
    """hooked into breezy.msgeditor set_commit_message.
     Set the commit message from debian/changelog and set any LP: #1234 to bug
     fixed tags."""
    from .util import (
        debuild_config, find_bugs_fixed)

    t = commit.work_tree
    config = debuild_config(t, False)
    if config.commit_message_from_changelog == False:
        return None

    changes = debian_changelog_commit_message(commit, start_message)
    if changes is None:
        return None

    bugs_fixed = find_bugs_fixed([changes], commit.work_tree.branch)
    commit.builder._revprops["bugs"] = "\n".join(bugs_fixed)

    # Debian Policy Manual states that debian/changelog must be UTF-8
    return changes.decode("utf-8")


def changelog_merge_hook_factory(merger):
    from . import merge_changelog
    return merge_changelog.ChangeLogFileMerge(merger)


def debian_tag_name(branch, revid):
    from .config import BUILD_TYPE_MERGE
    from .errors import MissingChangelogError
    from .import_dsc import (DistributionBranch,
        DistributionBranchSet)
    from .util import debuild_config, find_changelog
    t = branch.repository.revision_tree(revid)
    config = debuild_config(t, False)
    try:
        (changelog, top_level) = find_changelog(t, config.build_type == BUILD_TYPE_MERGE)
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


def start_commit_check_quilt(tree):
    """start_commit hook which checks the state of quilt patches.
    """
    if tree.path2id("debian/patches") is None:
        # No patches to worry about
        return
    from . import util
    this_source_format = util.tree_get_source_format(tree)
    if this_source_format != util.FORMAT_3_0_QUILT:
        from ... import trace
        trace.mutter("skipping smart quilt merge, not a 3.0 (quilt) tree.")
        return
    from .merge_quilt import start_commit_quilt_patches
    start_commit_quilt_patches(tree)


def pre_merge(merger):
    pre_merge_fix_ancestry(merger)
    pre_merge_quilt(merger)


def pre_merge_quilt(merger):
    if getattr(merger, "_no_quilt_unapplying", False):
        return

    if (merger.other_tree.path2id("debian/patches/series") is None and
        merger.this_tree.path2id("debian/patches/series") is None and
        merger.working_tree.path2id("debian/patches/series") is None):
        return

    from ... import trace
    this_source_format = util.tree_get_source_format(merger.this_tree)
    if this_source_format != util.FORMAT_3_0_QUILT:
        trace.mutter("skipping smart quilt merge, not a 3.0 (quilt) tree.")
        return

    from .util import debuild_config
    config = debuild_config(merger.working_tree, merger.working_tree)
    merger.debuild_config = config
    if not config.quilt_smart_merge:
        trace.mutter("skipping smart quilt merge, not enabled.")
        return

    if (merger.other_tree.path2id(".pc/applied-patches") is None and
        merger.this_tree.path2id(".pc/applied-patches") is None and
        merger.working_tree.path2id(".pc/applied-patches") is None):
        return

    from .errors import QuiltUnapplyError
    from .quilt import quilt_pop_all, quilt_series, QuiltError
    from .merge_quilt import tree_unapply_patches
    trace.note("Unapplying quilt patches to prevent spurious conflicts")
    merger._quilt_tempdirs = []
    merger._old_quilt_series = quilt_series(merger.working_tree)
    if merger._old_quilt_series:
        quilt_pop_all(working_dir=merger.working_tree.basedir)
    try:
        merger.this_tree, this_dir = tree_unapply_patches(merger.this_tree,
            merger.this_branch, force=True)
    except QuiltError, e:
        raise QuiltUnapplyError("this", e.stderr)
    else:
        if this_dir is not None:
            merger._quilt_tempdirs.append(this_dir)
    try:
        merger.base_tree, base_dir = tree_unapply_patches(merger.base_tree,
            merger.this_branch, force=True)
    except QuiltError, e:
        raise QuiltUnapplyError("base", e.stderr)
    else:
        if base_dir is not None:
            merger._quilt_tempdirs.append(base_dir)
    other_branch = getattr(merger, "other_branch", None)
    if other_branch is None:
        other_branch = merger.this_branch
    try:
        merger.other_tree, other_dir = tree_unapply_patches(merger.other_tree,
            other_branch, force=True)
    except QuiltError, e:
        raise QuiltUnapplyError("other", e.stderr)
    else:
        if other_dir is not None:
            merger._quilt_tempdirs.append(other_dir)


def post_merge_quilt_cleanup(merger):
    import shutil
    for dir in getattr(merger, "_quilt_tempdirs", []):
        shutil.rmtree(dir)
    config = getattr(merger, "debuild_config", None)
    if config is None:
        # If there is no debuild config, then pre_merge didn't get far enough.
        return
    policy = config.quilt_tree_policy
    if policy is None:
        return
    from .merge_quilt import post_process_quilt_patches
    post_process_quilt_patches(
        merger.working_tree,
        getattr(merger, "_old_quilt_series", []), policy)


def post_build_tree_quilt(tree):
    from .util import debuild_config
    config = debuild_config(tree, tree)
    policy = config.quilt_tree_policy
    if policy is None:
        return
    from .merge_quilt import post_process_quilt_patches
    post_process_quilt_patches(tree, [], policy)


def pre_merge_fix_ancestry(merger):
    from .config import BUILD_TYPE_NATIVE
    from .util import debuild_config
    from .merge_package import fix_ancestry_as_needed
    from ...workingtree import WorkingTree
    if not isinstance(merger.this_tree, WorkingTree):
        return
    if getattr(merger, "other_branch", None) is None:
        return
    if (not merger.this_tree.path2id("debian/changelog") or
        not merger.other_tree.path2id("debian/changelog")):
        return
    this_config = debuild_config(merger.this_tree, merger.this_tree)
    other_config = debuild_config(merger.other_tree, merger.other_tree)
    if not (this_config.build_type == BUILD_TYPE_NATIVE or
            other_config.build_type == BUILD_TYPE_NATIVE):
        from ... import trace
        from .errors import PackageVersionNotPresent
        try:
            fix_ancestry_as_needed(merger.this_tree, merger.other_branch,
                source_revid=merger.other_tree.get_revision_id())
        except PackageVersionNotPresent, e:
            trace.warning(
                gettext("Not attempting to fix packaging branch ancestry, missing pristine tar "
                "data for version %s."), e.version)


from ...hooks import install_lazy_named_hook
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
    'pre_merge', pre_merge,
    'Debian quilt patch (un)applying and ancestry fixing')
install_lazy_named_hook(
    "breezy.merge", "Merger.hooks",
    'post_merge', post_merge_quilt_cleanup,
    'Cleaning up quilt temporary directories')
install_lazy_named_hook(
    "breezy.mutabletree", "MutableTree.hooks",
    'post_build_tree', post_build_tree_quilt,
    'Applying quilt patches.')
install_lazy_named_hook(
    "breezy.mutabletree", "MutableTree.hooks",
    "start_commit", start_commit_check_quilt,
    "Check for (un)applied quilt patches")


def load_tests(loader, basic_tests, pattern):
    basic_tests.addTest(
        loader.loadTestsFromModuleNames([__name__ + '.tests']))
    return basic_tests
