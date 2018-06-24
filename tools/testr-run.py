#!/usr/bin/python

import argparse
import subprocess
import sys

parser = argparse.ArgumentParser(
    description="Test runner that supports both Python 2 and Python 3.")

parser.add_argument(
    "--load-list", metavar="PATH", help="Path to read list of tests to run from.",
    type=str)
parser.add_argument(
    "--list", help="List available tests.", action="store_true")

args = parser.parse_args()

if args.list:
    subprocess.call(['python', './brz', 'selftest', '--subunit2', '--list'])
    subprocess.call(['python3', './brz', 'selftest', '--subunit2', '--list'])
else:
    py2_args = ''
    py3_args = ''
    if args.load_list:
        import tempfile
        py2f = None
        py3f = None
        with open(args.load_list, 'r') as f:
            for testname in f:
                if testname.startswith("python2."):
                    if py2f is None:
                        py2f = tempfile.NamedTemporaryFile()
                    py2f.write(testname[len('python2.'):])
                elif testname.startswith("python3."):
                    if py3f is None:
                        py3f = tempfile.NamedTemporaryFile()
                    py3f.write(testname[len('python3.'):])
                else:
                    sys.stderr.write("unknown prefix %s\n" % testname)
        if py2f is not None:
            py2_args += ' --load-list=%s'  % py2f.name
        if py3f is not None:
            py3_args += ' --load-list=%s'  % py3f.name
    print >>sys.stderr, 'python ./brz selftest --subunit2 %s | subunit-filter -s --passthrough --rename "^" "python2."' % py2_args
    subprocess.call(
        'python ./brz selftest --subunit2 %s | subunit-filter -s --passthrough --rename "^" "python2."' % py2_args, shell=True)
    subprocess.call(
        'python ./brz selftest --subunit2 %s | subunit-filter -s --passthrough --rename "^" "python3."' % py3_args, shell=True)
