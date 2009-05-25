#!/usr/bin/python
# Simple script that will check which bugs mentioned in NEWS 
# are not yet marked Fix Released in Launchpad

import getopt, re, sys
try:
    from launchpadbugs import connector
except ImportError:
    print "Please install launchpadbugs from lp:python-launchpad-bugs"
    sys.exit(1)

options, args = getopt.gnu_getopt(sys.argv, "l", ["launchpad"])
options = dict(options)

if len(args) == 1:
    print "Usage: check-newsbugs [--launchpad] NEWS"
    print "Options:"
    print "--launchpad     Print out Launchpad mail commands for closing bugs "
    print "                that are already fixed."
    sys.exit(1)


def report_notmarked(bug, task, section):
    print 
    print "Bug %d was mentioned in NEWS but is not marked fix released:" % (bug.bugnumber, )
    print "Launchpad title: %s" % bug.title
    print "NEWS summary: "
    print section
    if "--launchpad" in options or "-l" in options:
        print "  bug %d" % bug.bugnumber
        print "  affects bzr"
        print "  status fixreleased"


def read_news_bugnos(path):
    """Read the bug numbers closed by a particular NEWS file

    :param path: Path to the NEWS file
    :return: list of bug numbers that were closed.
    """
    # Pattern to find bug numbers
    bug_pattern = re.compile("\#([0-9]+)")
    ret = set()
    f = open(path, 'r')
    try:
        section = ""
        for l in f.readlines():
            if l.strip() == "":
                try:
                    parenthesed = section.rsplit("(", 1)[1]
                except IndexError:
                    parenthesed = ""
                # Empty line, next section begins
                for bugno in [int(m) for m in bug_pattern.findall(parenthesed)]:
                    ret.add((bugno, section))
                section = ""
            else:
                section += l
        return ret
    finally:
        f.close()

open_bug = connector.ConnectBug("TEXT")

bugnos = read_news_bugnos(args[1])
for bugno, section in bugnos:
    bug = open_bug(url="https://bugs.launchpad.net/bzr/+bug/%d" % bugno)
    found_bzr = False
    for task in bug.infotable:
        if task.affects == "bzr":
            found_bzr = True
            if task.status != "Fix Released":
                report_notmarked(bug, task, section)
    if not found_bzr:
        print "Bug %d was mentioned in NEWS but is not marked as affecting bzr" % bugno
