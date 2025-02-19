# Copyright (C) 2008, 2009, 2012, 2016 Canonical Ltd
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

"""Views stored within a working tree.

The views are actually in the WorkingTree.views namespace, but these are
1:1 with WorkingTree implementations so can be tested from here.
"""

from breezy import views as _mod_views
from breezy.tests import TestNotApplicable, TestSkipped
from breezy.tests.per_workingtree import TestCaseWithWorkingTree
from breezy.workingtree import WorkingTree


class TestTreeViews(TestCaseWithWorkingTree):
    def setUp(self):
        # formats that don't support views can skip the rest of these
        # tests...
        fmt = self.workingtree_format
        f = fmt.supports_views
        if f is None:
            raise TestSkipped(
                "format %s doesn't declare whether it "
                "supports views, assuming not" % fmt
            )
        if not f():
            raise TestNotApplicable("format %s doesn't support views" % fmt)
        super().setUp()

    def test_views_initially_empty(self):
        wt = self.make_branch_and_tree("wt")
        current, views = wt.views.get_view_info()
        self.assertEqual(None, current)
        self.assertEqual({}, views)

    def test_set_and_get_view_info(self):
        wt = self.make_branch_and_tree("wt")
        view_current = "view-name"
        view_dict = {view_current: ["dir-1"], "other-name": ["dir-2"]}
        wt.views.set_view_info(view_current, view_dict)
        current, views = wt.views.get_view_info()
        self.assertEqual(view_current, current)
        self.assertEqual(view_dict, views)
        # then reopen the tree and see they're still there
        wt = WorkingTree.open("wt")
        current, views = wt.views.get_view_info()
        self.assertEqual(view_current, current)
        self.assertEqual(view_dict, views)
        # test setting a current view which does not exist
        self.assertRaises(
            _mod_views.NoSuchView, wt.views.set_view_info, "yet-another", view_dict
        )
        current, views = wt.views.get_view_info()
        self.assertEqual(view_current, current)
        self.assertEqual(view_dict, views)
        # test clearing the current view
        wt.views.set_view_info(None, view_dict)
        current, views = wt.views.get_view_info()
        self.assertEqual(None, current)
        self.assertEqual(view_dict, views)

    def test_lookup_view(self):
        wt = self.make_branch_and_tree("wt")
        view_current = "view-name"
        view_dict = {view_current: ["dir-1"], "other-name": ["dir-2"]}
        wt.views.set_view_info(view_current, view_dict)
        # test lookup of the default view
        result = wt.views.lookup_view()
        self.assertEqual(result, ["dir-1"])
        # test lookup of a named view
        result = wt.views.lookup_view("other-name")
        self.assertEqual(result, ["dir-2"])

    def test_set_view(self):
        wt = self.make_branch_and_tree("wt")
        # test that set_view sets the current view by default
        wt.views.set_view("view-1", ["dir-1"])
        current, views = wt.views.get_view_info()
        self.assertEqual("view-1", current)
        self.assertEqual({"view-1": ["dir-1"]}, views)
        # test adding a view and not making it the current one
        wt.views.set_view("view-2", ["dir-2"], make_current=False)
        current, views = wt.views.get_view_info()
        self.assertEqual("view-1", current)
        self.assertEqual({"view-1": ["dir-1"], "view-2": ["dir-2"]}, views)

    def test_unicode_view(self):
        wt = self.make_branch_and_tree("wt")
        view_name = "\u3070"
        view_files = ["foo", "bar/"]
        view_dict = {view_name: view_files}
        wt.views.set_view_info(view_name, view_dict)
        current, views = wt.views.get_view_info()
        self.assertEqual(view_name, current)
        self.assertEqual(view_dict, views)

    def test_no_such_view(self):
        wt = self.make_branch_and_tree("wt")
        try:
            wt.views.lookup_view("opaque")
        except _mod_views.NoSuchView as e:
            self.assertEqual(e.view_name, "opaque")
            self.assertEqual(str(e), "No such view: opaque.")
        else:
            self.fail("didn't get expected exception")

    def test_delete_view(self):
        wt = self.make_branch_and_tree("wt")
        view_name = "\N{GREEK SMALL LETTER ALPHA}"
        view_files = ["alphas/"]
        wt.views.set_view(view_name, view_files)
        # now try to delete it
        wt.views.delete_view(view_name)
        # now you can't look it up
        self.assertRaises(_mod_views.NoSuchView, wt.views.lookup_view, view_name)
        # and it's not in the dictionary
        self.assertEqual(wt.views.get_view_info()[1], {})
        # and you can't remove it a second time
        self.assertRaises(_mod_views.NoSuchView, wt.views.delete_view, view_name)
        # or remove a view that never existed
        self.assertRaises(_mod_views.NoSuchView, wt.views.delete_view, view_name + "2")

    def test_check_path_in_view(self):
        wt = self.make_branch_and_tree("wt")
        view_current = "view-name"
        view_dict = {view_current: ["dir-1"], "other-name": ["dir-2"]}
        wt.views.set_view_info(view_current, view_dict)
        self.assertEqual(_mod_views.check_path_in_view(wt, "dir-1"), None)
        self.assertEqual(_mod_views.check_path_in_view(wt, "dir-1/sub"), None)
        self.assertRaises(
            _mod_views.FileOutsideView, _mod_views.check_path_in_view, wt, "dir-2"
        )
        self.assertRaises(
            _mod_views.FileOutsideView, _mod_views.check_path_in_view, wt, "dir-2/sub"
        )
        self.assertRaises(
            _mod_views.FileOutsideView, _mod_views.check_path_in_view, wt, "other"
        )


class TestUnsupportedViews(TestCaseWithWorkingTree):
    """Formats that don't support views should give reasonable errors."""

    def setUp(self):
        fmt = self.workingtree_format
        supported = fmt.supports_views
        if supported is None:
            warn("Format %s doesn't declare whether it supports views or not" % fmt)
            raise TestSkipped("No view support at all")
        if supported():
            raise TestSkipped("Format %s declares that views are supported" % fmt)
            # it's covered by TestTreeViews
        super().setUp()

    def test_view_methods_raise(self):
        wt = self.make_branch_and_tree("wt")
        self.assertRaises(
            _mod_views.ViewsNotSupported,
            wt.views.set_view_info,
            "bar",
            {"bar": ["bars/"]},
        )
        self.assertRaises(_mod_views.ViewsNotSupported, wt.views.get_view_info)
        self.assertRaises(_mod_views.ViewsNotSupported, wt.views.lookup_view, "foo")
        self.assertRaises(_mod_views.ViewsNotSupported, wt.views.set_view, "foo", "bar")
        self.assertRaises(_mod_views.ViewsNotSupported, wt.views.delete_view, "foo")
