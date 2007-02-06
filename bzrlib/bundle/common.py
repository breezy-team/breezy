# Copyright (C) 2006 Canonical Ltd
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
"""\
Common entries, like strings, etc, for the bundle reading + writing code.
"""

import bzrlib

header_str = 'Bazaar revision bundle v'
version = (0, 8)


def get_header():
    return [
        header_str + '.'.join([str(v) for v in version]),
        ''
    ]

      
if __name__ == '__main__':
    import doctest
    doctest.testmod()
