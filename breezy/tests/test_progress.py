# Copyright (C) 2006-2011 Canonical Ltd
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

import codecs
import io

from .. import tests
from ..progress import ProgressTask
from ..ui.text import TextProgressView
from . import ui_testing


class TestTextProgressView(tests.TestCase):
    """Tests for text display of progress bars.

    These try to exercise the progressview independently of its construction,
    which is arranged by the TextUIFactory.
    """

    # The ProgressTask now connects directly to the ProgressView, so we can
    # check them independently of the factory or of the determination of what
    # view to use.

    def make_view_only(self, out, width=79):
        view = TextProgressView(out)
        view._avail_width = lambda: width
        return view

    def make_view(self):
        out = ui_testing.StringIOWithEncoding()
        return out, self.make_view_only(out)

    def make_task(self, parent_task, view, msg, curr, total):
        # would normally be done by UIFactory; is done here so that we don't
        # have to have one.
        task = ProgressTask(parent_task, progress_view=view)
        task.msg = msg
        task.current_cnt = curr
        task.total_cnt = total
        return task

    def test_clear(self):
        # <https://bugs.launchpad.net/bzr/+bug/611127> clear must actually
        # send spaces to clear the line
        out, view = self.make_view()
        task = self.make_task(None, view, "reticulating splines", 5, 20)
        view.show_progress(task)
        self.assertEqual(
            "\r/ reticulating splines 5/20                                                    \r",
            out.getvalue(),
        )
        view.clear()
        self.assertEqual(
            "\r/ reticulating splines 5/20                                                    \r"
            + "\r"
            + 79 * " "
            + "\r",
            out.getvalue(),
        )

    def test_render_progress_no_bar(self):
        """The default view now has a spinner but no bar."""
        out, view = self.make_view()
        # view.enable_bar = False
        task = self.make_task(None, view, "reticulating splines", 5, 20)
        view.show_progress(task)
        self.assertEqual(
            "\r/ reticulating splines 5/20                                                    \r",
            out.getvalue(),
        )

    def test_render_progress_easy(self):
        """Just one task and one quarter done."""
        out, view = self.make_view()
        view.enable_bar = True
        task = self.make_task(None, view, "reticulating splines", 5, 20)
        view.show_progress(task)
        self.assertEqual(
            "\r[####/               ] reticulating splines 5/20                               \r",
            out.getvalue(),
        )

    def test_render_progress_nested(self):
        """Tasks proportionally contribute to overall progress."""
        out, view = self.make_view()
        task = self.make_task(None, view, "reticulating splines", 0, 2)
        task2 = self.make_task(task, view, "stage2", 1, 2)
        view.show_progress(task2)
        view.enable_bar = True
        # so we're in the first half of the main task, and half way through
        # that
        self.assertEqual(
            "[####-               ] reticulating splines:stage2 1/2                         ",
            view._render_line(),
        )
        # if the nested task is complete, then we're all the way through the
        # first half of the overall work
        task2.update("stage2", 2, 2)
        self.assertEqual(
            "[#########\\          ] reticulating splines:stage2 2/2                         ",
            view._render_line(),
        )

    def test_render_progress_sub_nested(self):
        """Intermediate tasks don't mess up calculation."""
        out, view = self.make_view()
        view.enable_bar = True
        task_a = ProgressTask(None, progress_view=view)
        task_a.update("a", 0, 2)
        task_b = ProgressTask(task_a, progress_view=view)
        task_b.update("b")
        task_c = ProgressTask(task_b, progress_view=view)
        task_c.update("c", 1, 2)
        # the top-level task is in its first half; the middle one has no
        # progress indication, just a label; and the bottom one is half done,
        # so the overall fraction is 1/4
        self.assertEqual(
            "[####|               ] a:b:c 1/2                                               ",
            view._render_line(),
        )

    def test_render_truncated(self):
        # when the bar is too long for the terminal, we prefer not to truncate
        # the counters because they might be interesting, and because
        # truncating the numbers might be misleading
        out, view = self.make_view()
        task_a = ProgressTask(None, progress_view=view)
        task_a.update("start_" + "a" * 200 + "_end", 2000, 5000)
        line = view._render_line()
        self.assertEqual(
            "- start_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.. 2000/5000",
            line,
        )
        self.assertEqual(len(line), 79)

    def test_render_with_activity(self):
        # if the progress view has activity, it's shown before the spinner
        out, view = self.make_view()
        task_a = ProgressTask(None, progress_view=view)
        view._last_transport_msg = "   123kB   100kB/s "
        line = view._render_line()
        self.assertEqual(
            "   123kB   100kB/s /                                                           ",
            line,
        )
        self.assertEqual(len(line), 79)

        task_a.update("start_" + "a" * 200 + "_end", 2000, 5000)
        view._last_transport_msg = "   123kB   100kB/s "
        line = view._render_line()
        self.assertEqual(
            "   123kB   100kB/s \\ start_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.. 2000/5000",
            line,
        )
        self.assertEqual(len(line), 79)

    def test_render_progress_unicode_enc_utf8(self):
        out = ui_testing.StringIOWithEncoding()
        out.encoding = "utf-8"
        view = self.make_view_only(out, 20)
        task = self.make_task(None, view, "\xa7", 0, 1)
        view.show_progress(task)
        self.assertEqual("\r/ \xa7 0/1            \r", out.getvalue())

    def test_render_progress_unicode_enc_missing(self):
        out = codecs.getwriter("ascii")(io.BytesIO())
        self.assertRaises(AttributeError, getattr, out, "encoding")
        view = self.make_view_only(out, 20)
        task = self.make_task(None, view, "\xa7", 0, 1)
        view.show_progress(task)
        self.assertEqual(b"\r/ ? 0/1             \r", out.getvalue())

    def test_render_progress_unicode_enc_none(self):
        out = ui_testing.StringIOWithEncoding()
        out.encoding = None
        view = self.make_view_only(out, 20)
        task = self.make_task(None, view, "\xa7", 0, 1)
        view.show_progress(task)
        self.assertEqual("\r/ ? 0/1             \r", out.getvalue())
