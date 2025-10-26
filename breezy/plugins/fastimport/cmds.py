# Copyright (C) 2008 Canonical Ltd
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Fastimport/fastexport commands."""

from ... import controldir
from ...commands import Command
from ...option import Option, RegistryOption
from . import helpers, load_fastimport


def _run(source, processor_factory, verbose=False, user_map=None, **kwargs):
    """Create and run a processor.

    :param source: a filename or '-' for standard input. If the
      filename ends in .gz, it will be opened as a gzip file and
      the stream will be implicitly uncompressed
    :param processor_factory: a callable for creating a processor
    :param user_map: if not None, the file containing the user map.
    """
    from fastimport import parser
    from fastimport.errors import ParsingError

    from ...errors import CommandError

    stream = _get_source_stream(source)
    user_mapper = _get_user_mapper(user_map)
    proc = processor_factory(verbose=verbose, **kwargs)
    p = parser.ImportParser(stream, verbose=verbose, user_mapper=user_mapper)
    try:
        return proc.process(p.iter_commands)
    except ParsingError as e:
        raise CommandError(f"{e.lineno}: Parse error: {e}") from e


def _get_source_stream(source):
    if source == "-" or source is None:
        import sys

        try:
            stream = sys.stdin.buffer
        except AttributeError:
            stream = helpers.binary_stream(sys.stdin)
    elif source.endswith(".gz"):
        import gzip

        stream = gzip.open(source, "rb")
    else:
        stream = open(source, "rb")
    return stream


def _get_user_mapper(filename):
    from . import user_mapper

    if filename is None:
        return None
    f = open(filename)
    lines = f.readlines()
    f.close()
    return user_mapper.UserMapper(lines)


class cmd_fast_import(Command):
    """Backend for fast Bazaar data importers.

    This command reads a mixed command/data stream and creates
    branches in a Bazaar repository accordingly. The preferred
    recipe is::

      bzr fast-import project.fi project.bzr

    Numerous commands are provided for generating a fast-import file
    to use as input.
    To specify standard input as the input stream, use a
    source name of '-' (instead of project.fi). If the source name
    ends in '.gz', it is assumed to be compressed in gzip format.

    project.bzr will be created if it doesn't exist. If it exists
    already, it should be empty or be an existing Bazaar repository
    or branch. If not specified, the current directory is assumed.

    fast-import will intelligently select the format to use when
    creating a repository or branch. If you are running Bazaar 1.17
    up to Bazaar 2.0, the default format for Bazaar 2.x ("2a") is used.
    Otherwise, the current default format ("pack-0.92" for Bazaar 1.x)
    is used. If you wish to specify a custom format, use the `--format`
    option.

     .. note::

        To maintain backwards compatibility, fast-import lets you
        create the target repository or standalone branch yourself.
        It is recommended though that you let fast-import create
        these for you instead.

    :Branch mapping rules:

     Git reference names are mapped to Bazaar branch names as follows:

     * refs/heads/foo is mapped to foo
     * refs/remotes/origin/foo is mapped to foo.remote
     * refs/tags/foo is mapped to foo.tag
     * */master is mapped to trunk, trunk.remote, etc.
     * */trunk is mapped to git-trunk, git-trunk.remote, etc.

    :Branch creation rules:

     When a shared repository is created or found at the destination,
     branches are created inside it. In the simple case of a single
     branch (refs/heads/master) inside the input file, the branch is
     project.bzr/trunk.

     When a standalone branch is found at the destination, the trunk
     is imported there and warnings are output about any other branches
     found in the input file.

     When a branch in a shared repository is found at the destination,
     that branch is made the trunk and other branches, if any, are
     created in sister directories.

    :Working tree updates:

     The working tree is generated for the trunk branch. If multiple
     branches are created, a message is output on completion explaining
     how to create the working trees for other branches.

    :Custom exporters:

     The fast-export-from-xxx commands typically call more advanced
     xxx-fast-export scripts. You are welcome to use the advanced
     scripts if you prefer.

     If you wish to write a custom exporter for your project, see
     http://bazaar-vcs.org/BzrFastImport for the detailed protocol
     specification. In many cases, exporters can be written quite
     quickly using whatever scripting/programming language you like.

    :User mapping:

     Some source repositories store just the user name while Bazaar
     prefers a full email address. You can adjust user-ids while
     importing by using the --user-map option. The argument is a
     text file with lines in the format::

       old-id = new-id

     Blank lines and lines beginning with # are ignored.
     If old-id has the special value '@', then users without an
     email address will get one created by using the matching new-id
     as the domain, unless a more explicit address is given for them.
     For example, given the user-map of::

       @ = example.com
       bill = William Jones <bill@example.com>

     then user-ids are mapped as follows::

      maria => maria <maria@example.com>
      bill => William Jones <bill@example.com>

     .. note::

        User mapping is supported by both the fast-import and
        fast-import-filter commands.

    :Blob tracking:

     As some exporters (like git-fast-export) reuse blob data across
     commits, fast-import makes two passes over the input file by
     default. In the first pass, it collects data about what blobs are
     used when, along with some other statistics (e.g. total number of
     commits). In the second pass, it generates the repository and
     branches.

     .. note::

        The initial pass isn't done if the --info option is used
        to explicitly pass in information about the input stream.
        It also isn't done if the source is standard input. In the
        latter case, memory consumption may be higher than otherwise
        because some blobs may be kept in memory longer than necessary.

    :Restarting an import:

     At checkpoints and on completion, the commit-id -> revision-id
     map is saved to a file called 'fastimport-id-map' in the control
     directory for the repository (e.g. .bzr/repository). If the import
     is interrupted or unexpectedly crashes, it can be started again
     and this file will be used to skip over already loaded revisions.
     As long as subsequent exports from the original source begin
     with exactly the same revisions, you can use this feature to
     maintain a mirror of a repository managed by a foreign tool.
     If and when Bazaar is used to manage the repository, this file
     can be safely deleted.

    :Examples:

     Import a Subversion repository into Bazaar::

       svn-fast-export /svn/repo/path > project.fi
       bzr fast-import project.fi project.bzr

     Import a CVS repository into Bazaar::

       cvs2git /cvs/repo/path > project.fi
       bzr fast-import project.fi project.bzr

     Import a Git repository into Bazaar::

       cd /git/repo/path
       git fast-export --all > project.fi
       bzr fast-import project.fi project.bzr

     Import a Mercurial repository into Bazaar::

       cd /hg/repo/path
       hg fast-export > project.fi
       bzr fast-import project.fi project.bzr

     Import a Darcs repository into Bazaar::

       cd /darcs/repo/path
       darcs-fast-export > project.fi
       bzr fast-import project.fi project.bzr
    """

    hidden = False
    _see_also = ["fast-export", "fast-import-filter", "fast-import-info"]
    takes_args = ["source", "destination?"]
    takes_options = [
        "verbose",
        Option(
            "user-map",
            type=str,
            help="Path to file containing a map of user-ids.",
        ),
        Option(
            "info",
            type=str,
            help="Path to file containing caching hints.",
        ),
        Option(
            "trees",
            help="Update all working trees, not just trunk's.",
        ),
        Option(
            "count",
            type=int,
            help="Import this many revisions then exit.",
        ),
        Option(
            "checkpoint",
            type=int,
            help="Checkpoint automatically every N revisions. The default is 10000.",
        ),
        Option(
            "autopack",
            type=int,
            help="Pack every N checkpoints. The default is 4.",
        ),
        Option(
            "inv-cache",
            type=int,
            help="Number of inventories to cache.",
        ),
        RegistryOption.from_kwargs(
            "mode",
            "The import algorithm to use.",
            title="Import Algorithm",
            default="Use the preferred algorithm (inventory deltas).",
            experimental="Enable experimental features.",
            value_switches=True,
            enum_switch=False,
        ),
        Option("import-marks", type=str, help="Import marks from file."),
        Option("export-marks", type=str, help="Export marks to file."),
        RegistryOption(
            "format",
            help="Specify a format for the created repository. See"
            ' "bzr help formats" for details.',
            lazy_registry=("breezy.controldir", "format_registry"),
            converter=lambda name: controldir.format_registry.make_controldir(name),
            value_switches=False,
            title="Repository format",
        ),
    ]

    def run(
        self,
        source,
        destination=".",
        verbose=False,
        info=None,
        trees=False,
        count=-1,
        checkpoint=10000,
        autopack=4,
        inv_cache=-1,
        mode=None,
        import_marks=None,
        export_marks=None,
        format=None,
        user_map=None,
    ):
        load_fastimport()
        from .helpers import open_destination_directory
        from .processors import generic_processor

        control = open_destination_directory(destination, format=format)

        # If an information file was given and the source isn't stdin,
        # generate the information by reading the source file as a first pass
        if info is None and source != "-":
            info = self._generate_info(source)

        # Do the work
        if mode is None:
            mode = "default"
        params = {
            b"info": info,
            b"trees": trees,
            b"count": count,
            b"checkpoint": checkpoint,
            b"autopack": autopack,
            b"inv-cache": inv_cache,
            b"mode": mode,
            b"import-marks": import_marks,
            b"export-marks": export_marks,
        }
        return _run(
            source,
            generic_processor.GenericProcessor,
            bzrdir=control,
            params=params,
            verbose=verbose,
            user_map=user_map,
        )

    def _generate_info(self, source):
        from io import StringIO

        from fastimport import parser
        from fastimport.errors import ParsingError
        from fastimport.processors import info_processor

        from ...errors import CommandError

        stream = _get_source_stream(source)
        output = StringIO()
        try:
            proc = info_processor.InfoProcessor(verbose=True, outf=output)
            p = parser.ImportParser(stream)
            try:
                proc.process(p.iter_commands)
            except ParsingError as e:
                raise CommandError(f"{e.lineno}: Parse error: {e}") from e
            lines = output.getvalue().splitlines()
        finally:
            output.close()
            stream.seek(0)
        return lines


class cmd_fast_export(Command):
    """Generate a fast-import stream from a Bazaar branch.

    This program generates a stream from a Bazaar branch in fast-import
    format used by tools such as bzr fast-import, git-fast-import and
    hg-fast-import.

    It takes two optional arguments: the source bzr branch to export and
    the destination to write the file to write the fastimport stream to.

    If no source is specified, it will search for a branch in the
    current directory.

    If no destination is given or the destination is '-', standard output
    is used. Otherwise, the destination is the name of a file. If the
    destination ends in '.gz', the output will be compressed into gzip
    format.

    :Round-tripping:

     Recent versions of the fast-import specification support features
     that allow effective round-tripping most of the metadata in Bazaar
     branches. As such, fast-exporting a branch and fast-importing the data
     produced will create a new repository with roughly equivalent history, i.e.
     "bzr log -v -p --include-merges --forward" on the old branch and
     new branch should produce similar, if not identical, results.

     .. note::

        Be aware that the new repository may appear to have similar history
        but internally it is quite different with new revision-ids and
        file-ids assigned. As a consequence, the ability to easily merge
        with branches based on the old repository is lost. Depending on your
        reasons for producing a new repository, this may or may not be an
        issue.

    :Interoperability:

     fast-export can use the following "extended features" to
     produce a richer data stream:

     * *multiple-authors* - if a commit has multiple authors (as commonly
       occurs in pair-programming), all authors will be included in the
       output, not just the first author

     * *commit-properties* - custom metadata per commit that Bazaar stores
       in revision properties (e.g. branch-nick and bugs fixed by this
       change) will be included in the output.

     * *empty-directories* - directories, even the empty ones, will be
       included in the output.

     To disable these features and produce output acceptable to git 1.6,
     use the --plain option. To enable these features, use --no-plain.
     Currently, --plain is the default but that will change in the near
     future once the feature names and definitions are formally agreed
     to by the broader fast-import developer community.

     Git has stricter naming rules for tags and fast-export --plain
     will skip tags which can't be imported into git. To replace characters
     unsupported in git with an underscore instead, specify
     --rewrite-tag-names.

    :History truncation:

     It is sometimes convenient to simply truncate the revision history at a
     certain point.  The --baseline option, to be used in conjunction with -r,
     emits a baseline commit containing the state of the entire source tree at
     the first requested revision.  This allows a user to produce a tree
     identical to the original without munging multiple exports.

    :Examples:

     To produce data destined for import into Bazaar::

       bzr fast-export --no-plain my-bzr-branch my.fi.gz

     To produce data destined for Git 1.6::

       bzr fast-export --plain my-bzr-branch my.fi

     To import several unmerged but related branches into the same repository,
     use the --{export,import}-marks options, and specify a name for the git
     branch like this::

       bzr fast-export --export-marks=marks.bzr project.dev |
              GIT_DIR=project/.git git-fast-import --export-marks=marks.git

       bzr fast-export --import-marks=marks.bzr -b other project.other |
              GIT_DIR=project/.git git-fast-import --import-marks=marks.git

     If you get a "Missing space after source" error from git-fast-import,
     see the top of the commands.py module for a work-around.

     Since bzr uses per-branch tags and git/hg use per-repo tags, the
     way bzr fast-export presently emits tags (unconditional reset &
     new ref) may result in clashes when several different branches
     are imported into single git/hg repo.  If this occurs, use the
     bzr fast-export option --no-tags during the export of one or more
     branches to avoid the issue.
    """

    hidden = False
    _see_also = ["fast-import", "fast-import-filter"]
    takes_args = ["source?", "destination?"]
    takes_options = [
        "verbose",
        "revision",
        Option(
            "git-branch",
            short_name="b",
            type=str,
            argname="FILE",
            help="Name of the git branch to create (default=master).",
        ),
        Option(
            "checkpoint",
            type=int,
            argname="N",
            help="Checkpoint every N revisions (default=10000).",
        ),
        Option(
            "marks",
            type=str,
            argname="FILE",
            help="Import marks from and export marks to file.",
        ),
        Option(
            "import-marks", type=str, argname="FILE", help="Import marks from file."
        ),
        Option("export-marks", type=str, argname="FILE", help="Export marks to file."),
        Option("plain", help="Exclude metadata to maximise interoperability."),
        Option(
            "rewrite-tag-names",
            help="Replace characters invalid in git with '_' (plain mode only).",
        ),
        Option(
            "baseline",
            help="Export an 'absolute' baseline commit prior to"
            "the first relative commit",
        ),
        Option("no-tags", help="Don't export tags"),
    ]
    encoding_type = "exact"

    def run(
        self,
        source=None,
        destination=None,
        verbose=False,
        git_branch="master",
        checkpoint=10000,
        marks=None,
        import_marks=None,
        export_marks=None,
        revision=None,
        plain=True,
        rewrite_tag_names=False,
        no_tags=False,
        baseline=False,
    ):
        load_fastimport()
        from ...branch import Branch
        from . import exporter

        if marks:
            import_marks = export_marks = marks

        # Open the source
        if source is None:
            source = "."
        branch = Branch.open_containing(source)[0]
        outf = exporter._get_output_stream(destination)
        exporter = exporter.BzrFastExporter(
            branch,
            outf=outf,
            ref=b"refs/heads/%s" % git_branch.encode("utf-8"),
            checkpoint=checkpoint,
            import_marks_file=import_marks,
            export_marks_file=export_marks,
            revision=revision,
            verbose=verbose,
            plain_format=plain,
            rewrite_tags=rewrite_tag_names,
            no_tags=no_tags,
            baseline=baseline,
        )
        return exporter.run()
