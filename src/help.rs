use regex::Regex;
use std::borrow::Cow;
use std::convert::TryFrom;
use std::sync::RwLock;

pub enum HelpContents {
    Text(&'static str),
    Callback(fn(&str) -> String),
    Closure(Box<dyn Fn(&str) -> String + Send + Sync>),
}

macro_rules! help_topic_file {
    ($filename:expr) => {
        HelpContents::Text(include_str!(concat!(
            "../breezy/help_topics/en/",
            $filename,
            ".txt"
        )))
    };
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Section {
    Command,
    Concept,
    Hidden,
    List,
    Plugin,
}

impl TryFrom<&str> for Section {
    type Error = String;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        match value {
            "command" => Ok(Section::Command),
            "concept" => Ok(Section::Concept),
            "hidden" => Ok(Section::Hidden),
            "list" => Ok(Section::List),
            "plugin" => Ok(Section::Plugin),
            _ => Err(format!("Unknown help section: {}", value)),
        }
    }
}

pub struct HelpTopic {
    pub name: &'static str,
    pub contents: HelpContents,
    pub summary: &'static str,
    pub section: Section,
}

pub struct DynamicHelpTopic {
    pub name: String,
    pub contents: HelpContents,
    pub summary: String,
    pub section: Section,
}

impl HelpContents {
    fn get_contents(&self, topic: &str) -> Cow<'_, str> {
        match self {
            HelpContents::Text(text) => Cow::Borrowed(text),
            HelpContents::Callback(ref callback) => callback(topic).into(),
            HelpContents::Closure(ref callback) => callback(topic).into(),
        }
    }
}

impl HelpTopic {
    pub const fn new(
        section: Section,
        name: &'static str,
        summary: &'static str,
        contents: HelpContents,
    ) -> Self {
        Self {
            name,
            contents,
            summary,
            section,
        }
    }
    pub fn get_contents(&self) -> std::borrow::Cow<'_, str> {
        self.contents.get_contents(self.name)
    }

    pub fn get_summary(&self) -> String {
        self.summary.to_string()
    }

    pub fn get_section(&self) -> Section {
        self.section
    }

    pub fn get_name(&self) -> String {
        self.name.to_string()
    }

    /// Return a string with the help for this topic.
    ///
    /// Args:
    ///   additional_see_also: Additional help topics to be
    ///   cross-referenced.
    /// plain: if False, raw help (reStructuredText) is
    ///   returned instead of plain text.
    pub fn get_help_text(&self, additional_see_also: Option<&[&str]>, plain: bool) -> String {
        let mut text = String::new();
        text.push_str(self.get_contents().as_ref());
        if let Some(additional_see_also) = additional_see_also {
            let see_also = format_see_also(additional_see_also);
            text.push_str(see_also.as_str());
        }
        if plain {
            text = help_as_plain_text(text.as_str());
        }
        #[cfg(feature = "i18n")]
        {
            text = crate::i18n::gettext_per_paragraph(text.as_str());
        }
        text
    }
}

pub fn format_see_also(additional_see_also: &[&str]) -> String {
    let mut text = String::new();
    if !additional_see_also.is_empty() {
        let mut additional_see_also = additional_see_also.to_vec();
        additional_see_also.sort();
        text.push_str("\n:See also: ");
        text.push_str(additional_see_also.join(", ").as_str());
        text.push('\n');
    }
    text
}

/// Minimal converter of reStructuredText to plain text.
pub fn help_as_plain_text(text: &str) -> String {
    lazy_static::lazy_static! {
        static ref RE_STANDALONE_BLOCK: Regex = Regex::new(r"(?m)^\s*::\n\s*$").unwrap();
        static ref RE_DOC_REF: Regex = Regex::new(r":doc:`(.+?)-help`").unwrap();
    };
    // Remove the standalone code block marker
    let text = RE_STANDALONE_BLOCK.replace_all(text, "");
    let lines = text.split('\n');
    let mut ret = lines
        .map(|l| {
            let l = if let Some(suffix) = l.strip_prefix(':') {
                suffix.to_string()
            } else if l.ends_with("::") {
                l[..l.len() - 1].to_string()
            } else {
                l.to_string()
            };
            // Map :doc:`xxx-help` to ``brz help xxx``
            RE_DOC_REF
                .replace_all(l.as_str(), r"``brz help \1``")
                .to_string()
        })
        .collect::<Vec<_>>()
        .join("\n");
    if !ret.ends_with('\n') {
        ret.push('\n');
    }
    ret
}

