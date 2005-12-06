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



"""Text UI, write output to the console.
"""

import getpass
import sys

import bzrlib.progress
from bzrlib.ui import UIFactory


class TextUIFactory(UIFactory):
    def progress_bar(self):

        # this in turn is abstract, and creates either a tty or dots
        # bar depending on what we think of the terminal
        return bzrlib.progress.ProgressBar()

    def get_password(self, prompt='', **kwargs):
        """Prompt the user for a password.

        :param prompt: The prompt to present the user
        :param kwargs: Arguments which will be expanded into the prompt.
                       This lets front ends display different things if
                       they so choose.
        :return: The password string, return None if the user 
                 canceled the request.
        """
        prompt = (prompt % kwargs).encode(sys.stdout.encoding, 'replace')
        prompt += ': '
        try:
            return getpass.getpass(prompt)
        except KeyboardInterrupt:
            return None

