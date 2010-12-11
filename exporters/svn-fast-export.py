#!/usr/bin/python
#
# svn-fast-export.py
# ----------
#  Walk through each revision of a local Subversion repository and export it
#  in a stream that git-fast-import can consume.
#
# Author: Chris Lee <clee@kde.org>
# License: MIT <http://www.opensource.org/licenses/mit-license.php>

trunk_path = '/trunk/'
branches_path = '/branches/'
tags_path = '/tags/'
address = 'localhost'

first_rev = 1
final_rev = 0

import gc, sys, os.path
from optparse import OptionParser
from time import sleep, mktime, localtime, strftime, strptime
from svn.fs import svn_fs_dir_entries, svn_fs_file_length, svn_fs_file_contents, svn_fs_is_dir, svn_fs_revision_root, svn_fs_youngest_rev, svn_fs_revision_proplist, svn_fs_revision_prop, svn_fs_paths_changed
from svn.core import svn_pool_create, svn_pool_clear, svn_pool_destroy, svn_stream_read, svn_stream_for_stdout, svn_stream_copy, svn_stream_close, run_app
from svn.repos import svn_repos_open, svn_repos_fs

ct_short = ['M', 'A', 'D', 'R', 'X']

def dump_file_blob(root, full_path, pool):
    stream_length = svn_fs_file_length(root, full_path, pool)
    stream = svn_fs_file_contents(root, full_path, pool)
    sys.stdout.write("data %s\n" % stream_length)
    sys.stdout.flush()
    ostream = svn_stream_for_stdout(pool)
    svn_stream_copy(stream, ostream, pool)
    svn_stream_close(ostream)
    sys.stdout.write("\n")


class Matcher(object):

    branch = None

    def __init__(self, trunk_path):
        self.trunk_path = trunk_path

    def branchname(self):
        return self.branch

    def __str__(self):
        return super(Matcher, self).__str__() + ":" + self.trunk_path

    @staticmethod
    def getMatcher(trunk_path):
        if trunk_path.startswith("regex:"):
            return RegexStringMatcher(trunk_path)
        else:
            return StaticStringMatcher(trunk_path)

class StaticStringMatcher(Matcher):

    branch = "master"

    def matches(self, path):
        return path.startswith(trunk_path)

    def replace(self, path):
        return path.replace(self.trunk_path, '')

class RegexStringMatcher(Matcher):

    def __init__(self, trunk_path):
        super(RegexStringMatcher, self).__init__(trunk_path)
        import re
        self.matcher = re.compile(self.trunk_path[len("regex:"):])

    def matches(self, path):
        match = self.matcher.match(path)
        if match:
            self.branch = match.group(1)
            return True
        else:
            return False

    def replace(self, path):
        return self.matcher.sub("\g<2>", path)

MATCHER = None

