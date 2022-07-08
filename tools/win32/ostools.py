#!/usr/bin/python3

"""Cross-platform os tools: files/directories manipulations
Usage:

    ostools.py help
                    prints this help

    ostools.py copytodir FILES... DIR
                    copy files to specified directory

    ostools.py copytree FILES... DIR
                    copy files to specified directory keeping relative paths

    ostools.py copydir SOURCE TARGET
                    recursively copy SOURCE directory tree to TARGET directory

    ostools.py remove [FILES...] [DIRS...]
                    remove files or directories (recursive)
"""

import glob
import os
import shutil
import sys

def makedir(dirname):
    if not os.path.exists(dirname):
        os.makedirs(dirname)
    if not os.path.isdir(dirname):
        print("Error: Destination is not a directory", dirname)
        return 2
    return 0

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        argv = ['help']

    cmd = argv.pop(0)

    if cmd == 'help':
        print(__doc__)
        return 0

    if cmd == 'copytodir':
        if len(argv) < 2:
            print("Usage:  ostools.py copytodir FILES... DIR")
            return 1

        todir = argv.pop()
        retcode = makedir(todir)
        if retcode:
            return retcode

        files = []
        for possible_glob in argv:
            files += glob.glob(possible_glob)

        for src in files:
            dest = os.path.join(todir, os.path.basename(src))
            shutil.copy(src, dest)
            print("Copied:", src, "=>", dest)

        return 0

    if cmd == 'copytree':
        if len(argv) < 2:
            print("Usage:  ostools.py copytree FILES... DIR")
            return 1

        todir = argv.pop()
        retcode = makedir(todir)
        if retcode:
            return retcode

        files = []
        for possible_glob in argv:
            files += glob.glob(possible_glob)

        for src in files:
            relative_path = src
            dest = os.path.join(todir, relative_path)
            dest_dir = os.path.dirname(dest)
            retcode = makedir(dest_dir)
            if retcode:
                return retcode
            shutil.copy(src, dest)
            print("Copied:", src, "=>", dest)

        return 0

    if cmd == 'copydir':
        if len(argv) != 2:
            print("Usage:  ostools.py copydir SOURCE TARGET")
            return 1

        def _copy(src, dest, follow_symlinks=True):
            shutil.copy(src, dest, follow_symlinks=follow_symlinks)
            print("Copied:", src, "=>", dest)
        shutil.copytree(
            argv[0], argv[1],
            copy_function=_copy, dirs_exist_ok=True)

        return 0

    if cmd == 'remove':
        if len(argv) == 0:
            print("Usage:  ostools.py remove [FILES...] [DIRS...]")
            return 1

        filesdirs = []
        for possible_glob in argv:
            filesdirs += glob.glob(possible_glob)

        for i in filesdirs:
            if os.path.isdir(i):
                shutil.rmtree(i)
                print("Removed:", i)
            elif os.path.isfile(i):
                os.remove(i)
                print("Removed:", i)
            else:
                print("Not found:", i)

        return 0

    if cmd == "basename":
        if len(argv) == 0:
            print("Usage:  ostools.py basename [PATH | URL]")
            return 1

        for path in argv:
            print(os.path.basename(path))
        return 0

    if cmd == 'makedir':
        if len(argv) == 0:
            print("Usage:  ostools.py makedir DIR")
            return 1

        retcode = makedir(argv.pop())
        if retcode:
            return retcode
        return 0

    print("Usage error")
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
