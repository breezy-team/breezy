#!/usr/bin/env python
"""\
Common entries, like strings, etc, for the changeset reading + writing code.
"""

header_str = 'Bazaar-NG (bzr) changeset v'
version = (0, 0, 5)

def get_header():
    return [
        header_str + '.'.join([str(v) for v in version]),
        'This changeset can be applied with bzr apply-changeset',
        ''
    ]