impl DynamicHelpTopic {
    pub fn get_contents(&self) -> std::borrow::Cow<'_, str> {
        self.contents.get_contents(self.name.as_str())
    }

    /// Return a string with the help for this topic.
    ///
    /// Args:
    ///   additional_see_also: Additional help topics to be
    ///   cross-referenced.
    /// plain: if False, raw help (reStructuredText) is
    ///   returned instead of plain text.
    pub fn get_help_text(&self, additional_see_also: Option<&[&str]>, plain: bool) -> String {
        let mut text = String::new();
        text.push_str(self.get_contents().as_ref());
        if let Some(additional_see_also) = additional_see_also {
            let see_also = format_see_also(additional_see_also);
            text.push_str(see_also.as_str());
        }
        if plain {
            text = help_as_plain_text(text.as_str());
        }
        #[cfg(feature = "i18n")]
        {
            text = crate::i18n::gettext_per_paragraph(text.as_str());
        }
        text
    }
}

inventory::collect!(HelpTopic);

const GLOBAL_OPTIONS: &str = r#"Global Options

These options may be used with any command, and may appear in front of any
command.  (e.g. ``brz --profile help``).

--version      Print the version number. Must be supplied before the command.
--no-aliases   Do not process command aliases when running this command.
--builtin      Use the built-in version of a command, not the plugin version.
               This does not suppress other plugin effects.
--no-plugins   Do not process any plugins.
--no-l10n      Do not translate messages.
--concurrency  Number of processes that can be run concurrently (selftest).

--profile      Profile execution using the hotshot profiler.
--lsprof       Profile execution using the lsprof profiler.
--lsprof-file  Profile execution using the lsprof profiler, and write the
               results to a specified file.  If the filename ends with ".txt",
               text format will be used.  If the filename either starts with
               "callgrind.out" or end with ".callgrind", the output will be
               formatted for use with KCacheGrind. Otherwise, the output
               will be a pickle.
--coverage     Generate line coverage report in the specified directory.

-Oname=value   Override the ``name`` config option setting it to ``value`` for
               the duration of the command.  This can be used multiple times if
               several options need to be overridden.

See https://www.breezy-vcs.org/developers/profiling.html for more
information on profiling.

A number of debug flags are also available to assist troubleshooting and
development.  See :doc:`debug-flags-help`.
"#;

inventory::submit! {
    HelpTopic::new(
        Section::List,
        "global-options",
        "Options that control how Breezy runs",
        HelpContents::Text(GLOBAL_OPTIONS))
}

const BASIC_HELP: &str = r#"Breezy {breezy.__version__} -- a free distributed version-control tool
https://www.breezy-vcs.org/

Basic commands:
  brz init           makes this directory a versioned branch
  brz branch         make a copy of another branch

  brz add            make files or directories versioned
  brz ignore         ignore a file or pattern
  brz mv             move or rename a versioned file

  brz status         summarize changes in working copy
  brz diff           show detailed diffs

  brz merge          pull in changes from another branch
  brz commit         save some or all changes
  brz send           send changes via email

  brz log            show history of changes
  brz check          validate storage

  brz help init      more help on e.g. init command
  brz help commands  list all commands
  brz help topics    list all help topics
"#;

inventory::submit! {
    HelpTopic::new(
        Section::List,
        "basic",
        "Basic commands",
        HelpContents::Text(BASIC_HELP))
}

const STORAGE_FORMATS: &str = r#"Storage Formats

To ensure that older clients do not access data incorrectly,
Breezy's policy is to introduce a new storage format whenever
new features requiring new metadata are added. New storage
formats may also be introduced to improve performance and
scalability.

The newest format, 2a, is highly recommended. If your
project is not using 2a, then you should suggest to the
project owner to upgrade.


