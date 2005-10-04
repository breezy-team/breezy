#! /usr/bin/env python2.4

# Copyright (C) 2005 Canonical Ltd

"""Print to stdout a description of the current directory, 
formatted as a Python data structure.

This can be useful in tests that need to recreate directory
contents."""

# TODO: It'd be nice if this split long strings across 
# multiple lines, relying on Python concatenation of consecutive
# string constants.

import sys
import os
import pprint

from bzrlib.trace import enable_default_logging
enable_default_logging()
from bzrlib.selftest.treeshape import capture_tree_contents

def main(argv):
    print '['
    for tt in capture_tree_contents('.'):
        print `tt`, ','
    print ']'

if __name__ == '__main__':
    sys.exit(main(sys.argv))
