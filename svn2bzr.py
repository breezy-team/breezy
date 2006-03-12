#!/usr/bin/env python2.4
#
# Copyright (C) 2005 by Canonical Ltd
#
# Written by Gustavo Niemeyer <gustavo@niemeyer.net>
# Bugfixes and additional features by Jelmer Vernooij <jelmer@samba.org>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#
import optparse
import logging
import sys, os
import shutil
import time
import re
import bz2

logger = logging.getLogger("bzr")
logger.addHandler(logging.FileHandler("/dev/null"))

from bzrlib.branch import Branch
import bzrlib.trace
from dumpfile import Dump

VERSION = "0.6"

# Bogus difflib
sys.setrecursionlimit(10000)

def get_logger():
    if hasattr(get_logger, "initialized"):
        logger = logging.getLogger("svn2bzr")
    else:
        get_logger.initialized = True
        class Formatter(logging.Formatter):
            def format(self, record):
                if record.levelno != logging.INFO:
                    record.prefix = record.levelname.lower()+": "
                else:
                    record.prefix = ""
                return logging.Formatter.format(self, record)
        formatter = Formatter("%(prefix)s%(message)s")
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(formatter)
        #logger = logging.getLogger("bzr")
        #logger.addHandler(handler)
        #logger.setLevel(logging.ERROR)
        logger = logging.getLogger("svn2bzr")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


class Error(Exception): pass

