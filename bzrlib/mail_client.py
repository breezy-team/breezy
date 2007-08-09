# Copyright (C) 2007 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import os
import subprocess
import tempfile

from bzrlib import urlutils


class MailClient(object):

    def compose(self, to, subject, attachment):
        raise NotImplementedError


class Editor(MailClient):

    pass


class Thunderbird(MailClient):

    def compose(self, to, subject, attachment):
        fd, pathname = tempfile.mkstemp('.patch', 'bzr-mail-')
        try:
            os.write(fd, attachment)
        finally:
            os.close(fd)
        cmdline = ['thunderbird']
        cmdline.extend(self._get_compose_commandline(to, subject, pathname))
        subprocess.call(cmdline)

    def _get_compose_commandline(self, to, subject, attach_path):
        message_options = {}
        if to is not None:
            message_options['to'] = to
        if subject is not None:
            message_options['subject'] = subject
        if attach_path is not None:
            message_options['attachment'] = urlutils.local_path_to_url(
                attach_path)
        options_list = ["%s='%s'" % (k, v) for k, v in
                        sorted(message_options.iteritems())]
        return ['-compose', ','.join(options_list)]
