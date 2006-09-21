#!/usr/bin/env python
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
