#!/usr/bin/python

"""Cross-platform os tools: files/directories manipulations
Usage:

    ostools.py help
                    prints this help

    ostools.py copytodir FILES... DIR
                    copy files to specified directory

    ostools.py remove [FILES...] [DIRS...]
                    remove files or directories (recursive)
"""

import glob
import os
import shutil
import sys


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        argv = ['help']

    cmd = argv.pop(0)

    if cmd == 'help':
        print __doc__
        return 0

    if cmd == 'copytodir':
        if len(argv) < 2:
            print "Usage:  ostools.py copytodir FILES... DIR"
            return 1

        todir = argv.pop()
        if not os.path.exists(todir):
            os.makedirs(todir)
        if not os.path.isdir(todir):
            print "Error: Destination is not a directory"
            return 2

        files = []
        for possible_glob in argv:
            files += glob.glob(possible_glob)

        for src in files:
            dest = os.path.join(todir, os.path.basename(src))
            shutil.copy(src, dest)
            print "Copied:", src, "=>", dest

        return 0

    if cmd == 'remove':
        if len(argv) == 0:
            print "Usage:  ostools.py remove [FILES...] [DIRS...]"
            return 1

        filesdirs = []
        for possible_glob in argv:
            filesdirs += glob.glob(possible_glob)

        for i in filesdirs:
            if os.path.isdir(i):
                shutil.rmtree(i)
                print "Removed:", i
            elif os.path.isfile(i):
                os.remove(i)
                print "Removed:", i
            else:
                print "Not found:", i

        return 0

    print "Usage error"
    print __doc__
    return 1


if __name__ == "__main__":
    sys.exit(main())