def export_revision(rev, repo, fs, pool):
    sys.stderr.write("Exporting revision %s... " % rev)

    revpool = svn_pool_create(pool)
    svn_pool_clear(revpool)

    # Open a root object representing the youngest (HEAD) revision.
    root = svn_fs_revision_root(fs, rev, revpool)

    # And the list of what changed in this revision.
    changes = svn_fs_paths_changed(root, revpool)

    i = 1
    marks = {}
    file_changes = []

    for path, change_type in changes.iteritems():
        c_t = ct_short[change_type.change_kind]
        if svn_fs_is_dir(root, path, revpool):
            continue
        if not MATCHER.matches(path):
            # We don't handle branches. Or tags. Yet.
            pass
        else:
            if c_t == 'D':
                file_changes.append("D %s" % MATCHER.replace(path).lstrip("/"))
            else:
                marks[i] = MATCHER.replace(path)
                file_changes.append("M 644 :%s %s" % (i, marks[i].lstrip("/")))
                sys.stdout.write("blob\nmark :%s\n" % i)
                dump_file_blob(root, path, revpool)
                i += 1

    # Get the commit author and message
    props = svn_fs_revision_proplist(fs, rev, revpool)

    # Do the recursive crawl.
    if props.has_key('svn:author'):
        author = "%s <%s@%s>" % (props['svn:author'], props['svn:author'], address)
    else:
        author = 'nobody <nobody@users.sourceforge.net>'

    if len(file_changes) == 0:
        svn_pool_destroy(revpool)
        sys.stderr.write("skipping.\n")
        return

    svndate = props['svn:date'][0:-8]
    commit_time = mktime(strptime(svndate, '%Y-%m-%dT%H:%M:%S'))
    sys.stdout.write("commit refs/heads/%s\n" % MATCHER.branchname())
    sys.stdout.write("committer %s %s -0000\n" % (author, int(commit_time)))
    sys.stdout.write("data %s\n" % len(props['svn:log']))
    sys.stdout.write(props['svn:log'])
    sys.stdout.write("\n")
    sys.stdout.write('\n'.join(file_changes))
    sys.stdout.write("\n\n")

    svn_pool_destroy(revpool)

    sys.stderr.write("done!\n")

    #if rev % 1000 == 0:
    #    sys.stderr.write("gc: %s objects\n" % len(gc.get_objects()))
    #    sleep(5)


def crawl_revisions(pool, repos_path):
    """Open the repository at REPOS_PATH, and recursively crawl all its
    revisions."""
    global final_rev

    # Open the repository at REPOS_PATH, and get a reference to its
    # versioning filesystem.
    repos_obj = svn_repos_open(repos_path, pool)
    fs_obj = svn_repos_fs(repos_obj)

    # Query the current youngest revision.
    youngest_rev = svn_fs_youngest_rev(fs_obj, pool)


    if final_rev == 0:
        final_rev = youngest_rev
    for rev in xrange(first_rev, final_rev + 1):
        export_revision(rev, repos_obj, fs_obj, pool)


if __name__ == '__main__':
    usage = '%prog [options] REPOS_PATH'
    parser = OptionParser()
    parser.set_usage(usage)
    parser.add_option('-f', '--final-rev', help='Final revision to import', 
                      dest='final_rev', metavar='FINAL_REV', type='int')
    parser.add_option('-r', '--first-rev', help='First revision to import', 
                      dest='first_rev', metavar='FIRST_REV', type='int')
    parser.add_option('-t', '--trunk-path', help="Path in repo to /trunk, may be `regex:/cvs/(trunk)/proj1/(.*)`\nFirst group is used as branchname, second to match files",
                      dest='trunk_path', metavar='TRUNK_PATH')
    parser.add_option('-b', '--branches-path', help='Path in repo to /branches',
                      dest='branches_path', metavar='BRANCHES_PATH')
    parser.add_option('-T', '--tags-path', help='Path in repo to /tags',
                      dest='tags_path', metavar='TAGS_PATH')
    parser.add_option('-a', '--address', help='Domain to put on users for their mail address', 
                      dest='address', metavar='hostname', type='string')
    (options, args) = parser.parse_args()

    if options.trunk_path != None:
        trunk_path = options.trunk_path
    if options.branches_path != None:
        branches_path = options.branches_path
    if options.tags_path != None:
        tags_path = options.tags_path
    if options.final_rev != None:
        final_rev = options.final_rev
    if options.first_rev != None:
        first_rev = options.first_rev
    if options.address != None:
        address = options.address

    MATCHER = Matcher.getMatcher(trunk_path)
    sys.stderr.write("%s\n" % MATCHER)
    if len(args) != 1:
        parser.print_help()
        sys.exit(2)

    # Canonicalize (enough for Subversion, at least) the repository path.
    repos_path = os.path.normpath(args[0])
    if repos_path == '.': 
        repos_path = ''

    try:
        import msvcrt
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    except ImportError:
        pass

    # Call the app-wrapper, which takes care of APR initialization/shutdown
    # and the creation and cleanup of our top-level memory pool.
    run_app(crawl_revisions, repos_path)
