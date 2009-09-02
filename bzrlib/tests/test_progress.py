# Copyright (C) 2006, 2007, 2009 Canonical Ltd
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


import os
from StringIO import StringIO

from bzrlib import errors
from bzrlib.progress import (
    ProgressTask,
    )
from bzrlib.symbol_versioning import (
    deprecated_in,
    )
from bzrlib.tests import TestCase
from bzrlib.ui.text import (
    TextProgressView,
    )


class _TTYStringIO(StringIO):
    """A helper class which makes a StringIO look like a terminal"""

    def isatty(self):
        return True


class _NonTTYStringIO(StringIO):
    """Helper that implements isatty() but returns False"""

    def isatty(self):
        return False


class TestTextProgressView(TestCase):
    """Tests for text display of progress bars.

    These try to exercise the progressview independently of its construction,
    which is arranged by the TextUIFactory.
    """
    # The ProgressTask now connects directly to the ProgressView, so we can
    # check them independently of the factory or of the determination of what
    # view to use.
    
    def make_view(self):
        out = StringIO()
        view = TextProgressView(out)
        view._width = 80
        return out, view
    
    def make_task(self, parent_task, view, msg, curr, total):
        # would normally be done by UIFactory; is done here so that we don't
        # have to have one.
        task = ProgressTask(parent_task, progress_view=view)
        task.msg = msg
        task.current_cnt = curr
        task.total_cnt = total
        return task

    def test_render_progress_easy(self):
        """Just one task and one quarter done"""
        out, view = self.make_view()
        task = self.make_task(None, view, 'reticulating splines', 5, 20)
        view.show_progress(task)
        self.assertEqual(
'\r[####/               ] reticulating splines 5/20                               \r'
            , out.getvalue())

    def test_render_progress_nested(self):
        """Tasks proportionally contribute to overall progress"""
        out, view = self.make_view()
        task = self.make_task(None, view, 'reticulating splines', 0, 2)
        task2 = self.make_task(task, view, 'stage2', 1, 2)
        view.show_progress(task2)
        # so we're in the first half of the main task, and half way through
        # that
        self.assertEqual(
r'[####-               ] reticulating splines:stage2 1/2'
            , view._render_line())
        # if the nested task is complete, then we're all the way through the
        # first half of the overall work
        task2.update('stage2', 2, 2)
        self.assertEqual(
r'[#########\          ] reticulating splines:stage2 2/2'
            , view._render_line())

    def test_render_progress_sub_nested(self):
        """Intermediate tasks don't mess up calculation."""
        out, view = self.make_view()
        task_a = ProgressTask(None, progress_view=view)
        task_a.update('a', 0, 2)
        task_b = ProgressTask(task_a, progress_view=view)
        task_b.update('b')
        task_c = ProgressTask(task_b, progress_view=view)
        task_c.update('c', 1, 2)
        # the top-level task is in its first half; the middle one has no
        # progress indication, just a label; and the bottom one is half done,
        # so the overall fraction is 1/4
        self.assertEqual(
            r'[####|               ] a:b:c 1/2'
            , view._render_line())
