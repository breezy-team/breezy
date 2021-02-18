from __future__ import absolute_import

import os
import sys
import subprocess

from ... import (
    controldir,
    errors as bzr_errors,
    revision as mod_revision,
    trace,
    transport,
    workingtree,
    )

from . import (
    default_orig_dir,
    import_dsc,
    upstream,
    util,
    )


def _get_tree(package_name):
    try:
        tree = workingtree.WorkingTree.open(".")
    except bzr_errors.NotBranchError:
        if os.path.exists(package_name):
            raise bzr_errors.BzrCommandError(
                "Either run the command from an "
                "existing branch of upstream, or move %s aside "
                "and a new branch will be created there."
                % package_name)
        to_transport = transport.get_transport(package_name)
        tree = to_transport.ensure_base()
        try:
            a_controldir = controldir.ControlDir.open_from_transport(
                to_transport)
        except bzr_errors.NotBranchError:
            # really a NotBranchError...
            create_branch = controldir.ControlDir.create_branch_convenience
            branch = create_branch(to_transport.base,
                                   possible_transports=[to_transport])
            a_controldir = branch.controldir
        else:
            if a_controldir.has_branch():
                raise bzr_errors.AlreadyBranchError(package_name)
            branch = a_controldir.create_branch()
            a_controldir.create_workingtree()
        try:
            tree = a_controldir.open_workingtree()
        except bzr_errors.NoWorkingTree:
            tree = a_controldir.create_workingtree()
    return tree


def _get_tarballs(tree, subpath, tarball, package_name, version):
    from .repack_tarball import repack_tarball
    config = util.debuild_config(tree, subpath)
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
    provider = upstream.UpstreamProvider(
        package_name, version, orig_dir, [])
    orig_files = provider.provide(os.path.join(tree.basedir, ".."))
    ret = []
    for filename, component in orig_files:
        ret.append((filename, component, util.md5sum_filename(filename)))
    return ret


def import_upstream(tarball, package_name, version, use_pristine_tar=True):
    tree = _get_tree(package_name)
    if tree.branch.last_revision() != mod_revision.NULL_REVISION:
        parents = {None: [tree.branch.last_revision()]}
    else:
        parents = {}
    tarball_filenames = _get_tarballs(
        tree, '', tarball, package_name, version)
    db = import_dsc.DistributionBranch(
        tree.branch, tree.branch, tree=tree, pristine_upstream_tree=tree)
    dbs = import_dsc.DistributionBranchSet()
    dbs.add_branch(db)
    db.import_upstream_tarballs(
        tarball_filenames, package_name, version, parents,
        force_pristine_tar=use_pristine_tar)
    return tree
