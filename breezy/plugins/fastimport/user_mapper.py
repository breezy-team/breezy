# Copyright (C) 2009 Canonical Ltd
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from email.utils import parseaddr


class UserMapper(object):

    def __init__(self, lines):
        """Create a user-mapper from a list of lines.

        Blank lines and comment lines (starting with #) are ignored.
        Otherwise lines are of the form:

          old-id = new-id

        Each id may be in the following forms:

          name <email>
          name

        If old-id has the value '@', then new-id is the domain to use
        when generating an email from a user-id.
        """
        self._parse(lines)

    def _parse(self, lines):
        self._user_map = {}
        self._default_domain = None
        for line in lines:
            line = line.strip()
            if len(line) == 0 or line.startswith(b'#'):
                continue
            old, new = line.split(b'=', 1)
            old = old.strip()
            new = new.strip()
            if old == b'@':
                self._default_domain = new
                continue
            # Parse each id into a name and email address
            old_name, old_email = self._parse_id(old)
            new_name, new_email = self._parse_id(new)
            # print "found user map: %s => %s" % ((old_name, old_email), (new_name, new_email))
            self._user_map[(old_name, old_email)] = (new_name, new_email)

    def _parse_id(self, id):
        if id.find(b'<') == -1:
            return id, b""
        else:
            return parseaddr(id)

    def map_name_and_email(self, name, email):
        """Map a name and an email to the preferred name and email.

        :param name: the current name
        :param email: the current email
        :result: the preferred name and email
        """
        try:
            new_name, new_email = self._user_map[(name, email)]
        except KeyError:
            new_name = name
            if self._default_domain and not email:
                new_email = b"%s@%s" % (name, self._default_domain)
            else:
                new_email = email
        return new_name, new_email