class BranchCreator(object):

    def __init__(self, dump, root=None, prefix=None, log=None):
        self._dump = dump
        self._root = os.path.realpath(root)
        if prefix:
            self._prefix = prefix.strip("/")
            self._prefix_dir = self._prefix+"/"
        else:
            self._prefix = None
            self._prefix_dir = None
        self._revisions = {}
        self._branches = {}
        self._changed = {}
        self._filter = []
        self._log = log or get_logger()

        self._do_cache = {}

    def _do(self, branch, action, path):
        last = self._do_cache.get(branch)
        if last and action == last[0]:
            last[1].append(path)
        else:
            if last:
                self._do_now(branch, *last)
            self._do_cache[branch] = (action, [path])

    def _do_now(self, branch, action, paths):
        if action == "add":
            branch.__wt.add(paths)
        elif action == "remove":
            branch.__wt.remove(paths)
        else:
            raise RuntimeError, "Unknown action: %r" % action

    def _process_do_cache(self, branch):
        last = self._do_cache.get(branch)
        if last:
            self._do_now(branch, *last)
            del self._do_cache[branch]

    def _new_branch(self, branch):
        # Ugly, but let's wait until that API stabilizes. Right
        # now branch.working_tree() will open the branch again.
        self._log.debug("Creating new branch: %s" % branch.base)
        branch.__wt = branch.working_tree()

    def _remove_branch(self, branch):
        raise NotImplementedError
            
    def _get_branch(self, path):
        raise NotImplementedError

    def _get_all_branches(self):
        raise NotImplementedError

    def _get_branch_path(self, path):
        path = self.unprefix(path)
        if self.is_good(path):
            branch = self._get_branch(path)
            if branch:
                abspath = os.path.join(self._root, path)
                return branch, branch.__wt.relpath(abspath)
        return None, None

    def add_filter(self, include, regexp):
        self._filter.append((include, re.compile(regexp)))

    def is_good(self, path):
        for include, pattern in self._filter:
            if pattern.match(path):
                return include
        return True

    def unprefix(self, path):
        if not self._prefix:
            return path
        elif path == self._prefix:
            return ""
        elif path.startswith(self._prefix):
            return path[len(self._prefix)+1:]
        else:
            return None


    def add_file(self, path, content):
        branch, path_branch = self._get_branch_path(path)
        if branch:
            abspath = branch.__wt.abspath(path_branch)
            self._log.debug("Adding file: %s" % abspath)
            open(abspath, "w").write(content)
            self._do(branch, "add", path_branch)
            self._changed[branch] = True

    def change_file(self, path, content):
        branch, path_branch = self._get_branch_path(path)
        if branch:
            abspath = branch.__wt.abspath(path_branch)
            self._log.debug("Changing file: %s" % abspath)
            open(abspath, "w").write(content)
            self._changed[branch] = True

    def copy_file(self, orig_path, orig_revno, dest_path):
        dest_branch, dest_path_branch = self._get_branch_path(dest_path)
        if dest_branch:
            orig_entry = self._dump.get_entry(orig_revno, orig_path)
            orig_content = self._dump.get_entry_content(orig_entry)
            abspath = dest_branch.__wt.abspath(dest_path_branch)
            self._log.debug("Copying file: %s at %d to %s" %
                            (orig_path, orig_revno, abspath))
            open(abspath, "w").write(orig_content)
            self._do(dest_branch, "add", dest_path_branch)
            self._changed[dest_branch] = True

    def add_dir(self, path):
        branch, path_branch = self._get_branch_path(path)
        # The path test below checks if we got an empty path,
        # which happens when adding the self._prefix directory itself,
        # and shouldn't be considered since creating that directory
        # must have been done by _get_branch().
        if branch and path_branch:
            # Due to filtering, the directory may be added
            # without adding parent directories.
            abspath = branch.__wt.abspath(path_branch)
            self._log.debug("Adding dir: %s" % abspath)
            if os.path.isdir(os.path.dirname(abspath)):
                os.mkdir(abspath)
                self._do(branch, "add", path_branch)
            else:
                path_parts = path_branch.split('/')
                dir = branch.base
                for part in path_parts:
                    dir = "%s/%s" % (dir, part)
                    if not os.path.isdir(dir):
                        os.mkdir(dir)
                        self._do(branch, "add",
                                 branch.__wt.relpath(dir))
            self._changed[branch] = True

    def copy_dir(self, orig_path, orig_revno, dest_path):
        # Inside that method we cannot assume that dest_branch
        # is a valid branch, since we may be interested just in
        # part of the copy being made, for which a branch does
        # exist.
        #
        # To better understand what each path means, let's assume that
        # a copy of "trunk/foo" is being made to "branches/mine/foo",
        # "trunk" and "branches/mine" are different branches", and that
        # "trunk/foo/bar" exists and is being copied during the current
        # iteration.
        #
        # orig_path = "trunk/foo"
        # dest_path = "branches/mine/foo"
        # dest_path_branch = "foo"
        # path = "trunk/foo/bar"
        # tail = "bar"
        # copy_dest_path = "branches/mine/foo/bar"
        #
        # Got it? :-)
        #
        dest_branch, dest_path_branch = self._get_branch_path(dest_path)
        entries = self._dump.get_dir_tree(orig_revno, orig_path).items()
        entries.sort()
        changed = False
        for path, entry in entries:
            tail = path[len(orig_path)+1:]
            copy_dest_path = os.path.join(dest_path, tail)
            node_kind = entry["node-kind"]
            if node_kind == "file":
                content = self._dump.get_entry_content(entry)
                self.add_file(copy_dest_path, content)
            elif node_kind == "dir":
                self.add_dir(copy_dest_path)

    def set_ignore_glob(self, path, globs):
        from bzrlib.atomicfile import AtomicFile
        branch, path_branch = self._get_branch_path(path)

        if branch is None:
            self._log.debug("Ignoring out-of-branch ignore settings on %s" % path)
            return

        # Obtain list of existing ignores
        ifn = branch.working_tree().abspath('.bzrignore')

        if os.path.exists(ifn):
            f = open(ifn, 'rt')
            igns = f.read().decode('utf-8').split("\n")
            f.close()
            os.unlink(ifn)
        else:
            igns = []

        # Figure out which elements are already there
        for ign in igns:
            dir = os.path.dirname(ign)
 
            if dir != path_branch:
                continue

            if not ign in globs:
                igns.remove(ign)
            else:
                globs.remove(ign)

        # The remaining items didn't exist yet
        for ign in globs:
            igns.append(ign)
            
        f = AtomicFile(ifn, 'wt')
        data = "\n".join(igns)
        f.write(data.encode('utf-8'))
        f.commit()

        if not branch.working_tree().path2id('.bzrignore'):
            branch.working_tree().add(['.bzrignore'])

        self._changed[branch] = True

    def set_executable(self, path, executable):
        branch, path_branch = self._get_branch_path(path)
        if branch is None:
            self._log.debug("Ignoring out-of-branch executable settings on %s" % path)
            return

        abspath = branch.working_tree().abspath(path_branch)
        mode = os.stat(abspath).st_mode
        if executable:
            mode = mode | 0111
        else:
            mode = mode &~ 0111
        os.chmod(abspath, mode)
        self._changed[branch] = True

    def copy(self, orig_path, orig_revno, dest_path):
        orig_entry = self._dump.get_entry(orig_revno, orig_path)
        if orig_entry["node-kind"] == "dir":
            self.copy_dir(orig_path, orig_revno, dest_path)
        else:
            self.copy_file(orig_path, orig_revno, dest_path)

    def move(self, orig_path, orig_revno, dest_path):
        orig_branch, orig_path_branch = self._get_branch_path(orig_path)
        dest_branch, dest_path_branch = self._get_branch_path(dest_path)
        if not dest_branch or orig_branch != dest_branch:
            self.remove(orig_path)
            self.copy(orig_path, orig_revno, dest_path)
        else:
            self._process_do_cache(orig_branch)
            orig_abspath = orig_branch.__wt.abspath(orig_path_branch)
            if not os.path.exists(orig_abspath):
                # Was previously removed, as usual in svn.
                orig_branch.__wt.revert([orig_abspath])
                # Revert is currently broken. It invalidates the inventory.
                orig_branch.__wt = orig_branch.working_tree()
            self._log.debug("Moving: %s to %s" %
                            (orig_abspath,
                             dest_branch.__wt.abspath(dest_path_branch)))
            orig_branch.__wt.rename_one(orig_path_branch, dest_path_branch)
            self._changed[orig_branch] = True

    def remove(self, path):
        branch, path_branch = self._get_branch_path(path)
        if branch:
            abspath = branch.__wt.abspath(path_branch)
            if not path_branch:
                # Do we want to remove the branch or its content?
                self._log.debug("Removing branch: %s" % abspath)
                self._remove_branch(branch)
            elif os.path.exists(abspath):
                self._do(branch, "remove", path_branch)
                if os.path.isdir(abspath):
                    self._log.debug("Removing dir: %s" % abspath)
                    shutil.rmtree(abspath)
                    # If the directory parent is filtered, no one is
                    # taking care of it, so remove it as well.
                    abspath = os.path.dirname(abspath)
                    while abspath != branch.base:
                        relpath = abspath[len(branch.base)+1:]
                        if self.is_good(relpath):
                            break
                        try:
                            os.rmdir(abspath)
                            self._do(branch, "remove", relpath)
                        except OSError:
                            break
                elif os.path.isfile(abspath):
                    self._log.debug("Removing file: %s" % abspath)
                    os.unlink(abspath)
                self._changed[branch] = True

    def commit(self, revno, message, committer, timestamp):
        if self._changed:
            self._log.info("Committing revision %d" % revno)
            for branch in self._changed:
                self._process_do_cache(branch)
                branch.__wt.commit(message, committer=committer,
                                   timestamp=timestamp, verbose=False)
        else:
            self._log.info("Nothing changed in revision %d" % revno)
        self._revisions[revno] = revs = {}
        for (path,branch) in self._branches.items():
            revs[path] = (branch, branch.last_revision())
        self._changed.clear()

    def run(self):

        revision = None
        revno = None

        def commit():
            # Parse timestamps like 2005-09-23T17:52:33.719737Z
            time_tokens = revision.prop["svn:date"].split(".")
            parsed_time = time.strptime(time_tokens[0],
                                        "%Y-%m-%dT%H:%M:%S")
            timestamp = time.mktime(parsed_time)
            timestamp += float(time_tokens[1][:-1])

            self.commit(revno, revision.prop.get("svn:log", ""),
                        committer=revision.prop.get("svn:author"),
                        timestamp=timestamp)

        deleted = {}

        for entry in self._dump:
            
            if "revision-number" in entry:

                if revision is not None:
                    commit()

                revision = entry
                revno = revision["revision-number"]

                deleted.clear()

            elif "node-path" in entry:

                node_path = entry["node-path"]

                if self.unprefix(node_path) is None:
                    continue

                node_action = entry["node-action"]
                node_kind = entry.get("node-kind")
                
                assert node_kind in (None, "file", "dir")
                assert node_action in ("add", "delete", "change", "replace")

                if node_action == "delete":
                    self.remove(node_path)
                    deleted[node_path] = True

                elif node_action == "add" or node_action == "replace":

                    if node_action == "replace":
                        self.remove(node_path)

                    if "node-copyfrom-path" in entry:
                        copy_path = entry["node-copyfrom-path"]
                        copy_revno = entry["node-copyfrom-rev"]

                        if copy_path in deleted and copy_revno == revno-1:
                            self.move(copy_path, copy_revno, node_path)
                        elif node_kind == "file":
                            self.copy_file(copy_path, copy_revno, node_path)
                        else:
                            self.copy_dir(copy_path, copy_revno, node_path)

                    elif node_kind == "file":
                        content = self._dump.get_entry_content(entry)
                        self.add_file(node_path, content)

                    elif node_kind == "dir":
                        self.add_dir(node_path)

                elif node_action == "change":

                    if (node_kind == "file" and
                        entry.content_pos != entry.change_from.content_pos):
                        content = self._dump.get_entry_content(entry)
                        self.change_file(node_path, content)

                if os.path.isfile(node_path):
                    if entry.prop.has_key('svn:executable') and \
                        entry.prop['svn:executable'] == '*':
                        self.set_executable(node_path, True)
                    else:
                        self.set_executable(node_path, False)

                if entry.prop.has_key('svn:ignore'):
                    self.set_ignore_glob(node_path, \
                            entry.prop['svn:ignore'].split("\n"))

        if revision is not None:
            commit()


