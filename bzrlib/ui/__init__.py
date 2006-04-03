# Copyright (C) 2005 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA



"""UI abstraction.

This tells the library how to display things to the user.  Through this
layer different applications can choose the style of UI.

At the moment this layer is almost trivial: the application can just
choose the style of progress bar.

Set the ui_factory member to define the behaviour.  The default
displays no output.
"""


import bzrlib.progress
from bzrlib.symbol_versioning import *


class UIFactory(object):
    """UI abstraction.

    This tells the library how to display things to the user.  Through this
    layer different applications can choose the style of UI.
    """

    def __init__(self):
        super(UIFactory, self).__init__()
        self._progress_bar_stack = None

    @deprecated_method(zero_eight)
    def progress_bar(self):
        """See UIFactory.nested_progress_bar()."""
        raise NotImplementedError(self.progress_bar)

    def get_password(self, prompt='', **kwargs):
        """Prompt the user for a password.

        :param prompt: The prompt to present the user
        :param kwargs: Arguments which will be expanded into the prompt.
                       This lets front ends display different things if
                       they so choose.
        :return: The password string, return None if the user 
                 canceled the request.
        """
        raise NotImplementedError(self.get_password)
        
    def nested_progress_bar(self):
        """Return a nested progress bar.

        When the bar has been finished with, it should be released bu calling
        bar.finished().
        """
        raise NotImplementedError(self.nested_progress_bar)

    def clear_term(self):
        """Prepare the terminal for output.

        This will, for example, clear text progress bars, and leave the
        cursor at the leftmost position."""
        raise NotImplementedError(self.clear_term)


class SilentUIFactory(UIFactory):
    """A UI Factory which never prints anything.

    This is the default UI, if another one is never registered.
    """

    @deprecated_method(zero_eight)
    def progress_bar(self):
        """See UIFactory.nested_progress_bar()."""
        return bzrlib.progress.DummyProgress()

    def get_password(self, prompt='', **kwargs):
        return None

    def nested_progress_bar(self):
        if self._progress_bar_stack is None:
            self._progress_bar_stack = bzrlib.progress.ProgressBarStack(
                klass=bzrlib.progress.DummyProgress)
        return self._progress_bar_stack.get_nested()

    def clear_term(self):
        pass


def clear_decorator(func, *args, **kwargs):
    """Decorator that clears the term"""
    ui_factory.clear_term()
    func(*args, **kwargs)


ui_factory = SilentUIFactory()
"""IMPORTANT: never import this symbol directly. ONLY ever access it as 
ui.ui_factory."""