.. note::

   Some of the older formats have two variants:
   a plain one and a rich-root one. The latter include an additional
   field about the root of the tree. There is no performance cost
   for using a rich-root format but you cannot easily merge changes
   from a rich-root format into a plain format. As a consequence,
   moving a project to a rich-root format takes some co-ordination
   in that all contributors need to upgrade their repositories
   around the same time. 2a and all future formats will be
   implicitly rich-root.

See :doc:`current-formats-help` for the complete list of
currently supported formats. See :doc:`other-formats-help` for
descriptions of any available experimental and deprecated formats.
"#;

inventory::submit! {
    HelpTopic::new(
        Section::Concept,
        "storage-formats",
        "Information on choosing a storage format",
        HelpContents::Text(STORAGE_FORMATS))
}

const WORKING_TREES: &str = r#"Working Trees

A working tree is the contents of a branch placed on disk so that you can
see the files and edit them. The working tree is where you make changes to a
branch, and when you commit the current state of the working tree is the
snapshot that is recorded in the commit.

When you push a branch to a remote system, a working tree will not be
created. If one is already present the files will not be updated. The
branch information will be updated and the working tree will be marked
as out-of-date. Updating a working tree remotely is difficult, as there
may be uncommitted changes or the update may cause content conflicts that are
difficult to deal with remotely.

If you have a branch with no working tree you can use the 'checkout' command
to create a working tree. If you run 'brz checkout .' from the branch it will
create the working tree. If the branch is updated remotely, you can update the
working tree by running 'brz update' in that directory.

If you have a branch with a working tree that you do not want the 'remove-tree'
command will remove the tree if it is safe. This can be done to avoid the
warning about the remote working tree not being updated when pushing to the
branch. It can also be useful when working with a '--no-trees' repository
(see 'brz help repositories').

If you want to have a working tree on a remote machine that you push to you
can either run 'brz update' in the remote branch after each push, or use some
other method to update the tree during the push. There is an 'rspush' plugin
that will update the working tree using rsync as well as doing a push. There
is also a 'push-and-update' plugin that automates running 'brz update' via SSH
after each push.

Useful commands::

  checkout     Create a working tree when a branch does not have one.
  remove-tree  Removes the working tree from a branch when it is safe to do so.
  update       When a working tree is out of sync with its associated branch
               this will update the tree to match the branch.
"#;

inventory::submit! {
    HelpTopic::new(
        Section::Concept,
        "working-trees",
        "Information on working trees",
        HelpContents::Text(WORKING_TREES))
}

const STANDALONE_TREES: &str = r#"Standalone Trees

A standalone tree is a working tree with an associated repository. It
is an independently usable branch, with no dependencies on any other.
Creating a standalone tree (via brz init) is the quickest way to put
an existing project under version control.

Related Commands::

  init    Make a directory into a versioned branch.
"#;

inventory::submit! {
    HelpTopic::new(
        Section::Concept,
        "standalone-trees",
        "Information on what a standalone tree is",
        HelpContents::Text(STANDALONE_TREES))
}

const CRISS_CROSS: &str = r#"Criss-Cross

A criss-cross in the branch history can cause the default merge technique
to emit more conflicts than would normally be expected.

In complex merge cases, ``brz merge --lca`` or ``brz merge --weave`` may give
better results.  You may wish to ``brz revert`` the working tree and merge
again.  Alternatively, use ``brz remerge`` on particular conflicted files.

Criss-crosses occur in a branch's history if two branches merge the same thing
and then merge one another, or if two branches merge one another at the same
time.  They can be avoided by having each branch only merge from or into a
designated central branch (a "star topology").

Criss-crosses cause problems because of the way merge works.  Breezy's default
merge is a three-way merger; in order to merge OTHER into THIS, it must
find a basis for comparison, BASE.  Using BASE, it can determine whether
differences between THIS and OTHER are due to one side adding lines, or
from another side removing lines.

Criss-crosses mean there is no good choice for a base.  Selecting the recent
merge points could cause one side's changes to be silently discarded.
Selecting older merge points (which Breezy does) mean that extra conflicts
are emitted.

The ``weave`` merge type is not affected by this problem because it uses
line-origin detection instead of a basis revision to determine the cause of
differences.
"#;