class SingleBranchCreator(BranchCreator):

    def __init__(self, dump, root, prefix=None, log=None):
        BranchCreator.__init__(self, dump, root, prefix, log)
        self._branch = None

    def _remove_branch(self, branch):
        self._branch = None
        shutil.rmtree(self._root)

    def _get_branch(self, path):
        if not self._branch:
            self._branch = Branch.initialize(self._root)
            self._new_branch(self._branch)
        return self._branch

    def _get_all_branches(self):
        if self._branch is None:
            return []
        else:
            return [self._branch]


class DynamicBranchCreator(BranchCreator):
    ATTICDIR = "attic"

    def __init__(self, dump, root, prefix=None, log=None):
        BranchCreator.__init__(self, dump, root, prefix, log)

    def _remove_branch(self, branch):
        # Retire a branch to the attic
        rel_path = branch.base[len(self._root)+1:].rstrip("/")
        attic_branch = "%s-r%d" % (os.path.basename(rel_path), self._revisions.keys()[-1])
        branch_top = os.path.join(self._root, DynamicBranchCreator.ATTICDIR, os.path.dirname(rel_path))
        self._log.debug("Retiring %s to %s" % (rel_path, attic_branch))
        if not os.path.isdir(branch_top):
            os.makedirs(branch_top)
        attic_path = os.path.join(branch_top, attic_branch)
        shutil.move(branch.base, attic_path)
        new_branch = Branch.open(attic_path)
        self._new_branch(new_branch)

        # Set correct path for old revisions that used this branch
        for revno in self._revisions:
            if not self._revisions[revno].has_key(rel_path):
                continue

            (b,r) = self._revisions[revno][rel_path] 
            if b == branch:
                self._revisions[revno][rel_path] = (new_branch,r)
        
        del self._branches[rel_path]

    def _want_branch(self, path):
        raise NotImplemented

    def _get_branch(self, path):
        for (bp,branch) in self._branches.items():
            if path == bp or path.startswith(bp+"/"):
                return branch

    def _get_all_branches(self):
        return self._branches.values()

    def add_dir(self, path):
        branch, path_branch = self._get_branch_path(path)
        unpref_path = self.unprefix(path)
        if not branch:
            if self.is_good(unpref_path) and self._want_branch(unpref_path):
                branch_path = os.path.join(self._root, unpref_path)
                os.makedirs(branch_path)
                branch = Branch.initialize(branch_path)
                self._branches[unpref_path] = branch
                self._new_branch(branch)
        else:
            BranchCreator.add_dir(self, path)
 
    def copy_dir(self, orig_path, orig_revno, dest_path):
        # unpref_dest_path can't be None because it was
        # already filtered in run()
        unpref_orig_path = self.unprefix(orig_path)
        unpref_dest_path = self.unprefix(dest_path)
        orig_abspath = os.path.join(self._root, unpref_orig_path)
        if (unpref_orig_path is None or
            not self._revisions[orig_revno].has_key(unpref_orig_path) or
            self._get_branch(unpref_dest_path)):

            # Normal copy
            BranchCreator.copy_dir(self, orig_path, orig_revno,
                                          dest_path)

        elif self.is_good(unpref_dest_path):

            # Create new branch
            dest_abspath = os.path.join(self._root, unpref_dest_path)
            (orig_branch,revid) = self._revisions[orig_revno][unpref_orig_path]
            os.makedirs(dest_abspath)
            branch = orig_branch.clone(to_location=dest_abspath, revision=revid)
            self._branches[unpref_dest_path] = branch
            self._new_branch(branch)

    def remove(self, path):
        unpref_path = self.unprefix(path)
        if not self._get_branch(unpref_path):
            abspath = os.path.join(self._root, unpref_path)
            if os.path.isdir(abspath):
                shutil.rmtree(abspath)
                for branch_path in self._branches.keys():
                    if branch_path.startswith(path+"/"):
                        del self._branches[branch_path]
        else:
            BranchCreator.remove(self, path)
        

