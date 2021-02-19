# Copyright (C) 2005-2013, 2016 Canonical Ltd
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


"""Black-box tests for bzr.

These check that it behaves properly when it's invoked through the regular
command-line interface. This doesn't actually run a new interpreter but
rather starts again from the run_brz function.
"""


from breezy import tests


def load_tests(loader, basic_tests, pattern):
    suite = loader.suiteClass()
    # add the tests for this module
    suite.addTests(basic_tests)

    prefix = 'breezy.tests.blackbox.'
    testmod_names = [
        'test_add',
        'test_added',
        'test_alias',
        'test_aliases',
        'test_ancestry',
        'test_annotate',
        'test_bisect',
        'test_big_file',
        'test_branch',
        'test_branches',
        'test_break_lock',
        'test_bound_branches',
        'test_bundle_info',
        'test_cat',
        'test_cat_revision',
        'test_check',
        'test_checkout',
        'test_clean_tree',
        'test_clone',
        'test_command_encoding',
        'test_commit',
        'test_config',
        'test_conflicts',
        'test_cp',
        'test_debug',
        'test_deleted',
        'test_diff',
        'test_exceptions',
        'test_export',
        'test_export_pot',
        'test_fetch_ghosts',
        'test_filesystem_cicp',
        'test_filtered_view_ops',
        'test_find_merge_base',
        'test_help',
        'test_hooks',
        'test_import',
        'test_ignore',
        'test_ignored',
        'test_info',
        'test_init',
        'test_inventory',
        'test_join',
        'test_link_tree',
        'test_locale',
        'test_log',
        'test_logformats',
        'test_lookup_revision',
        'test_ls',
        'test_lsprof',
        'test_merge',
        'test_merge_directive',
        'test_missing',
        'test_mkdir',
        'test_modified',
        'test_mv',
        'test_nick',
        'test_non_ascii',
        'test_outside_wt',
        'test_pack',
        'test_patch',
        'test_ping',
        'test_plugins',
        'test_pull',
        'test_push',
        'test_reconcile',
        'test_reconfigure',
        'test_reference',
        'test_remerge',
        'test_remove',
        'test_re_sign',
        'test_remember_option',
        'test_remove_tree',
        'test_repair_workingtree',
        'test_resolve',
        'test_resolve_location',
        'test_revert',
        'test_revno',
        'test_revision_history',
        'test_revision_info',
        'test_rmbranch',
        'test_script',
        'test_selftest',
        'test_send',
        'test_serve',
        'test_shared_repository',
        'test_shell_complete',
        'test_shelve',
        'test_sign_my_commits',
        'test_verify_signatures',
        'test_split',
        'test_status',
        'test_switch',
        'test_tags',
        'test_testament',
        'test_too_much',
        'test_uncommit',
        'test_unknowns',
        'test_update',
        'test_upgrade',
        'test_version',
        'test_version_info',
        'test_versioning',
        'test_view',
        'test_whoami',
        ]
    # add the tests for the sub modules
    suite.addTests(loader.loadTestsFromModuleNames(
        [prefix + module_name for module_name in testmod_names]))
    return suite


class ExternalBase(tests.TestCaseWithTransport):
    """Don't use this class anymore, use TestCaseWithTransport or similar"""
