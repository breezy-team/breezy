# Copyright (C) 2005 by Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

"""GPG signing and checking logic."""

import errno
import subprocess

import bzrlib.errors as errors

class LoopbackGPGStrategy(object):

    def __init__(self, ignored):
        """Real strategies take a configuration."""

    def sign(self, content):
        return content


class GPGStrategy(object):
    """GPG Signing and checking facilities."""
        
    def _command_line(self):
        return [self._config.gpg_signing_command(), '--clearsign']

    def __init__(self, config):
        self._config = config

    def sign(self, content):
        try:
            process = subprocess.Popen(self._command_line(),
                                       stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE)
            try:
                result = process.communicate(content)[0]
                if process.returncode is None:
                    process.wait()
                if process.returncode != 0:
                    raise errors.SigningFailed(self._command_line())
                return result
            except OSError, e:
                if e.errno == errno.EPIPE:
                    raise errors.SigningFailed(self._command_line())
                else:
                    raise
        except ValueError:
            # bad subprocess parameters, should never happen.
            raise
        except OSError, e:
            if e.errno == errno.ENOENT:
                # gpg is not installed
                raise errors.SigningFailed(self._command_line())
            else:
                raise