class TrunkBranchCreator(DynamicBranchCreator):

    def _want_branch(self, path):
        return path not in ("", "tags", "branches")


def svn2bzr(dump_file, output_dir, creator_class=None, prefix=None, filter=[]):

    if os.path.exists(output_dir):
        raise Error, "%s already exists" % output_dir

    if creator_class is None:
        creator_class = SingleBranchCreator

    dump = Dump(dump_file,log=get_logger(),cache_interval=10)

    creator = creator_class(dump, output_dir, prefix)

    for include, regexp in filter:
        creator.add_filter(include, regexp)

    creator.run()


def append_filter(option, opt, value, parser):
    lst = getattr(parser.values, option.dest)
    if type(lst) is not list:
        lst = []
        setattr(parser.values, option.dest, lst)
    lst.append((opt == "--include", value))


def parse_options():
    parser = optparse.OptionParser("svn2bzr.py [options] "
                                   "<dump file> <output dir>",
                                   version="%prog "+VERSION)
    parser.defaults["filter"] = []
    parser.add_option("--include", dest="filter", metavar="REGEXP",
                      type="string", action="callback", callback=append_filter,
                      help="paths matching the regular expression are "
                           "considered if no prior exclude matched")
    parser.add_option("--exclude", dest="filter", metavar="REGEXP",
                      type="string", action="callback", callback=append_filter,
                      help="paths matching the regular expression are "
                           "discarded if no prior include matched")
    parser.add_option("--prefix", metavar="PATH", type="string",
                      help="Subversion repository will be considered as if "
                           "it started at the given path")
    parser.add_option("--scheme", metavar="SCHEME", type="string",
                      help="Subversion repository scheme (single or trunk, "
                           "default is single)",
                      default="single")
    parser.add_option("--log", metavar="LEVEL",
                      help="set logging level to LEVEL (debug, info, "
                           "warning, error)", default="info")
    opts, args = parser.parse_args()
    if len(args) != 2:
        parser.print_help()
        sys.exit(1)
    opts.args = args
    return opts


def main():

    bzrlib.user_encoding = 'utf8'

    opts = parse_options()

    if opts.scheme == "trunk":
        creator_class = TrunkBranchCreator
    else:
        creator_class = SingleBranchCreator

    log = get_logger()
    log.setLevel(logging.getLevelName(opts.log.upper()))

    dump_filename = opts.args[0]
    if dump_filename.endswith(".gz"):
        import gzip
        dump_file = gzip.GzipFile(dump_filename)
    elif dump_filename.endswith(".bz2"):
        dump_file = bz2.BZ2File(dump_filename)
    else:
        dump_file = open(dump_filename)

    try:
        svn2bzr(dump_file, opts.args[1], creator_class,
                opts.prefix, opts.filter)
    except Error, e:
        sys.exit("error: %s" % e)
    except KeyboardInterrupt:
        sys.exit("Interrupted")

if __name__ == "__main__":
    main()

