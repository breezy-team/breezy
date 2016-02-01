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
rather starts again from the run_bzr function.
"""


from bzrlib.symbol_versioning import (
    deprecated_in,
    deprecated_method,
    )
from bzrlib import tests


def load_tests(basic_tests, module, loader):
    suite = loader.suiteClass()
    # add the tests for this module
    suite.addTests(basic_tests)

    prefix = 'bzrlib.tests.blackbox.'
    testmod_names = [
                     'test_add',
                     'test_added',
                     'test_alias',
                     'test_aliases',
                     'test_ancestry',
                     'test_annotate',
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
                     'test_command_encoding',
                     'test_commit',
                     'test_config',
                     'test_conflicts',
                     'test_debug',
                     'test_deleted',
                     'test_diff',
                     'test_dump_btree',
                     'test_dpush',
                     'test_exceptions',
                     'test_export',
                     'test_export_pot',
                     'test_filesystem_cicp',
                     'test_filtered_view_ops',
                     'test_find_merge_base',
                     'test_help',
                     'test_hooks',
                     'test_ignore',
                     'test_ignored',
                     'test_info',
                     'test_init',
                     'test_inventory',
                     'test_join',
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
                     'test_ping',
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

    @deprecated_method(deprecated_in((2, 2, 0)))
    def check_output(self, output, *args):
        """Verify that the expected output matches what bzr says.

        The output is supplied first, so that you can supply a variable
        number of arguments to bzr.
        """
        self.assertEqual(self.run_bzr(*args)[0], output)
