#! /usr/bin/env python

# Copyright (C) 2005 Canonical Ltd

"""Print to stdout a description of the current directory,
formatted as a Python data structure.

This can be useful in tests that need to recreate directory
contents."""

import os
import sys

from breezy.trace import enable_default_logging
enable_default_logging()
from breezy.selftest.treeshape import capture_tree_contents

def main(argv):
    # a lame reimplementation of pformat that splits multi-line
    # strings into concatenated string literals.
    print('[')
    for tt in capture_tree_contents('.'):
        assert isinstance(tt, tuple)
        print('    (', repr(tt[0]) + ',', end=' ')
        if len(tt) == 1:
            print('),')
        else:
            assert len(tt) == 2
            val = tt[1]
            print()
            if val == '':
                print("        ''")
            else:
                for valline in val.splitlines(True):
                    print('       ', repr(valline))
            print('    ),')
    print(']')

if __name__ == '__main__':
    sys.exit(main(sys.argv))