inventory::submit! {
    HelpTopic::new(
        Section::Concept,
        "criss-cross",
        "Information on criss-cross merging",
        HelpContents::Text(CRISS_CROSS))
}

const BRANCHES_OUT_OF_SYNC: &str = r#"Branches Out of Sync

When reconfiguring a checkout, tree or branch into a lightweight checkout,
a local branch must be destroyed.  (For checkouts, this is the local branch
that serves primarily as a cache.)  If the branch-to-be-destroyed does not
have the same last revision as the new reference branch for the lightweight
checkout, data could be lost, so Breezy refuses.

How you deal with this depends on *why* the branches are out of sync.

If you have a checkout and have done local commits, you can get back in sync
by running "brz update" (and possibly "brz commit").

If you have a branch and the remote branch is out-of-date, you can push
the local changes using "brz push".  If the local branch is out of date, you
can do "brz pull".  If both branches have had changes, you can merge, commit
and then push your changes.  If you decide that some of the changes aren't
useful, you can "push --overwrite" or "pull --overwrite" instead.
"#;

inventory::submit! {
    HelpTopic::new(
        Section::Concept,
        "branches-out-of-sync",
        "Steps to resolve \"out-of-sync\" when reconfiguring",
        HelpContents::Text(BRANCHES_OUT_OF_SYNC))
}

const FILES: &str = r#"Files

:On Unix:   ~/.config/breezy/breezy.conf
:On Windows: %APPDATA%\\breezy\\breezy.conf

Contains the user's default configuration. The section ``[DEFAULT]`` is
used to define general configuration that will be applied everywhere.
The section ``[ALIASES]`` can be used to create command aliases for
commonly used options.

A typical config file might look something like::

  [DEFAULT]
  email=John Doe <jdoe@isp.com>

  [ALIASES]
  commit = commit --strict
  log10 = log --short -r -10..-1
"#;

inventory::submit! {
    HelpTopic::new(
        Section::Concept,
        "files",
        "Information on the configuration and log files",
        HelpContents::Text(FILES))
}

const STATUS_FLAGS: &str = r#"Status Flags

Status flags are used to summarise changes to the working tree in a concise
manner.  They are in the form::

   xxx   <filename>

where the columns' meanings are as follows.

Column 1 - versioning/renames::

  + File versioned
  - File unversioned
  R File renamed
  ? File unknown
  X File nonexistent (and unknown to brz)
  C File has conflicts
  P Entry for a pending merge (not a file)

Column 2 - contents::

  N File created
  D File deleted
  K File kind changed
  M File modified

Column 3 - execute::

  * The execute bit was changed
"#;

inventory::submit! {
    HelpTopic::new(
        Section::List,
        "status-flags",
        "Help on status flags",
        HelpContents::Text(STATUS_FLAGS))
}

const CHECKOUTS: &str = r#"Checkouts

Checkouts are source trees that are connected to a branch, so that when
you commit in the source tree, the commit goes into that branch.  They
allow you to use a simpler, more centralized workflow, ignoring some of
Breezy's decentralized features until you want them. Using checkouts
with shared repositories is very similar to working with SVN or CVS, but
doesn't have the same restrictions.  And using checkouts still allows
others working on the project to use whatever workflow they like.

A checkout is created with the brz checkout command (see "help checkout").
You pass it a reference to another branch, and it will create a local copy
for you that still contains a reference to the branch you created the
checkout from (the master branch). Then if you make any commits they will be
made on the other branch first. This creates an instant mirror of your work, or
facilitates lockstep development, where each developer is working together,
continuously integrating the changes of others.

However the checkout is still a first class branch in Breezy terms, so that
you have the full history locally.  As you have a first class branch you can
also commit locally if you want, for instance due to the temporary loss af a
network connection. Use the --local option to commit to do this. All the local
commits will then be made on the master branch the next time you do a non-local
commit.

If you are using a checkout from a shared branch you will periodically want to
pull in all the changes made by others. This is done using the "update"
command. The changes need to be applied before any non-local commit, but
Breezy will tell you if there are any changes and suggest that you use this
command when needed.

It is also possible to create a "lightweight" checkout by passing the
--lightweight flag to checkout. A lightweight checkout is even closer to an
SVN checkout in that it is not a first class branch, it mainly consists of the
working tree. This means that any history operations must query the master
branch, which could be slow if a network connection is involved. Also, as you
don't have a local branch, then you cannot commit locally.

