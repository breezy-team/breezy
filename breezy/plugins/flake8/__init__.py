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

"""Flake8 type checking before commits.

Set the ``flake8.pre_commit_check`` configuration variable to True
to enable this.
"""

from breezy.errors import BzrError, DependencyNotPresent


class Flake8Errors(BzrError):
    _fmt = (
        "Running in strict flake8 mode; aborting commit, "
        "since %(errors)d flake8 errors exist."
    )

    def __init__(self, errors):
        self.errors = errors


def _delta_files(tree_delta):
    for path, _file_id, kind in tree_delta.added:
        if kind == "file":
            yield path
    for (
        path,
        _file_id,
        kind,
        text_modified,
        _meta_modified,
    ) in tree_delta.modified:
        if kind == "file" and text_modified:
            yield path
    for (
        _oldpath,
        newpath,
        _id,
        kind,
        text_modified,
        _meta_modified,
    ) in tree_delta.renamed:
        if kind == "file" and text_modified:
            yield newpath
    for path, _id, _old_kind, new_kind in tree_delta.kind_changed:
        if new_kind == "file":
            yield path


def _copy_files_to(tree, target_dir, files):
    from breezy import osutils

    for relpath in files:
        target_path = os.path.join(target_dir, relpath)
        os.makedirs(os.path.dirname(target_path))
        with tree.get_file(relpath) as inf, open(target_path, "wb") as outf:
            osutils.pumpfile(inf, outf)
            yield target_path


def _update_paths(checker_manager, temp_prefix):
    temp_prefix_length = len(temp_prefix)
    for checker in checker_manager.checkers:
        filename = checker.display_name
        if filename.startswith(temp_prefix):
            checker.display_name = os.path.relpath(filename[temp_prefix_length:])


def hook(config, tree_delta, future_tree):
    """Execute Flake8 on the files in git's index.

    Determine which files are about to be committed and run Flake8 over
    them to check for violations.

    :param bool strict:
        If True, return the total number of errors/violations found by
        Flake8. This will cause the hook to fail.
    :returns:
        Total number of errors found during the run.
    :rtype:
        int
    """
    try:
        from flake8.main import application
    except ModuleNotFoundError as e:
        raise DependencyNotPresent("flake8", e)
    import tempfile

    strict = config.get("flake8.strict")

    app = application.Application()
    with tempfile.TemporaryDirectory() as tempdir:
        filepaths = list(_copy_files_to(future_tree, tempdir, _delta_files(tree_delta)))
        app.initialize([tempdir])
        app.options._running_from_vcs = True
        app.run_checks(filepaths)
        _update_paths(app.file_checker_manager, tempdir)
        app.report_errors()

    if strict:
        if app.result_count:
            raise Flake8Errors(app.result_count)


def _check_flake8(
    local,
    master,
    old_revno,
    old_revid,
    future_revno,
    future_revid,
    tree_delta,
    future_tree,
):
    branch = local or master
    config = branch.get_config_stack()
    if config.get("flake8.pre_commit_check"):
        hook(config, tree_delta, future_tree)


from breezy.branch import Branch

Branch.hooks.install_named_hook("pre_commit", _check_flake8, "Check flake8")  # type: ignore
