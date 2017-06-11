from __future__ import absolute_import

import os
import sys
import subprocess

from ... import (
    bzrdir,
    revision as mod_revision,
    trace,
    transport,
    workingtree,
    )
from ... import errors as bzr_errors

from . import (
    default_orig_dir,
    errors,
    import_dsc,
    upstream,
    util,
    )


def _get_tree(package_name):
    try:
        tree = workingtree.WorkingTree.open(".")
    except bzr_errors.NotBranchError:
        if os.path.exists(package_name):
            raise bzr_errors.BzrCommandError("Either run the command from an "
                    "existing branch of upstream, or move %s aside "
                    "and a new branch will be created there."
                    % package_name)
        to_transport = transport.get_transport(package_name)
        tree = to_transport.ensure_base()
        try:
            a_bzrdir = bzrdir.BzrDir.open_from_transport(to_transport)
        except bzr_errors.NotBranchError:
            # really a NotBzrDir error...
            create_branch = bzrdir.BzrDir.create_branch_convenience
            branch = create_branch(to_transport.base,
                                   possible_transports=[to_transport])
            a_bzrdir = branch.bzrdir
        else:
            if a_bzrdir.has_branch():
                raise bzr_errors.AlreadyBranchError(package_name)
            branch = a_bzrdir.create_branch()
            a_bzrdir.create_workingtree()
        try:
            tree = a_bzrdir.open_workingtree()
        except bzr_errors.NoWorkingTree:
            tree = a_bzrdir.create_workingtree()
    return tree


def _get_tarballs(tree, tarball, package_name, version):
    from .repack_tarball import repack_tarball
    config = util.debuild_config(tree, tree)
    orig_dir = config.orig_dir or default_orig_dir
    orig_dir = os.path.join(tree.basedir, orig_dir)
    if not os.path.exists(orig_dir):
        os.makedirs(orig_dir)
    format = None
    if tarball.endswith(".tar.bz2") or tarball.endswith(".tbz2"):
        format = "bz2"
    elif tarball.endswith(".tar.xz"):
        format = "xz"
    dest_name = util.tarball_name(package_name, version, None, format=format)
    trace.note("Fetching tarball")
    repack_tarball(tarball, dest_name, target_dir=orig_dir)
    provider = upstream.UpstreamProvider(package_name, version,
            orig_dir, [])
    orig_files = provider.provide(os.path.join(tree.basedir, ".."))
    ret = []
    for filename, component in orig_files:
        ret.append((filename, component, util.md5sum_filename(filename)))
    return ret


def import_upstream(tarball, package_name, version):
    tree = _get_tree(package_name)
    if tree.branch.last_revision() != mod_revision.NULL_REVISION:
        parents = { None: [tree.branch.last_revision()] }
    else:
        parents = {}
    tarball_filenames  = _get_tarballs(tree, tarball,
            package_name, version)
    db = import_dsc.DistributionBranch(tree.branch, tree.branch, tree=tree,
            pristine_upstream_tree=tree)
    dbs = import_dsc.DistributionBranchSet()
    dbs.add_branch(db)
    db.import_upstream_tarballs(tarball_filenames, package_name, version,
        parents)
    return tree


def run_dh_make(tree, package_name, version):
    if not tree.has_filename("debian"):
        tree.mkdir("debian")
    # FIXME: give a nice error on 'debian is not a directory'
    if tree.path2id("debian") is None:
        tree.add("debian")
    command = ["dh_make", "--addmissing", "--packagename",
                "%s_%s" % (package_name, version)]
    if getattr(sys.stdin, 'fileno', None) is None:
        # running in a test or something
        stdin = subprocess.PIPE
        input = "s\n\n"
    else:
        stdin = sys.stdin
        input = None
    try:
        proc = subprocess.Popen(command, cwd=tree.basedir,
                preexec_fn=util.subprocess_setup, stdin=stdin)
    except OSError:
        raise bzr_errors.BzrCommandError("The dh_make command was not found. "
                                         "Please install the dh-make package "
                                         "or use the '--bzr-only' flag and "
                                         "create the debian/ manually.")
    if input is not None:
        proc.stdin.write(input)
        proc.stdin.close()
    retcode = proc.wait()
    if retcode != 0:
        raise bzr_errors.BzrCommandError("dh_make failed.")
    for fn in os.listdir(tree.abspath("debian")):
        if not fn.endswith(".ex") and not fn.endswith(".EX"):
            tree.add(os.path.join("debian", fn))