Lightweight checkouts work best when you have fast reliable access to the
master branch. This means that if the master branch is on the same disk or LAN
a lightweight checkout will be faster than a heavyweight one for any commands
that modify the revision history (as only one copy of the branch needs to
be updated). Heavyweight checkouts will generally be faster for any command
that uses the history but does not change it, but if the master branch is on
the same disk then there won't be a noticeable difference.

Another possible use for a checkout is to use it with a treeless repository
containing your branches, where you maintain only one working tree by
switching the master branch that the checkout points to when you want to
work on a different branch.

Obviously to commit on a checkout you need to be able to write to the master
branch. This means that the master branch must be accessible over a writeable
protocol , such as sftp://, and that you have write permissions at the other
end. Checkouts also work on the local file system, so that all that matters is
file permissions.

You can change the master of a checkout by using the "switch" command (see
"help switch").  This will change the location that the commits are sent to.
The "bind" command can also be used to turn a normal branch into a heavy
checkout. If you would like to convert your heavy checkout into a normal
branch so that every commit is local, you can use the "unbind" command. To see
whether or not a branch is bound or not you can use the "info" command. If the
branch is bound it will tell you the location of the bound branch.

Related commands::

  checkout    Create a checkout. Pass --lightweight to get a lightweight
              checkout
  update      Pull any changes in the master branch in to your checkout
  commit      Make a commit that is sent to the master branch. If you have
              a heavy checkout then the --local option will commit to the
              checkout without sending the commit to the master
  switch      Change the master branch that the commits in the checkout will
              be sent to
  bind        Turn a standalone branch into a heavy checkout so that any
              commits will be sent to the master branch
  unbind      Turn a heavy checkout into a standalone branch so that any
              commits are only made locally
  info        Displays whether a branch is bound or unbound. If the branch is
              bound, then it will also display the location of the bound branch
"#;

inventory::submit! {
    HelpTopic::new(
        Section::Concept,
        "checkouts",
        "Information on what a checkout is",
        HelpContents::Text(CHECKOUTS))
}

const BRANCHES: &str = r#"Branches

A branch consists of the state of a project, including all of its
history. All branches have a repository associated (which is where the
branch history is stored), but multiple branches may share the same
repository (a shared repository). Branches can be copied and merged.

In addition, one branch may be bound to another one.  Binding to another
branch indicates that commits which happen in this branch must also
happen in the other branch.  Breezy ensures consistency by not allowing
commits when the two branches are out of date.  In order for a commit
to succeed, it may be necessary to update the current branch using
``brz update``.

Related commands::

  init    Change a directory into a versioned branch.
  branch  Create a new branch that is a copy of an existing branch.
  merge   Perform a three-way merge.
  bind    Bind a branch to another one.
"#;

inventory::submit! {
    HelpTopic::new(
        Section::Concept,
        "branches",
        "Information on what a branch is",
        HelpContents::Text(BRANCHES))
}

const REPOSITORIES: &str = r#"Repositories

Repositories in Breezy are where committed information is stored. There is
a repository associated with every branch.

Repositories are a form of database. Breezy will usually maintain this for
good performance automatically, but in some situations (e.g. when doing
very many commits in a short time period) you may want to ask brz to
optimise the database indices. This can be done by the 'brz pack' command.

By default just running 'brz init' will create a repository within the new
branch but it is possible to create a shared repository which allows multiple
branches to share their information in the same location. When a new branch is
created it will first look to see if there is a containing shared repository it
can use.

When two branches of the same project share a repository, there is
generally a large space saving. For some operations (e.g. branching
within the repository) this translates in to a large time saving.

To create a shared repository use the init-shared-repository command (or the
alias init-shared-repo). This command takes the location of the repository to
create. This means that 'brz init-shared-repository repo' will create a
directory named 'repo', which contains a shared repository. Any new branches
that are created in this directory will then use it for storage.

