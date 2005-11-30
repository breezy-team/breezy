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


class UIFactory(object):
    """UI abstraction.

    This tells the library how to display things to the user.  Through this
    layer different applications can choose the style of UI.
    """
    def progress_bar(self):
        raise NotImplementedError


class SilentUIFactory(UIFactory):
    """A UI Factory which never prints anything.

    This is the default UI, if another one is never registered.
    """
    def progress_bar(self):
        return bzrlib.progress.DummyProgress()

ui_factory = SilentUIFactory()
