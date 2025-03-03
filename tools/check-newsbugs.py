#!/usr/bin/python3
# Simple script that will check which bugs mentioned in NEWS
# are not yet marked Fix Released in Launchpad

import getopt
import re
import sys

if not importlib.util.find_spec("launchpadlib.launchpad"):
    print("Please install launchpadlib")
    sys.exit(1)

try:
    from lazr.restfulclient import errors
except ModuleNotFoundError:
    print("Please install lazr.restfulclient")
    sys.exit(1)
try:
    import hydrazine
except ModuleNotFoundError:
    print("Please install hydrazine from lp:hydrazine")
    sys.exit(1)


options, args = getopt.gnu_getopt(sys.argv, "lw", ["launchpad", "webbrowser"])
options = dict(options)

if len(args) == 1:
    print(
        "Usage: check-newsbugs [--launchpad][--webbrowser] "
        "doc/en/release-notes/brz-x.y.txt"
    )
    print("Options:")
    print("--launchpad     Print out Launchpad mail commands for closing bugs ")
    print("                that are already fixed.")
    print("--webbrowser    Open launchpad bug pages for bugs that are already ")
    print("                fixed.")
    sys.exit(1)


def report_notmarked(bug, task, section):
    print()
    print("Bug %d was mentioned in NEWS but is not marked fix released:" % (bug.id,))
    print("Launchpad title: {}".format(bug.title))
    print("NEWS summary: ")
    print(section)
    if "--launchpad" in options or "-l" in options:
        print("  bug %d" % bug.id)
        print("  affects {}".format(task.bug_target_name))
        print("  status fixreleased")
    if "--webbrowser" in options or "-w" in options:
        import webbrowser

        webbrowser.open("http://pad.lv/{}>".format(bug.id))


def read_news_bugnos(path):
    """Read the bug numbers closed by a particular NEWS file.

    Args:
      path: Path to the NEWS file
    Returns: list of bug numbers that were closed.
    """
    # Pattern to find bug numbers
    bug_pattern = re.compile(r"\#([0-9]+)")
    ret = set()
    with open(path) as f:
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


def print_bug_url(bugno):
    print("<URL:http://pad.lv/{}>".format(bugno))


launchpad = hydrazine.create_session()
bugnos = read_news_bugnos(args[1])
for bugno, section in bugnos:
    try:
        bug = launchpad.bugs[bugno]
    except errors.HTTPError as e:
        if e.response.status == 401:
            print_bug_url(bugno)
            # Private, we can't access the bug content
            print("{} is private and cannot be accessed".format(bugno))
            continue
        raise

    found_brz = False
    fix_released = False
    for task in bug.bug_tasks:
        parts = task.bug_target_name.split("/")
        if len(parts) == 1:
            project = parts[0]
            distribution = None
        else:
            project = parts[0]
            distribution = parts[1]
        if project == "brz":
            found_brz = True
            if not fix_released and task.status == "Fix Released":
                # We could check that the NEWS section and task_status are in
                # sync, but that would be overkill. (case at hand: bug #416732)
                fix_released = True

    if not found_brz:
        print_bug_url(bugno)
        print(f"Bug {bugno} was mentioned in NEWS but is not marked as affecting brz")
    elif not fix_released:
        print_bug_url(bugno)
        report_notmarked(bug, task, section)