It is a good idea to create a repository whenever you might create more
than one branch of a project. This is true for both working areas where you
are doing the development, and any server areas that you use for hosting
projects. In the latter case, it is common to want branches without working
trees. Since the files in the branch will not be edited directly there is no
need to use up disk space for a working tree. To create a repository in which
the branches will not have working trees pass the '--no-trees' option to
'init-shared-repository'.

Related commands::

  init-shared-repository   Create a shared repository. Use --no-trees to create
                           one in which new branches won't get a working tree.
"#;

inventory::submit! {
    HelpTopic::new(
        Section::Concept,
        "repositories",
        "Information on what a repository is",
        HelpContents::Text(REPOSITORIES))
}

const STANDARD_OPTIONS: &str = r#"Standard Options

Standard options are legal for all commands.

--help, -h     Show help message.
--verbose, -v  Display more information.
--quiet, -q    Only display errors and warnings.

Unlike global options, standard options can be used in aliases.
"#;

inventory::submit! {
    HelpTopic::new(
        Section::List,
        "standard-options",
        "Options that can be used with any command",
        HelpContents::Text(STANDARD_OPTIONS))
}

inventory::submit! {
    HelpTopic::new(
        Section::List,
        "authentication",
        "Information on configuring authentication",
        help_topic_file!("authentication")
    )
}

inventory::submit! {
    HelpTopic::new(
        Section::List,
        "configuration",
        "Details on the configuration settings available",
        help_topic_file!("configuration")
    )
}

inventory::submit! {
    HelpTopic::new(
        Section::List,
        "conflict-types",
        "Types of conflicts and what to do about them",
        help_topic_file!("conflict-types")
    )
}

inventory::submit! {
    HelpTopic::new(
        Section::List,
        "debug-flags",
        "Options to show or record debug information",
        help_topic_file!("debug-flags")
    )
}

inventory::submit! {
    HelpTopic::new(
        Section::List,
        "glossary",
        "Glossary",
        help_topic_file!("glossary")
    )
}

inventory::submit! {
    HelpTopic::new(
        Section::List,
        "log-formats",
        "Details on the logging formats available",
        help_topic_file!("log-formats")
    )
}

inventory::submit! {
    HelpTopic::new(
        Section::List,
        "missing-extensions",
        "What to do when compiled extensions are missing",
        help_topic_file!("missing-extensions")
    )
}

inventory::submit! {
    HelpTopic::new(
        Section::List,
        "url-special-chars",
        "Special character handling in URLs",
        help_topic_file!("url-special-chars")
    )
}

inventory::submit! {
    HelpTopic::new(
        Section::Concept,
        "content-filters",
        "Conversion of content into/from working trees",
        help_topic_file!("content-filters")
    )
}

inventory::submit! {
    HelpTopic::new(
        Section::Concept,
        "diverged-branches",
        "How to fix diverged branches",
        help_topic_file!("diverged-branches")
    )
}

inventory::submit! {
    HelpTopic::new(
        Section::Concept,
        "eol",
        "Information on end-of-line handling",
        help_topic_file!("eol")
    )
}

inventory::submit! {
    HelpTopic::new(
        Section::Concept,
        "patterns",
        "Information on the pattern syntax",
        help_topic_file!("patterns")
    )
}

inventory::submit! {
    HelpTopic::new(
        Section::Concept,
        "rules",
        "Information on defining rule-based preferences",
        help_topic_file!("rules")
    )
}

pub const KNOWN_ENV_VARIABLES: &[(&str, &str)] = &[
    (
        "BRZPATH",
        "Path where brz is to look for shell plugin external commands.",
    ),
    ("BRZ_EMAIL", "E-Mail address of the user. Overrides EMAIL."),
    ("EMAIL", "E-Mail address of the user."),
    (
        "BRZ_EDITOR",
        "Editor for editing commit messages. Overrides EDITOR.",
    ),
    ("EDITOR", "Editor for editing commit messages."),
    (
        "BRZ_PLUGIN_PATH",
        "Paths where brz should look for plugins.",
    ),
    ("BRZ_DISABLE_PLUGINS", "Plugins that brz should not load."),
    (
        "BRZ_PLUGINS_AT",
        "Plugins to load from a directory not in BRZ_PLUGIN_PATH.",
    ),
    (
        "BRZ_HOME",
        "Directory holding breezy config dir. Overrides HOME.",
    ),
    (
        "BRZ_HOME (Win32)",
        "Directory holding breezy config dir. Overrides APPDATA and HOME.",
    ),
    (
        "BZR_REMOTE_PATH",
        "Full name of remote 'brz' command (for brz+ssh:// URLs).",
    ),
    (
        "BRZ_SSH",
        "Path to SSH client, or one of paramiko, openssh, sshcorp, plink or lsh.",
    ),
    (
        "BRZ_LOG",
        "Location of brz.log (use '/dev/null' to suppress log).",
    ),
    (
        "BRZ_LOG (Win32)",
        "Location of brz.log (use 'NUL' to suppress log).",
    ),
    ("BRZ_COLUMNS", "Override implicit terminal width."),
    (
        "BRZ_CONCURRENCY",
        "Number of processes that can be run concurrently (selftest)",
    ),
    (
        "BRZ_PROGRESS_BAR",
        "Override the progress display. Values are 'none' or 'text'.",
    ),
    ("BRZ_PDB", "Control whether to launch a debugger on error."),
    (
        "BRZ_SIGQUIT_PDB",
        "Control whether SIGQUIT behaves normally or invokes a breakin debugger.",
    ),
    (
        "BRZ_TEXTUI_INPUT",
        "Force console input mode for prompts to line-based (instead of char-based).",
    ),
];

fn env_variables(_topic: &str) -> String {
    let mut ret = vec![
        "Environment Variables\n\n".to_string(),
        "See brz help configuration for more details.\n\n".to_string(),
    ];
    let max_key_len = KNOWN_ENV_VARIABLES.iter().map(|e| e.0.len()).max().unwrap();

    let desc_len = 80 - max_key_len - 2;

    let mut textwrap_options = textwrap::Options::new(desc_len);
    textwrap_options.initial_indent = "";
    let subsequent_indent = " ".repeat(max_key_len + 1);
    textwrap_options.subsequent_indent = subsequent_indent.as_str();

    ret.push(format!(
        "{} {}\n",
        "=".repeat(max_key_len),
        "=".repeat(desc_len)
    ));
    for (k, desc) in KNOWN_ENV_VARIABLES.iter() {
        ret.push(format!("{}{}", k, " ".repeat(max_key_len + 1 - k.len())));
        ret.push(textwrap::wrap(desc, &textwrap_options).join("\n"));
        ret.push("\n".to_string());
    }
    ret.push(format!(
        "{} {}\n",
        "=".repeat(max_key_len),
        "=".repeat(desc_len)
    ));
    ret.concat()
}

inventory::submit! {
    HelpTopic::new(
        Section::List,
        "env-variables",
        "Environment variable names and values",
        HelpContents::Callback(env_variables)
        )
}

pub fn get_static_topic(name: &str) -> Option<&'static HelpTopic> {
    iter_static_topics().find(|t| t.name == name)
}

pub fn get_dynamic_topic(name: &str) -> Option<std::sync::Arc<DynamicHelpTopic>> {
    let lock = DYNAMIC_TOPICS.read().unwrap();
    if let Some(topic) = lock.get(name) {
        return Some(std::sync::Arc::clone(topic));
    }
    None
}

pub fn register_topic(topic: DynamicHelpTopic) {
    let mut lock = DYNAMIC_TOPICS.write().unwrap();
    lock.insert(topic.name.to_string(), std::sync::Arc::new(topic));
}

pub fn iter_static_topics() -> impl Iterator<Item = &'static HelpTopic> {
    inventory::iter::<HelpTopic>()
}

pub fn iter_dynamic_topics() -> impl Iterator<Item = std::sync::Arc<DynamicHelpTopic>> {
    let lock = DYNAMIC_TOPICS.read().unwrap();
    lock.iter()
        .map(|(_, topic)| std::sync::Arc::clone(topic))
        .collect::<Vec<_>>()
        .into_iter()
}

static DYNAMIC_TOPICS: once_cell::sync::Lazy<
    RwLock<std::collections::HashMap<String, std::sync::Arc<DynamicHelpTopic>>>,
> = once_cell::sync::Lazy::new(|| RwLock::new(std::collections::HashMap::new()));
