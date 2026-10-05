//! Command infrastructure.
//!
//! A native command implements the [`Command`] trait: [`Command::spec`]
//! describes it as a [`CommandSpec`] and [`Command::run`] runs it against a
//! [`CommandContext`]. This module also holds the [`CommandError`] type, the
//! matching of positional arguments against a spec, the assembly of a
//! command's help text and the hook-driven command lookup ([`CommandSource`]).

/// Error raised while looking up or running a command.
///
/// At the Python boundary this maps to `breezy.errors.CommandError`. The variant
/// corresponds to the ``internal_error`` attribute that ``trace.report_exception``
/// keys on: a [`CommandError::User`] is a `BzrError` with ``internal_error = False``
/// (reported as ``brz: ERROR: msg``, exit 3); a [`CommandError::Internal`] is an
/// unexpected failure / bug (reported as a bug, exit 4).
#[derive(Debug)]
pub enum CommandError {
    /// A user-facing error message, already translated.
    User(String),
    /// An internal error (a bug, or an unexpected failure).
    ///
    /// `kind` is the exception type name to report it as (e.g.
    /// ``AssertionError``); `None` reports it as a ``RuntimeError``.
    Internal {
        /// The exception type name, if a specific one should be reported.
        kind: Option<String>,
        /// The error message.
        message: String,
    },
    /// A broken output pipe, reported as ``brz: broken pipe``.
    BrokenPipe,
    /// A Python exception raised while answering a Python-backed command.
    ///
    /// The exception is carried rather than rendered, so it reaches Python with
    /// its type and traceback intact. Only the PyO3 command impls produce this;
    /// the pure crate just passes it along.
    #[cfg(feature = "pyo3")]
    Python(pyo3::PyErr),
}

#[cfg(feature = "pyo3")]
impl From<pyo3::PyErr> for CommandError {
    fn from(err: pyo3::PyErr) -> Self {
        CommandError::Python(err)
    }
}

#[cfg(feature = "pyo3")]
impl From<CommandError> for pyo3::PyErr {
    /// Surface a command error as a Python exception: a carried exception is
    /// re-raised unchanged, anything else becomes a ``CommandError``.
    fn from(err: CommandError) -> Self {
        match err {
            CommandError::Python(e) => e,
            CommandError::User(message) => pyo3::Python::attach(|py| {
                use pyo3::types::PyAnyMethods;
                match py
                    .import("breezy.errors")
                    .and_then(|m| m.as_any().getattr("CommandError"))
                    .and_then(|c| c.call1((message,)))
                {
                    Ok(e) => pyo3::PyErr::from_value(e),
                    Err(e) => e,
                }
            }),
            // An internal error is raised as the named builtin exception type so
            // that trace.report_exception reports it as a bug.
            CommandError::Internal { kind, message } => pyo3::Python::attach(|py| {
                use pyo3::types::PyAnyMethods;
                let kind = kind.unwrap_or_else(|| "RuntimeError".to_string());
                match py
                    .import("builtins")
                    .and_then(|m| m.as_any().getattr(kind.as_str()))
                    .and_then(|c| c.call1((message,)))
                {
                    Ok(e) => pyo3::PyErr::from_value(e),
                    Err(e) => e,
                }
            }),
            // trace.report_exception recognises a broken pipe by its errno.
            CommandError::BrokenPipe => pyo3::Python::attach(|py| {
                use pyo3::types::PyAnyMethods;
                match py.import("errno").and_then(|m| m.as_any().getattr("EPIPE")) {
                    Ok(epipe) => pyo3::exceptions::PyBrokenPipeError::new_err((
                        epipe.unbind(),
                        "Broken pipe",
                    )),
                    Err(e) => e,
                }
            }),
        }
    }
}

impl CommandError {
    /// A user error with the given (already translated) message.
    pub fn user(message: impl Into<String>) -> Self {
        CommandError::User(message.into())
    }

    /// An internal error reported as the named exception type (e.g.
    /// ``AssertionError``), so the bug report reads ``{kind}: {message}``.
    pub fn internal_as(kind: impl Into<String>, message: impl Into<String>) -> Self {
        CommandError::Internal {
            kind: Some(kind.into()),
            message: message.into(),
        }
    }
}

impl std::fmt::Display for CommandError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            CommandError::User(msg) | CommandError::Internal { message: msg, .. } => {
                f.write_str(msg)
            }
            CommandError::BrokenPipe => f.write_str("broken pipe"),
            #[cfg(feature = "pyo3")]
            CommandError::Python(e) => write!(f, "{e}"),
        }
    }
}

impl std::error::Error for CommandError {}

impl From<std::io::Error> for CommandError {
    /// An I/O failure while running a command surfaces as a user error (exit 3),
    /// matching the ``EnvironmentError`` branch of ``trace.report_exception``; a
    /// broken pipe gets its dedicated message.
    fn from(err: std::io::Error) -> Self {
        if err.kind() == std::io::ErrorKind::BrokenPipe {
            CommandError::BrokenPipe
        } else {
            CommandError::User(err.to_string())
        }
    }
}

/// Convert a squished class name (``cmd_foo_bar``) to a command name (``foo-bar``).
pub fn unsquish_command_name(name: &str) -> String {
    name.strip_prefix("cmd_").unwrap_or(name).replace('_', "-")
}

/// Convert a command name (``foo-bar``) to a squished class name (``cmd_foo_bar``).
pub fn squish_command_name(name: &str) -> String {
    format!("cmd_{}", name.replace('-', "_"))
}

/// A value bound to a positional argument by [`match_argform`].
///
/// Plain and optional (`?`) arguments produce a [`ArgValue::Scalar`]; the
/// list-valued specifiers (`*`, `+`, `$`) produce a [`ArgValue::List`], which is
/// `None` for the empty-`*` case.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ArgValue {
    /// A single argument value.
    Scalar(String),
    /// A list of argument values, or `None` for an empty `*` match.
    List(Option<Vec<String>>),
}

/// An error produced while matching positional arguments against the
/// argument-form specification.
///
/// The variants carry the data needed to format the user-facing message; the
/// Python binding layer renders them through `breezy.i18n.gettext`, so the
/// existing translations of the messages still apply.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ArgMatchError {
    /// A `+` or `$` argument that did not receive enough values.
    /// Carries the command name and the upper-cased argument name.
    NeedsOneOrMore {
        /// The command name.
        cmd: String,
        /// The upper-cased argument name.
        argname: String,
    },
    /// A required plain argument that was not supplied.
    /// Carries the command name and the upper-cased argument name.
    RequiresArgument {
        /// The command name.
        cmd: String,
        /// The upper-cased argument name.
        argname: String,
    },
    /// More arguments were supplied than the command accepts.
    /// Carries the command name and the first extra argument.
    ExtraArgument {
        /// The command name.
        cmd: String,
        /// The first unconsumed argument.
        extra: String,
    },
}

/// The positional arguments matched against a command's ``takes_args``.
///
/// Keyed by the parameter name [`match_argform`] produces (e.g. ``filename``
/// for a plain argument, ``file_list`` for a ``file*`` one).
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct MatchedArgs {
    args: std::collections::HashMap<String, ArgValue>,
}

impl MatchedArgs {
    /// The value of a single (plain or ``?``) argument `name`, if given.
    pub fn scalar(&self, name: &str) -> Option<&str> {
        match self.args.get(name) {
            Some(ArgValue::Scalar(s)) => Some(s),
            _ => None,
        }
    }

    /// The values of a list (``*``, ``+`` or ``$``) argument, by its
    /// ``name_list`` parameter; empty when nothing matched.
    pub fn list(&self, list_param: &str) -> Vec<String> {
        match self.args.get(list_param) {
            Some(ArgValue::List(Some(v))) => v.clone(),
            _ => Vec::new(),
        }
    }

    /// Record the value matched for parameter `name`.
    pub fn set(&mut self, name: String, value: ArgValue) {
        self.args.insert(name, value);
    }
}

/// The parameter name [`match_argform`] binds a `takes_args` entry to:
/// ``name`` for ``name`` and ``name?``, ``name_list`` for the list forms.
pub fn argform_param(spec: &str) -> String {
    match spec.chars().last() {
        Some('?') => spec[..spec.len() - 1].to_string(),
        Some('*' | '+' | '$') => format!("{}_list", &spec[..spec.len() - 1]),
        _ => spec.to_string(),
    }
}

/// Match the supplied positional `args` against the `takes_args` specification.
///
/// Returns the bound arguments as an ordered list of (parameter-name, value)
/// pairs, preserving the declaration order of `takes_args`. The trailing
/// character of each entry in `takes_args` selects the matching behaviour:
///
/// * ``name?`` -- optional single argument (omitted entirely if absent)
/// * ``name*`` -- zero or more, bound to ``name_list`` (`None` if empty)
/// * ``name+`` -- one or more, bound to ``name_list``
/// * ``name$`` -- all but the last, bound to ``name_list``
/// * ``name``  -- a required single argument
pub fn match_argform(
    cmd: &str,
    takes_args: &[String],
    mut args: Vec<String>,
) -> Result<Vec<(String, ArgValue)>, ArgMatchError> {
    let mut argdict: Vec<(String, ArgValue)> = Vec::new();

    for ap in takes_args {
        let last = ap.chars().last();
        // Everything but the trailing specifier character. For a plain
        // argument (handled in the default branch) this prefix is unused.
        let argname = match last {
            Some(c) => &ap[..ap.len() - c.len_utf8()],
            None => ap.as_str(),
        };
        match last {
            Some('?') => {
                if !args.is_empty() {
                    argdict.push((argname.to_string(), ArgValue::Scalar(args.remove(0))));
                }
            }
            Some('*') => {
                if !args.is_empty() {
                    argdict.push((
                        format!("{argname}_list"),
                        ArgValue::List(Some(std::mem::take(&mut args))),
                    ));
                } else {
                    argdict.push((format!("{argname}_list"), ArgValue::List(None)));
                }
            }
            Some('+') => {
                if args.is_empty() {
                    return Err(ArgMatchError::NeedsOneOrMore {
                        cmd: cmd.to_string(),
                        argname: argname.to_uppercase(),
                    });
                }
                argdict.push((
                    format!("{argname}_list"),
                    ArgValue::List(Some(std::mem::take(&mut args))),
                ));
            }
            Some('$') => {
                if args.len() < 2 {
                    return Err(ArgMatchError::NeedsOneOrMore {
                        cmd: cmd.to_string(),
                        argname: argname.to_uppercase(),
                    });
                }
                // Capture all but the last argument, leaving the last one in
                // ``args`` for a later spec (or the trailing extra-argument
                // check) to handle.
                let last_arg = args.pop().unwrap();
                let rest = std::mem::replace(&mut args, vec![last_arg]);
                argdict.push((format!("{argname}_list"), ArgValue::List(Some(rest))));
            }
            _ => {
                // A plain arg: the whole spec is the name.
                let argname = ap.as_str();
                if args.is_empty() {
                    return Err(ArgMatchError::RequiresArgument {
                        cmd: cmd.to_string(),
                        argname: argname.to_uppercase(),
                    });
                }
                argdict.push((argname.to_string(), ArgValue::Scalar(args.remove(0))));
            }
        }
    }

    if !args.is_empty() {
        return Err(ArgMatchError::ExtraArgument {
            cmd: cmd.to_string(),
            extra: args.remove(0),
        });
    }

    Ok(argdict)
}

/// Build the single-line argument grammar for a command's usage string.
///
/// Only the positional arguments are described (not options): ``$``/``+``
/// become ``NAME...``, ``?`` becomes ``[NAME]`` and ``*`` becomes ``[NAME...]``.
pub fn usage(name: &str, takes_args: &[String]) -> String {
    let mut s = format!("brz {name} ");
    for aname in takes_args {
        let aname = aname.to_uppercase();
        let rendered = match aname.chars().last() {
            Some('$') | Some('+') => format!("{}...", &aname[..aname.len() - 1]),
            Some('?') => format!("[{}]", &aname[..aname.len() - 1]),
            Some('*') => format!("[{}...]", &aname[..aname.len() - 1]),
            _ => aname,
        };
        s.push_str(&rendered);
        s.push(' ');
    }
    // Remove the trailing space.
    s.pop();
    s
}

/// Split command help text into a summary line and named sections.
///
/// The first line is the summary. A line of the form ``:xxx:`` starts a named
/// section ``xxx``; the default section (text outside any named section) is
/// keyed with `None`. Returns the summary plus the sections as an ordered list
/// of (label, body) pairs, in first-appearance order, with repeated labels
/// merged (their bodies joined with a newline).
pub fn split_help_parts(text: &str) -> (String, Vec<(Option<String>, String)>) {
    // An ordered map: keep insertion order, merge repeated labels.
    let mut order: Vec<Option<String>> = Vec::new();
    let mut sections: std::collections::HashMap<Option<String>, String> =
        std::collections::HashMap::new();

    let save_section = |order: &mut Vec<Option<String>>,
                        sections: &mut std::collections::HashMap<Option<String>, String>,
                        label: &Option<String>,
                        section: &str| {
        if !section.is_empty() {
            if let Some(existing) = sections.get_mut(label) {
                existing.push('\n');
                existing.push_str(section);
            } else {
                order.push(label.clone());
                sections.insert(label.clone(), section.to_string());
            }
        }
    };

    let trimmed = text.trim_end();
    let mut lines = trimmed.lines();
    let summary = lines.next().unwrap_or("").to_string();

    let mut label: Option<String> = None;
    let mut section = String::new();

    for line in lines {
        // Count characters rather than bytes, so a line holding a single
        // multi-byte character is not taken for a heading.
        let char_count = line.chars().count();
        if line.starts_with(':') && line.ends_with(':') && char_count > 2 {
            save_section(&mut order, &mut sections, &label, &section);
            // Strip the leading and trailing ``:`` (single ASCII bytes).
            label = Some(line[1..line.len() - 1].to_string());
            section = String::new();
        } else if label.is_some()
            && char_count > 1
            && !line.chars().next().is_some_and(|c| c.is_whitespace())
        {
            save_section(&mut order, &mut sections, &label, &section);
            label = None;
            section = line.to_string();
        } else if section.is_empty() {
            section = line.to_string();
        } else {
            section.push('\n');
            section.push_str(line);
        }
    }
    save_section(&mut order, &mut sections, &label, &section);

    let ordered = order
        .into_iter()
        .map(|label| {
            let body = sections.get(&label).cloned().unwrap_or_default();
            (label, body)
        })
        .collect();
    (summary, ordered)
}

/// Score how far `candidate` is from `cmd_name` using a patiencediff-based
/// edit distance.
///
/// The two names are compared character by character. Deletions, insertions and
/// replacements add to the distance; equal runs subtract a small amount so that
/// similarly-shaped names of equal length sort ahead of arbitrary ones.
fn guess_distance(cmd_name: &[char], candidate: &[char]) -> f64 {
    let mut matcher = patiencediff::SequenceMatcher::new(cmd_name, candidate);
    let mut distance = 0.0f64;
    for opcode in matcher.get_opcodes() {
        // l = a-range (cmd_name), r = b-range (candidate).
        let l1 = opcode.a_start() as i64;
        let l2 = opcode.a_end() as i64;
        let r1 = opcode.b_start() as i64;
        let r2 = opcode.b_end() as i64;
        match opcode {
            patiencediff::Opcode::Delete(..) => distance += (l2 - l1) as f64,
            // TODO: ``r2 - l1`` looks like a bug (``r2 - r1`` was probably
            // meant); it is kept so suggestions match earlier releases.
            patiencediff::Opcode::Replace(..) => distance += (l2 - l1).max(r2 - l1) as f64,
            patiencediff::Opcode::Insert(..) => distance += (r2 - r1) as f64,
            patiencediff::Opcode::Equal(..) => distance -= 0.1 * (l2 - l1) as f64,
        }
    }
    distance
}

/// Guess which command a user meant when `cmd_name` was not found.
///
/// `candidates` is the full set of known command names and aliases (gathered
/// by the caller, which needs the registries). `overrides` are the hard-coded
/// cost overrides for this `cmd_name`; they replace or add costs before the
/// final selection. Returns the closest candidate, or `None` if nothing scores
/// at or below the cutoff of 4.
pub fn guess_command(
    cmd_name: &str,
    candidates: &[String],
    overrides: &[(String, f64)],
) -> Option<String> {
    let cmd_chars: Vec<char> = cmd_name.chars().collect();
    let mut costs: std::collections::HashMap<String, f64> = std::collections::HashMap::new();
    for name in candidates {
        let name_chars: Vec<char> = name.chars().collect();
        costs.insert(name.clone(), guess_distance(&cmd_chars, &name_chars));
    }
    for (key, value) in overrides {
        costs.insert(key.clone(), *value);
    }

    // Lowest cost first, ties broken on the name.
    let mut entries: Vec<(f64, String)> = costs.into_iter().map(|(k, v)| (v, k)).collect();
    entries.sort_by(|a, b| {
        a.0.partial_cmp(&b.0)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.1.cmp(&b.1))
    });

    let (cost, candidate) = entries.into_iter().next()?;
    if cost > 4.0 {
        return None;
    }
    Some(candidate)
}

/// The master options parsed from the front of a ``brz`` command line.
///
/// These control how the command itself is interpreted and are stripped from
/// the argument vector before command lookup. Side effects (setting debug
/// flags, the concurrency environment variable, config overrides) are left to
/// the caller; this struct only carries the parsed data.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct MasterOptions {
    /// ``--lsprof`` or ``--lsprof-file`` was given.
    pub lsprof: bool,
    /// ``--profile`` was given.
    pub profile: bool,
    /// ``--no-plugins`` was given.
    pub no_plugins: bool,
    /// ``--no-aliases`` was given.
    pub no_aliases: bool,
    /// ``--no-l10n`` was given.
    pub no_l10n: bool,
    /// ``--builtin`` was given.
    pub builtin: bool,
    /// ``--coverage`` was given.
    pub coverage: bool,
    /// The argument to ``--lsprof-file``, if any.
    pub lsprof_file: Option<String>,
    /// The argument to ``--concurrency``, if any (the caller sets
    /// ``BRZ_CONCURRENCY`` from it).
    pub concurrency: Option<String>,
    /// Debug flags collected from ``-D`` arguments.
    pub debug_flags: Vec<String>,
    /// Config overrides collected from ``-O`` arguments.
    pub config_overrides: Vec<String>,
}

/// Error returned when a master option that consumes the next argument is
/// missing it (e.g. a trailing ``--lsprof-file``).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MissingMasterOptionArgument {
    /// The option that was missing its argument.
    pub option: String,
}

/// Scan and strip the master options from the front of `argv`.
///
/// Returns the parsed [`MasterOptions`] and the remaining argument vector (with
/// the master options removed). Returns an error if ``--lsprof-file`` or ``--concurrency`` appears
/// without a following argument.
pub fn scan_master_options(
    argv: Vec<String>,
) -> Result<(MasterOptions, Vec<String>), MissingMasterOptionArgument> {
    let mut opts = MasterOptions::default();
    let mut remaining: Vec<String> = Vec::new();
    let mut i = 0;
    while i < argv.len() {
        let a = &argv[i];
        match a.as_str() {
            "--profile" => opts.profile = true,
            "--lsprof" => opts.lsprof = true,
            "--lsprof-file" => {
                opts.lsprof = true;
                let value = argv.get(i + 1).ok_or(MissingMasterOptionArgument {
                    option: "--lsprof-file".to_string(),
                })?;
                opts.lsprof_file = Some(value.clone());
                i += 1;
            }
            "--no-plugins" => opts.no_plugins = true,
            "--no-aliases" => opts.no_aliases = true,
            "--no-l10n" => opts.no_l10n = true,
            "--builtin" => opts.builtin = true,
            "--concurrency" => {
                let value = argv.get(i + 1).ok_or(MissingMasterOptionArgument {
                    option: "--concurrency".to_string(),
                })?;
                opts.concurrency = Some(value.clone());
                i += 1;
            }
            "--coverage" => opts.coverage = true,
            "--profile-imports" => {} // already handled in the startup script
            other if other.starts_with("-D") => {
                opts.debug_flags.push(other[2..].to_string());
            }
            other if other.starts_with("-O") => {
                opts.config_overrides.push(other[2..].to_string());
            }
            _ => remaining.push(a.clone()),
        }
        i += 1;
    }
    Ok((opts, remaining))
}

/// Which profiler `run_bzr` should run a command under.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Profiler {
    /// No profiler.
    None,
    /// The lsprof profiler (``--lsprof`` / ``--lsprof-file``).
    Lsprof,
    /// The hotshot profiler (``--profile``).
    Profile,
    /// Coverage reporting (``--coverage``).
    Coverage,
}

impl Profiler {
    /// The name the dispatcher passes to ``run_command`` to select this profiler.
    pub fn name(self) -> &'static str {
        match self {
            Profiler::None => "none",
            Profiler::Lsprof => "lsprof",
            Profiler::Profile => "profile",
            Profiler::Coverage => "coverage",
        }
    }
}

/// Decide which profiler to use given the master options, and collect any
/// warnings that should be emitted.
///
/// ``--lsprof`` wins over ``--profile`` which wins over ``--coverage``; when ``--coverage`` is combined with a
/// higher-precedence profiler a warning is produced explaining it was ignored.
pub fn select_profiler(opts: &MasterOptions) -> (Profiler, Vec<String>) {
    let mut warnings = Vec::new();
    if opts.lsprof {
        if opts.coverage {
            warnings.push("--coverage ignored, because --lsprof is in use.".to_string());
        }
        (Profiler::Lsprof, warnings)
    } else if opts.profile {
        if opts.coverage {
            warnings.push("--coverage ignored, because --profile is in use.".to_string());
        }
        (Profiler::Profile, warnings)
    } else if opts.coverage {
        (Profiler::Coverage, warnings)
    } else {
        (Profiler::None, warnings)
    }
}

/// What ``run_bzr`` does with the post-master-option argv.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Dispatch {
    /// No command given: show the top-level help.
    ShowHelp,
    /// The first argument is ``--version``: show the version.
    ShowVersion,
    /// Run a command (the argv begins with the command name).
    RunCommand,
}

/// Decide what ``run_bzr`` should do with `argv` after master options are
/// stripped: no command shows help, a leading ``--version`` shows the version,
/// otherwise a command is run.
pub fn classify_dispatch(argv: &[String]) -> Dispatch {
    match argv.first() {
        None => Dispatch::ShowHelp,
        Some(first) if first == "--version" => Dispatch::ShowVersion,
        Some(_) => Dispatch::RunCommand,
    }
}

/// Apply a resolved command alias to the argv.
///
/// `expansion` is what ``get_alias`` returned for ``argv[0]``: `None` (no alias)
/// or the alias's tokens. A non-empty expansion replaces ``argv[0]`` with its
/// first token; the remaining tokens become the returned `alias_argv` (the extra
/// arguments prepended to the command line). When there is no alias, `argv` is
/// unchanged and `None` is returned.
pub fn apply_alias(argv: &mut [String], expansion: Option<Vec<String>>) -> Option<Vec<String>> {
    let mut expanded = expansion?;
    if !expanded.is_empty() {
        argv[0] = expanded.remove(0);
    }
    Some(expanded)
}

/// Resolve the argv to dispatch.
///
/// `None` means "read `sys.argv` later" (the caller resolves it); an explicit
/// list has its program name (``argv[0]``) dropped.
pub fn drop_program_name(argv: Option<Vec<String>>) -> Option<Vec<String>> {
    argv.map(|a| a.into_iter().skip(1).collect())
}

/// Find `cmd` on a ``BZRPATH``-style search path (the search half of
/// ``ExternalCommand.find_command``).
///
/// `bzrpath` is the raw path variable, split on `separator` (``os.pathsep``).
/// Empty entries are not real paths and are skipped. Returns the first entry
/// joined with `cmd` that `is_file` reports as a file, letting the caller
/// decide how to test that (the real lookup uses ``os.path.isfile``, which can
/// itself fail, so the test is fallible).
pub fn find_on_bzrpath<E>(
    bzrpath: &str,
    separator: char,
    cmd: &str,
    mut is_file: impl FnMut(&str) -> Result<bool, E>,
) -> Result<Option<String>, E> {
    for dir in bzrpath.split(separator) {
        // Empty directories are not real paths.
        if dir.is_empty() {
            continue;
        }
        // Joined rather than concatenated, so Windows can find a batch file.
        let path = std::path::Path::new(dir).join(cmd);
        let Some(path) = path.to_str() else { continue };
        if is_file(path)? {
            return Ok(Some(path.to_string()));
        }
    }
    Ok(None)
}

/// One hook point on ``Command.hooks``: its name, documentation and the
/// release it was introduced in.
pub struct CommandHookDef {
    /// The hook point's name, as used to index ``Command.hooks``.
    pub name: &'static str,
    /// The documentation shown for the hook point.
    pub doc: &'static str,
    /// The ``(major, minor)`` release the hook point was introduced in.
    pub introduced: (u32, u32),
}

/// The hook points defined on ``Command.hooks``, in definition order (the body
/// of ``CommandHooks.__init__``).
pub fn command_hook_defs() -> &'static [CommandHookDef] {
    &[
        CommandHookDef {
            name: "extend_command",
            doc: "Called after creating a command object to allow modifications \
                  such as adding or removing options, docs etc. Called with the \
                  new breezy.commands.Command object.",
            introduced: (1, 13),
        },
        CommandHookDef {
            name: "get_command",
            doc: "Called when creating a single command. Called with \
                  (cmd_or_none, command_name). get_command should either return \
                  the cmd_or_none parameter, or a replacement Command object that \
                  should be used for the command. Note that the Command.hooks \
                  hooks are core infrastructure. Many users will prefer to use \
                  breezy.commands.register_command or plugin_cmds.register_lazy.",
            introduced: (1, 17),
        },
        CommandHookDef {
            name: "get_missing_command",
            doc: "Called when creating a single command if no command could be \
                  found. Called with (command_name). get_missing_command should \
                  either return None, or a Command object to be used for the \
                  command.",
            introduced: (1, 17),
        },
        CommandHookDef {
            name: "list_commands",
            doc: "Called when enumerating commands. Called with a set of \
                  cmd_name strings for all the commands found so far. This set \
                  \u{20}is safe to mutate - e.g. to remove a command. \
                  list_commands should return the updated set of command names.",
            introduced: (1, 17),
        },
        CommandHookDef {
            name: "pre_command",
            doc: "Called prior to executing a command. Called with the command object.",
            introduced: (2, 6),
        },
        CommandHookDef {
            name: "post_command",
            doc: "Called after executing a command. Called with the command object.",
            introduced: (2, 6),
        },
    ]
}

/// The message telling the user which uninstalled plugin provides a command.
pub fn command_available_in_plugin(cmd_name: &str, plugin_name: &str, url: &str) -> String {
    format!(
        "\"{cmd_name}\" is not a standard brz command. \n\
         However, the following official plugin provides this command: {plugin_name}\n\
         You can install it by going to: {url}"
    )
}

/// The source of command objects: the hook-driven lookup and enumeration.
///
/// This abstracts the ``get_command`` / ``get_missing_command`` /
/// ``extend_command`` / ``list_commands`` hook machinery that
/// ``_get_cmd_object`` and ``all_command_names`` drive. The control flow (the
/// override rule, the hook iteration order, the ``invoked_as`` defaulting, the
/// ``list_commands`` None-guard) lives here as pure default methods; the
/// implementor supplies only the primitive operations - iterating the hooks and
/// calling them. The PyO3 implementation (in [`crate::commands`]) wraps the real
/// ``Command.hooks`` and Python command objects; this trait keeps the logic
/// itself free of any PyO3 dependency.
///
/// The command and hook representations are left to the implementor, so the
/// logic compiles without PyO3.
pub trait CommandSource {
    /// A resolved command object (a Python `Command` in the PyO3 impl).
    type Cmd;
    /// A registered hook callback.
    type Hook;
    /// The registered ``list_commands`` hooks, in iteration order.
    fn list_commands_hooks(&self) -> Result<Vec<Self::Hook>, CommandError>;
    /// Call a ``list_commands`` hook with the accumulating name set; returns the
    /// updated set, or `None` if the hook (incorrectly) returned nothing.
    fn call_list_hook(
        &self,
        hook: &Self::Hook,
        names: std::collections::BTreeSet<String>,
    ) -> Result<Option<std::collections::BTreeSet<String>>, CommandError>;
    /// A display label for a hook, for the ``list_commands`` None-guard error.
    fn hook_label(&self, hook: &Self::Hook) -> Result<String, CommandError>;

    /// The registered ``get_command`` hooks, in iteration order.
    fn get_command_hooks(&self) -> Result<Vec<Self::Hook>, CommandError>;
    /// The registered ``get_missing_command`` hooks, in iteration order.
    fn get_missing_command_hooks(&self) -> Result<Vec<Self::Hook>, CommandError>;
    /// The registered ``extend_command`` hooks, in iteration order.
    fn extend_command_hooks(&self) -> Result<Vec<Self::Hook>, CommandError>;

    /// Call a ``get_command`` hook with the current command (or none) and the
    /// command name; returns the hook's replacement command, if any.
    fn call_get_command(
        &self,
        hook: &Self::Hook,
        current: Option<&Self::Cmd>,
        cmd_name: &str,
    ) -> Result<Option<Self::Cmd>, CommandError>;
    /// Call a ``get_missing_command`` hook with the command name.
    fn call_get_missing(
        &self,
        hook: &Self::Hook,
        cmd_name: &str,
    ) -> Result<Option<Self::Cmd>, CommandError>;
    /// Call an ``extend_command`` hook with the resolved command.
    fn call_extend(&self, hook: &Self::Hook, cmd: &Self::Cmd) -> Result<(), CommandError>;

    /// Whether `cmd` reports a plugin name (used by the override rule).
    fn is_plugin_command(&self, cmd: &Self::Cmd) -> Result<bool, CommandError>;
    /// Whether `cmd` already has its ``invoked_as`` set.
    fn has_invoked_as(&self, cmd: &Self::Cmd) -> Result<bool, CommandError>;
    /// Record that `cmd` was invoked as `cmd_name`.
    fn set_invoked_as(&self, cmd: &Self::Cmd, cmd_name: &str) -> Result<(), CommandError>;

    /// Resolve a command object by name.
    ///
    /// Drives the hook iteration and the override rule: a non-plugin command
    /// found while `plugins_override` is false is not overridden by later hooks.
    /// If nothing is found and `check_missing` is set, the
    /// ``get_missing_command`` hooks are tried. The resolved command is passed
    /// through every ``extend_command`` hook and its ``invoked_as`` defaulted.
    /// Returns `Ok(None)` when no command is found (the caller raises the
    /// user-facing error).
    fn resolve_command(
        &self,
        cmd_name: &str,
        plugins_override: bool,
        check_missing: bool,
    ) -> Result<Option<Self::Cmd>, CommandError> {
        let mut cmd: Option<Self::Cmd> = None;

        for hook in self.get_command_hooks()? {
            if let Some(found) = self.call_get_command(&hook, cmd.as_ref(), cmd_name)? {
                // plugin_name() is only consulted when plugins_override is false.
                let stop = !plugins_override && !self.is_plugin_command(&found)?;
                cmd = Some(found);
                if stop {
                    // A non-plugin command found; later hooks don't override it.
                    break;
                }
            }
        }

        if cmd.is_none() && check_missing {
            for hook in self.get_missing_command_hooks()? {
                if let Some(found) = self.call_get_missing(&hook, cmd_name)? {
                    cmd = Some(found);
                    break;
                }
            }
        }

        let Some(cmd) = cmd else {
            return Ok(None);
        };

        for hook in self.extend_command_hooks()? {
            self.call_extend(&hook, &cmd)?;
        }
        if !self.has_invoked_as(&cmd)? {
            self.set_invoked_as(&cmd, cmd_name)?;
        }
        Ok(Some(cmd))
    }

    /// Collect every command name.
    ///
    /// Threads an accumulating name set through each ``list_commands`` hook. A
    /// hook that returns nothing is a programming error and raises, naming the
    /// offending hook in an ``AssertionError``.
    fn enumerate_names(&self) -> Result<std::collections::BTreeSet<String>, CommandError> {
        let mut names = std::collections::BTreeSet::new();
        for hook in self.list_commands_hooks()? {
            match self.call_list_hook(&hook, names)? {
                Some(updated) => names = updated,
                None => {
                    let label = self.hook_label(&hook)?;
                    return Err(CommandError::internal_as(
                        "AssertionError",
                        format!("hook {label} returned None"),
                    ));
                }
            }
        }
        Ok(names)
    }
}

/// How a command's output stream treats characters the output encoding cannot
/// represent (``Command.encoding_type``).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum EncodingType {
    /// Raise an error on an unencodable character.
    #[default]
    Strict,
    /// Replace an unencodable character with ``?``.
    Replace,
    /// Write bytes through unchanged (for commands such as ``cat`` and ``diff``).
    Exact,
}

impl EncodingType {
    /// The name the Python output stream factory takes.
    pub fn as_str(self) -> &'static str {
        match self {
            EncodingType::Strict => "strict",
            EncodingType::Replace => "replace",
            EncodingType::Exact => "exact",
        }
    }
}

impl std::str::FromStr for EncodingType {
    type Err = CommandError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "strict" => Ok(EncodingType::Strict),
            "replace" => Ok(EncodingType::Replace),
            "exact" => Ok(EncodingType::Exact),
            other => Err(CommandError::internal_as(
                "ValueError",
                format!("unknown encoding type {other:?}"),
            )),
        }
    }
}

/// The description of a command: everything about it except how it runs.
///
/// This is what the registry, the help system and the option parser need to
/// know.
#[derive(Debug, Clone, Default)]
pub struct CommandSpec {
    /// The canonical command name (e.g. ``status``).
    pub name: String,
    /// Alternative names the command is also known by (e.g. ``st``).
    pub aliases: Vec<String>,
    /// The positional argument specification (e.g. ``["file*"]``).
    pub takes_args: Vec<String>,
    /// The help text, or `None` if the command has none of its own.
    pub help: Option<String>,
    /// Whether the command is left out of the command list.
    pub hidden: bool,
    /// How the output stream treats unencodable characters.
    pub encoding_type: EncodingType,
    /// Related help topics (``_see_also``), unsorted.
    pub see_also: Vec<String>,
    /// The plugin providing the command, or `None` for a builtin.
    pub plugin_name: Option<String>,
    /// Whether the command only displays information, so that a broken pipe or
    /// an interrupt ends it quietly (``@display_command``).
    pub display: bool,
    /// The command's own options, beyond the standard ones.
    pub options: Vec<crate::option::OptionRef>,
}

impl CommandSpec {
    /// A spec for the command `name`, with everything else at its default.
    pub fn new(name: impl Into<String>) -> Self {
        CommandSpec {
            name: name.into(),
            ..Default::default()
        }
    }

    /// Related help topics, deduplicated and lexically sorted, together with
    /// `additional` ones.
    pub fn get_see_also(&self, additional: Option<Vec<String>>) -> Vec<String> {
        let mut set: std::collections::BTreeSet<String> = self.see_also.iter().cloned().collect();
        set.extend(additional.unwrap_or_default());
        set.into_iter().collect()
    }

    /// Build the full help text for the command.
    ///
    /// Assembles the purpose and usage header, the options block, the
    /// description and any custom sections, and the aliases / plugin / see-also
    /// footer. `option_help` is
    /// the rendered options block (``Options:`` followed by the options). With
    /// `plain` the result is rendered to plain text; otherwise raw
    /// reStructuredText is returned. With `verbose` false, the descriptive
    /// sections are left out in favour of a pointer to the full help.
    ///
    /// `localise` selects whether the help text is translated; the caller is
    /// responsible for having installed the i18n catalogue when it is set.
    pub fn help_text(
        &self,
        option_help: &str,
        additional_see_also: Option<Vec<String>>,
        plain: bool,
        see_also_as_links: bool,
        verbose: bool,
        localise: bool,
    ) -> String {
        let tr = |s: &str| crate::i18n::gettext(s);
        let doc = match &self.help {
            Some(d) if !d.is_empty() => {
                if localise {
                    crate::i18n::gettext_per_paragraph(d)
                } else {
                    d.clone()
                }
            }
            _ => tr("No help for this command."),
        };

        let (purpose, mut sections) = split_help_parts(&doc);
        let usage = match take_section(&mut sections, &Some("Usage".to_string())) {
            Some(u) => u,
            None => usage(&self.name, &self.takes_args),
        };

        let mut result = String::new();
        result.push_str(&fmt1(&tr(":Purpose: %s\n"), &purpose));
        if usage.contains('\n') {
            result.push_str(&fmt1(&tr(":Usage:\n%s\n"), &usage));
        } else {
            result.push_str(&fmt1(&tr(":Usage:   %s\n"), &usage));
        }
        result.push('\n');

        let mut options = option_help.to_string();
        if !plain && options.contains("  --1.14  ") {
            options = options.replacen(" format:\n", " format::\n\n", 1);
        }
        if let Some(rest) = options.strip_prefix("Options:") {
            result.push_str(&fmt1(&tr(":Options:%s"), rest));
        } else {
            result.push_str(&options);
        }
        result.push('\n');

        if verbose {
            if let Some(text) = take_section(&mut sections, &None) {
                // "\n  ".join(text.splitlines()); str::lines matches splitlines'
                // no-trailing-empty behaviour so we do not emit a spurious blank.
                let text = text.lines().collect::<Vec<_>>().join("\n  ");
                result.push_str(&fmt1(&tr(":Description:\n  %s\n\n"), &text));
            }
            if !sections.is_empty() {
                for (label, body) in &sections {
                    if let Some(label) = label {
                        result.push_str(&format!(":{label}:\n{body}\n"));
                    }
                }
                result.push('\n');
            }
        } else {
            result.push_str(&fmt1(
                &tr("See brz help %s for more details and examples.\n\n"),
                &self.name,
            ));
        }

        if !self.aliases.is_empty() {
            result.push_str(&tr(":Aliases:  "));
            result.push_str(&self.aliases.join(", "));
            result.push('\n');
        }
        if let Some(plugin) = &self.plugin_name {
            result.push_str(&fmt1(&tr(":From:     plugin \"%s\"\n"), plugin));
        }
        let mut see_also = self.get_see_also(additional_see_also);
        if !see_also.is_empty() {
            if !plain && see_also_as_links {
                see_also = see_also
                    .into_iter()
                    .map(|item| {
                        if item == "topics" {
                            item
                        } else {
                            // gettext(":doc:`{0} <{1}-help>`").format(item, item)
                            tr(":doc:`{0} <{1}-help>`")
                                .replace("{0}", &item)
                                .replace("{1}", &item)
                        }
                    })
                    .collect();
            }
            result.push_str(&fmt1(&tr(":See also: %s"), &see_also.join(", ")));
            result.push('\n');
        }

        if plain {
            result = crate::help::help_as_plain_text(&result);
        }
        result
    }
}

/// What a running command can reach of its environment.
///
/// The command machinery supplies this to [`Command::run`]. Resources that need
/// releasing when the command ends are plain Rust values dropped at the end of
/// ``run``, so there is no equivalent of the Python ``add_cleanup``.
pub trait CommandContext {
    /// The command's output stream (the Python ``self.outf``), already set up
    /// for the command's [`EncodingType`].
    fn out(&mut self) -> &mut dyn std::io::Write;

    /// Tell the user something (``trace.note``); suppressed when quiet.
    fn note(&mut self, message: &str) -> Result<(), CommandError>;

    /// Warn the user about something (``trace.warning``).
    fn warning(&mut self, message: &str) -> Result<(), CommandError>;

    /// The name the command was invoked as: its name or one of its aliases.
    fn invoked_as(&self) -> &str;

    /// The verbosity level: positive for ``-v`` (``-vv`` is 2), negative for
    /// ``-q``, zero by default.
    fn verbosity(&self) -> i32;
}

/// A breezy command implemented in Rust.
///
/// Commands implemented in Python are not instances of this trait; they are
/// Python subclasses of ``breezy.commands.Command``.
pub trait Command: Send + Sync {
    /// The description of the command.
    fn spec(&self) -> CommandSpec;

    /// Run the command with the parsed options and the positional arguments
    /// matched against [`CommandSpec::takes_args`], returning its exit code.
    fn run(
        &self,
        ctx: &mut dyn CommandContext,
        opts: &crate::option::ParsedOptions,
        args: &MatchedArgs,
    ) -> Result<i32, CommandError>;
}

/// `fmt % (arg,)` for the single-`%s` format strings used in help assembly.
///
/// The help format strings contain exactly one ``%s`` and no other ``%``, so a
/// single substitution reproduces Python's ``%``-formatting here.
fn fmt1(fmt: &str, arg: &str) -> String {
    fmt.replacen("%s", arg, 1)
}

/// Remove and return the body of the first section labelled `label`, preserving
/// the order of the remaining sections in the list produced by
/// [`split_help_parts`].
fn take_section(
    sections: &mut Vec<(Option<String>, String)>,
    label: &Option<String>,
) -> Option<String> {
    let pos = sections.iter().position(|(l, _)| l == label)?;
    Some(sections.remove(pos).1)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;

    #[test]
    fn find_on_bzrpath_cases() {
        let exists = |p: &str| Ok::<_, ()>(p == "/b/mycmd");
        assert_eq!(
            Ok(Some("/b/mycmd".to_string())),
            find_on_bzrpath("/a:/b:/c", ':', "mycmd", exists)
        );
        // Empty entries are skipped rather than searched as the cwd.
        assert_eq!(
            Ok(Some("/b/mycmd".to_string())),
            find_on_bzrpath("::/b", ':', "mycmd", exists)
        );
        assert_eq!(Ok(None), find_on_bzrpath("/a:/c", ':', "mycmd", exists));
        assert_eq!(Ok(None), find_on_bzrpath("", ':', "mycmd", exists));
        // A failing file test propagates rather than reading as "not found".
        assert_eq!(
            Err("boom"),
            find_on_bzrpath("/a", ':', "mycmd", |_| Err("boom"))
        );
    }

    #[test]
    fn command_hook_docs_match_python() {
        let defs = command_hook_defs();
        assert_eq!(6, defs.len());
        let by_name = |n: &str| defs.iter().find(|d| d.name == n).unwrap();
        assert_eq!(
            "Called after creating a command object to allow modifications such as \
             adding or removing options, docs etc. Called with the new \
             breezy.commands.Command object.",
            by_name("extend_command").doc
        );
        assert_eq!(
            "Called when creating a single command. Called with (cmd_or_none, \
             command_name). get_command should either return the cmd_or_none \
             parameter, or a replacement Command object that should be used for \
             the command. Note that the Command.hooks hooks are core \
             infrastructure. Many users will prefer to use \
             breezy.commands.register_command or plugin_cmds.register_lazy.",
            by_name("get_command").doc
        );
        assert_eq!(
            "Called when creating a single command if no command could be found. \
             Called with (command_name). get_missing_command should either return \
             None, or a Command object to be used for the command.",
            by_name("get_missing_command").doc
        );
        // Note the double space after "This set" - an upstream typo that the
        // help output has always shown, so it is reproduced verbatim.
        assert_eq!(
            "Called when enumerating commands. Called with a set of cmd_name \
             strings for all the commands found so far. This set \
             \u{20}is safe to mutate - e.g. to remove a command. list_commands \
             should return the \
             updated set of command names.",
            by_name("list_commands").doc
        );
        assert_eq!((2, 6), by_name("post_command").introduced);
    }

    #[test]
    fn command_available_in_plugin_message() {
        assert_eq!(
            "\"foo\" is not a standard brz command. \n\
             However, the following official plugin provides this command: bzr-foo\n\
             You can install it by going to: http://example.com/foo",
            command_available_in_plugin("foo", "bzr-foo", "http://example.com/foo")
        );
    }

    /// A pyo3-free `CommandSource` for testing the pure orchestration. A command
    /// is just a name; a hook is a canned behaviour.
    #[derive(Clone)]
    enum MockHook {
        /// Return a command with this name (and plugin-ness) for any lookup.
        Returns(String, bool),
        /// Return nothing.
        Nothing,
    }

    #[derive(Default)]
    struct MockSource {
        get_command: Vec<MockHook>,
        get_missing: Vec<MockHook>,
        list_commands: Vec<MockHook>,
        extended: RefCell<Vec<String>>,
        invoked_as: RefCell<Vec<(String, String)>>,
    }

    impl CommandSource for MockSource {
        type Cmd = (String, bool);
        type Hook = MockHook;
        fn list_commands_hooks(&self) -> Result<Vec<MockHook>, CommandError> {
            Ok(self.list_commands.clone())
        }
        fn call_list_hook(
            &self,
            hook: &MockHook,
            mut names: std::collections::BTreeSet<String>,
        ) -> Result<Option<std::collections::BTreeSet<String>>, CommandError> {
            Ok(match hook {
                // Reuse Returns' name field as a name to add to the set.
                MockHook::Returns(n, _) => {
                    names.insert(n.clone());
                    Some(names)
                }
                // Nothing models a hook that (wrongly) returned None here.
                MockHook::Nothing => None,
            })
        }
        fn hook_label(&self, _hook: &MockHook) -> Result<String, CommandError> {
            Ok("mock hook".to_string())
        }

        fn get_command_hooks(&self) -> Result<Vec<MockHook>, CommandError> {
            Ok(self.get_command.clone())
        }
        fn get_missing_command_hooks(&self) -> Result<Vec<MockHook>, CommandError> {
            Ok(self.get_missing.clone())
        }
        fn extend_command_hooks(&self) -> Result<Vec<MockHook>, CommandError> {
            Ok(vec![MockHook::Nothing])
        }
        fn call_get_command(
            &self,
            hook: &MockHook,
            _current: Option<&(String, bool)>,
            _cmd_name: &str,
        ) -> Result<Option<(String, bool)>, CommandError> {
            Ok(match hook {
                MockHook::Returns(n, plugin) => Some((n.clone(), *plugin)),
                MockHook::Nothing => None,
            })
        }
        fn call_get_missing(
            &self,
            hook: &MockHook,
            _cmd_name: &str,
        ) -> Result<Option<(String, bool)>, CommandError> {
            Ok(match hook {
                MockHook::Returns(n, plugin) => Some((n.clone(), *plugin)),
                MockHook::Nothing => None,
            })
        }
        fn call_extend(&self, _hook: &MockHook, cmd: &(String, bool)) -> Result<(), CommandError> {
            self.extended.borrow_mut().push(cmd.0.clone());
            Ok(())
        }
        fn is_plugin_command(&self, cmd: &(String, bool)) -> Result<bool, CommandError> {
            Ok(cmd.1)
        }
        fn has_invoked_as(&self, _cmd: &(String, bool)) -> Result<bool, CommandError> {
            Ok(false)
        }
        fn set_invoked_as(&self, cmd: &(String, bool), cmd_name: &str) -> Result<(), CommandError> {
            self.invoked_as
                .borrow_mut()
                .push((cmd.0.clone(), cmd_name.to_string()));
            Ok(())
        }
    }

    #[test]
    fn resolve_command_found_and_extended() {
        let src = MockSource {
            get_command: vec![MockHook::Returns("status".into(), false)],
            ..Default::default()
        };
        let cmd = src.resolve_command("status", true, true).unwrap();
        assert_eq!(cmd, Some(("status".to_string(), false)));
        // The extend hook ran and invoked_as was defaulted.
        assert_eq!(*src.extended.borrow(), vec!["status".to_string()]);
        assert_eq!(
            *src.invoked_as.borrow(),
            vec![("status".to_string(), "status".to_string())]
        );
    }

    #[test]
    fn resolve_command_override_rule() {
        // A non-plugin command found while plugins_override is false stops the
        // iteration: the later (plugin) hook does not override it.
        let src = MockSource {
            get_command: vec![
                MockHook::Returns("builtin".into(), false),
                MockHook::Returns("plugin".into(), true),
            ],
            ..Default::default()
        };
        let cmd = src.resolve_command("x", false, true).unwrap();
        assert_eq!(cmd, Some(("builtin".to_string(), false)));
    }

    #[test]
    fn resolve_command_plugins_override_keeps_last() {
        // With plugins_override true, later hooks do override.
        let src = MockSource {
            get_command: vec![
                MockHook::Returns("builtin".into(), false),
                MockHook::Returns("plugin".into(), true),
            ],
            ..Default::default()
        };
        let cmd = src.resolve_command("x", true, true).unwrap();
        assert_eq!(cmd, Some(("plugin".to_string(), true)));
    }

    #[test]
    fn resolve_command_missing_then_check_missing() {
        let src = MockSource {
            get_command: vec![MockHook::Nothing],
            get_missing: vec![MockHook::Returns("fromplugin".into(), true)],
            ..Default::default()
        };
        // check_missing true: the missing hook supplies the command.
        assert_eq!(
            src.resolve_command("x", true, true).unwrap(),
            Some(("fromplugin".to_string(), true))
        );
        // check_missing false: nothing found.
        let src2 = MockSource {
            get_command: vec![MockHook::Nothing],
            get_missing: vec![MockHook::Returns("fromplugin".into(), true)],
            ..Default::default()
        };
        assert_eq!(src2.resolve_command("x", true, false).unwrap(), None);
    }

    #[test]
    fn enumerate_names_threads_set() {
        let src = MockSource {
            list_commands: vec![
                MockHook::Returns("status".into(), false),
                MockHook::Returns("commit".into(), false),
            ],
            ..Default::default()
        };
        assert_eq!(
            vec!["commit".to_string(), "status".to_string()],
            src.enumerate_names()
                .unwrap()
                .into_iter()
                .collect::<Vec<_>>()
        );
    }

    #[test]
    fn enumerate_names_none_guard_errors() {
        let src = MockSource {
            list_commands: vec![MockHook::Nothing],
            ..Default::default()
        };
        assert!(matches!(
            src.enumerate_names(),
            Err(CommandError::Internal { kind: Some(kind), .. }) if kind == "AssertionError"
        ));
    }

    #[test]
    fn drop_program_name_cases() {
        assert_eq!(drop_program_name(None), None);
        assert_eq!(
            drop_program_name(Some(vec!["brz".into(), "status".into(), "-v".into()])),
            Some(vec!["status".to_string(), "-v".to_string()])
        );
        // A bare program name leaves an empty argv.
        assert_eq!(drop_program_name(Some(vec!["brz".into()])), Some(vec![]));
    }

    #[test]
    fn profiler_names() {
        assert_eq!(Profiler::None.name(), "none");
        assert_eq!(Profiler::Lsprof.name(), "lsprof");
        assert_eq!(Profiler::Profile.name(), "profile");
        assert_eq!(Profiler::Coverage.name(), "coverage");
    }

    #[test]
    fn classify_dispatch_cases() {
        assert_eq!(classify_dispatch(&[]), Dispatch::ShowHelp);
        assert_eq!(
            classify_dispatch(&["--version".to_string()]),
            Dispatch::ShowVersion
        );
        assert_eq!(
            classify_dispatch(&["--version".to_string(), "extra".to_string()]),
            Dispatch::ShowVersion
        );
        assert_eq!(
            classify_dispatch(&["status".to_string()]),
            Dispatch::RunCommand
        );
    }

    #[test]
    fn apply_alias_cases() {
        // No alias: argv unchanged, None returned.
        let mut argv = vec!["ci".to_string(), "-m".to_string()];
        assert_eq!(apply_alias(&mut argv, None), None);
        assert_eq!(argv, vec!["ci".to_string(), "-m".to_string()]);

        // Non-empty expansion: argv[0] replaced, rest become alias_argv.
        let mut argv = vec!["ci".to_string(), "file".to_string()];
        let alias = apply_alias(&mut argv, Some(vec!["commit".into(), "-q".into()]));
        assert_eq!(alias, Some(vec!["-q".to_string()]));
        assert_eq!(argv, vec!["commit".to_string(), "file".to_string()]);

        // Empty expansion: argv[0] kept, empty alias_argv.
        let mut argv = vec!["x".to_string()];
        assert_eq!(apply_alias(&mut argv, Some(vec![])), Some(vec![]));
        assert_eq!(argv, vec!["x".to_string()]);
    }

    #[test]
    fn unsquish() {
        assert_eq!(unsquish_command_name("cmd_status"), "status");
        assert_eq!(
            unsquish_command_name("cmd_find_merge_base"),
            "find-merge-base"
        );
        // Names without the prefix are returned with underscores replaced.
        assert_eq!(unsquish_command_name("status"), "status");
    }

    #[test]
    fn squish() {
        assert_eq!(squish_command_name("status"), "cmd_status");
        assert_eq!(
            squish_command_name("find-merge-base"),
            "cmd_find_merge_base"
        );
    }

    #[test]
    fn squish_roundtrip() {
        for name in ["status", "find-merge-base", "commit", "re-sign"] {
            assert_eq!(unsquish_command_name(&squish_command_name(name)), name);
        }
    }

    #[test]
    fn command_error_display() {
        let e = CommandError::User("boom".to_string());
        assert_eq!(e.to_string(), "boom");
    }

    fn specs(items: &[&str]) -> Vec<String> {
        items.iter().map(|s| s.to_string()).collect()
    }

    fn argv(items: &[&str]) -> Vec<String> {
        items.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn argform_plain_required() {
        let r = match_argform("cmd", &specs(&["a", "b"]), argv(&["x", "y"])).unwrap();
        assert_eq!(
            r,
            vec![
                ("a".to_string(), ArgValue::Scalar("x".to_string())),
                ("b".to_string(), ArgValue::Scalar("y".to_string())),
            ]
        );
    }

    #[test]
    fn argform_plain_missing() {
        let e = match_argform("cmd", &specs(&["a"]), argv(&[])).unwrap_err();
        assert_eq!(
            e,
            ArgMatchError::RequiresArgument {
                cmd: "cmd".to_string(),
                argname: "A".to_string(),
            }
        );
    }

    #[test]
    fn argform_optional_present_and_absent() {
        let r = match_argform("cmd", &specs(&["a?"]), argv(&["x"])).unwrap();
        assert_eq!(
            r,
            vec![("a".to_string(), ArgValue::Scalar("x".to_string()))]
        );

        // An absent optional argument is omitted entirely, not bound to None.
        let r = match_argform("cmd", &specs(&["a?"]), argv(&[])).unwrap();
        assert_eq!(r, vec![]);
    }

    #[test]
    fn argform_star_empty_is_none() {
        let r = match_argform("cmd", &specs(&["file*"]), argv(&[])).unwrap();
        assert_eq!(r, vec![("file_list".to_string(), ArgValue::List(None))]);
    }

    #[test]
    fn argform_star_collects_remaining() {
        let r = match_argform("cmd", &specs(&["file*"]), argv(&["a", "b", "c"])).unwrap();
        assert_eq!(
            r,
            vec![(
                "file_list".to_string(),
                ArgValue::List(Some(argv(&["a", "b", "c"]))),
            )]
        );
    }

    #[test]
    fn argform_plus_requires_one() {
        let e = match_argform("cmd", &specs(&["file+"]), argv(&[])).unwrap_err();
        assert_eq!(
            e,
            ArgMatchError::NeedsOneOrMore {
                cmd: "cmd".to_string(),
                argname: "FILE".to_string(),
            }
        );

        let r = match_argform("cmd", &specs(&["file+"]), argv(&["a"])).unwrap();
        assert_eq!(
            r,
            vec![("file_list".to_string(), ArgValue::List(Some(argv(&["a"]))))]
        );
    }

    #[test]
    fn argform_all_but_one() {
        // ``names$`` captures all but the last argument; the last remains and,
        // with no further spec, is reported as an extra argument.
        let e = match_argform("cmd", &specs(&["names$"]), argv(&["a", "b", "c"])).unwrap_err();
        assert_eq!(
            e,
            ArgMatchError::ExtraArgument {
                cmd: "cmd".to_string(),
                extra: "c".to_string(),
            }
        );

        // Followed by a plain arg that consumes the leftover last value.
        let r = match_argform("cmd", &specs(&["names$", "tail"]), argv(&["a", "b", "c"])).unwrap();
        assert_eq!(
            r,
            vec![
                (
                    "names_list".to_string(),
                    ArgValue::List(Some(argv(&["a", "b"])))
                ),
                ("tail".to_string(), ArgValue::Scalar("c".to_string())),
            ]
        );
    }

    #[test]
    fn argform_all_but_one_needs_two() {
        let e = match_argform("cmd", &specs(&["names$"]), argv(&["a"])).unwrap_err();
        assert_eq!(
            e,
            ArgMatchError::NeedsOneOrMore {
                cmd: "cmd".to_string(),
                argname: "NAMES".to_string(),
            }
        );
    }

    #[test]
    fn argform_extra_argument() {
        let e = match_argform("cmd", &specs(&["a"]), argv(&["x", "y"])).unwrap_err();
        assert_eq!(
            e,
            ArgMatchError::ExtraArgument {
                cmd: "cmd".to_string(),
                extra: "y".to_string(),
            }
        );
    }

    #[test]
    fn usage_no_args() {
        assert_eq!(usage("rocks", &[]), "brz rocks");
    }

    #[test]
    fn usage_each_specifier() {
        assert_eq!(usage("cmd", &specs(&["loc"])), "brz cmd LOC");
        assert_eq!(usage("cmd", &specs(&["loc?"])), "brz cmd [LOC]");
        assert_eq!(usage("cmd", &specs(&["file*"])), "brz cmd [FILE...]");
        assert_eq!(usage("cmd", &specs(&["file+"])), "brz cmd FILE...");
        assert_eq!(usage("cmd", &specs(&["names$"])), "brz cmd NAMES...");
    }

    #[test]
    fn usage_multiple_args() {
        assert_eq!(
            usage("status", &specs(&["from", "to?", "file*"])),
            "brz status FROM [TO] [FILE...]"
        );
    }

    #[test]
    fn help_parts_summary_only() {
        let (summary, sections) = split_help_parts("One line summary.");
        assert_eq!(summary, "One line summary.");
        assert_eq!(sections, vec![]);
    }

    #[test]
    fn help_parts_default_section() {
        // The blank line after the summary does not contribute a leading
        // newline.
        let (summary, sections) = split_help_parts("Summary.\n\nMore detail here.\nSecond line.");
        assert_eq!(summary, "Summary.");
        assert_eq!(
            sections,
            vec![(None, "More detail here.\nSecond line.".to_string())]
        );
    }

    #[test]
    fn help_parts_named_sections_in_order() {
        // ``:See also: status`` is NOT a heading (it does not end with ``:``),
        // so it stays part of the default section.
        let text = "Summary.\n\nBody text.\n\n:Examples:\n  do a thing\n\n:See also: status";
        let (summary, sections) = split_help_parts(text);
        assert_eq!(summary, "Summary.");
        assert_eq!(
            sections,
            vec![
                (None, "Body text.\n\n:See also: status".to_string()),
                (Some("Examples".to_string()), "  do a thing\n".to_string()),
            ]
        );
    }

    #[test]
    fn help_parts_repeated_label_merges() {
        let text = "Summary.\n\n:Note:\n  first\n\n:Note:\n  second";
        let (_summary, sections) = split_help_parts(text);
        assert_eq!(
            sections,
            vec![(Some("Note".to_string()), "  first\n\n  second".to_string())]
        );
    }

    #[test]
    fn guess_finds_close_match() {
        let candidates = specs(&["status", "commit", "branch", "checkout", "diff"]);
        assert_eq!(
            guess_command("statue", &candidates, &[]),
            Some("status".to_string())
        );
    }

    #[test]
    fn guess_no_match_returns_none() {
        let candidates = specs(&["status", "commit", "branch"]);
        assert_eq!(guess_command("nothingisevenclose", &candidates, &[]), None);
    }

    #[test]
    fn guess_override_wins() {
        // Without the override the heuristic prefers something else; the
        // override forces ``ci`` to cost 0.
        let candidates = specs(&["ci", "nick", "commit"]);
        let overrides = vec![("ci".to_string(), 0.0)];
        assert_eq!(
            guess_command("ic", &candidates, &overrides),
            Some("ci".to_string())
        );
    }

    #[test]
    fn guess_empty_candidates_returns_none() {
        assert_eq!(guess_command("status", &[], &[]), None);
    }

    #[test]
    fn guess_ties_break_on_name() {
        // Two equally-distant single-char candidates: the lexicographically
        // smaller name wins.
        let candidates = specs(&["b", "a"]);
        assert_eq!(guess_command("z", &candidates, &[]), Some("a".to_string()));
    }

    #[test]
    fn master_options_none() {
        let (opts, rest) = scan_master_options(argv(&["status", "-v"])).unwrap();
        assert_eq!(opts, MasterOptions::default());
        assert_eq!(rest, argv(&["status", "-v"]));
    }

    #[test]
    fn master_options_boolean_flags() {
        let (opts, rest) = scan_master_options(argv(&[
            "--no-plugins",
            "--builtin",
            "--no-aliases",
            "--no-l10n",
            "--profile",
            "--lsprof",
            "--coverage",
            "st",
        ]))
        .unwrap();
        assert!(opts.no_plugins);
        assert!(opts.builtin);
        assert!(opts.no_aliases);
        assert!(opts.no_l10n);
        assert!(opts.profile);
        assert!(opts.lsprof);
        assert!(opts.coverage);
        assert_eq!(rest, argv(&["st"]));
    }

    #[test]
    fn master_options_lsprof_file_consumes_next() {
        let (opts, rest) =
            scan_master_options(argv(&["--lsprof-file", "out.prof", "status"])).unwrap();
        assert!(opts.lsprof);
        assert_eq!(opts.lsprof_file, Some("out.prof".to_string()));
        assert_eq!(rest, argv(&["status"]));
    }

    #[test]
    fn master_options_concurrency_consumes_next() {
        let (opts, rest) = scan_master_options(argv(&["--concurrency", "4", "selftest"])).unwrap();
        assert_eq!(opts.concurrency, Some("4".to_string()));
        assert_eq!(rest, argv(&["selftest"]));
    }

    #[test]
    fn master_options_debug_and_override() {
        let (opts, rest) =
            scan_master_options(argv(&["-Dhpss", "-Ofoo=bar", "-Dbytes", "log"])).unwrap();
        assert_eq!(opts.debug_flags, specs(&["hpss", "bytes"]));
        assert_eq!(opts.config_overrides, specs(&["foo=bar"]));
        assert_eq!(rest, argv(&["log"]));
    }

    #[test]
    fn master_options_profile_imports_dropped() {
        let (_opts, rest) = scan_master_options(argv(&["--profile-imports", "version"])).unwrap();
        assert_eq!(rest, argv(&["version"]));
    }

    #[test]
    fn master_options_missing_lookahead_errors() {
        let err = scan_master_options(argv(&["--lsprof-file"])).unwrap_err();
        assert_eq!(err.option, "--lsprof-file");
        let err = scan_master_options(argv(&["--concurrency"])).unwrap_err();
        assert_eq!(err.option, "--concurrency");
    }

    fn opts_with(lsprof: bool, profile: bool, coverage: bool) -> MasterOptions {
        MasterOptions {
            lsprof,
            profile,
            coverage,
            ..MasterOptions::default()
        }
    }

    #[test]
    fn profiler_none() {
        let (p, w) = select_profiler(&opts_with(false, false, false));
        assert_eq!(p, Profiler::None);
        assert!(w.is_empty());
    }

    #[test]
    fn profiler_precedence() {
        assert_eq!(
            select_profiler(&opts_with(true, false, false)).0,
            Profiler::Lsprof
        );
        assert_eq!(
            select_profiler(&opts_with(false, true, false)).0,
            Profiler::Profile
        );
        assert_eq!(
            select_profiler(&opts_with(false, false, true)).0,
            Profiler::Coverage
        );
        // lsprof wins over profile and coverage.
        assert_eq!(
            select_profiler(&opts_with(true, true, true)).0,
            Profiler::Lsprof
        );
    }

    #[test]
    fn profiler_coverage_ignored_warnings() {
        let (p, w) = select_profiler(&opts_with(true, false, true));
        assert_eq!(p, Profiler::Lsprof);
        assert_eq!(
            w,
            vec!["--coverage ignored, because --lsprof is in use.".to_string()]
        );

        let (p, w) = select_profiler(&opts_with(false, true, true));
        assert_eq!(p, Profiler::Profile);
        assert_eq!(
            w,
            vec!["--coverage ignored, because --profile is in use.".to_string()]
        );

        // Coverage alone produces no warning.
        let (_p, w) = select_profiler(&opts_with(false, false, true));
        assert!(w.is_empty());
    }

    #[test]
    fn encoding_type_round_trip() {
        for t in [
            EncodingType::Strict,
            EncodingType::Replace,
            EncodingType::Exact,
        ] {
            assert_eq!(t, t.as_str().parse().unwrap());
        }
        assert!("bogus".parse::<EncodingType>().is_err());
    }

    #[test]
    fn see_also_sorted_and_deduplicated() {
        let spec = CommandSpec {
            see_also: vec!["log".to_string(), "diff".to_string(), "log".to_string()],
            ..CommandSpec::new("status")
        };
        assert_eq!(
            vec!["diff".to_string(), "log".to_string(), "topics".to_string()],
            spec.get_see_also(Some(vec!["topics".to_string(), "diff".to_string()]))
        );
    }

    #[test]
    fn help_text_raw() {
        let spec = CommandSpec {
            aliases: vec!["e".to_string()],
            takes_args: vec!["file*".to_string()],
            help: Some("Echo things.\n\nMore detail.\n".to_string()),
            see_also: vec!["cat".to_string()],
            plugin_name: Some("echo".to_string()),
            ..CommandSpec::new("echo")
        };
        assert_eq!(
            ":Purpose: Echo things.\n\
             :Usage:   brz echo [FILE...]\n\
             \n\
             :Options:\n  -h, --help  Show help message.\n\
             \n\
             :Description:\n  More detail.\n\
             \n\
             :Aliases:  e\n\
             :From:     plugin \"echo\"\n\
             :See also: cat\n",
            spec.help_text(
                "Options:\n  -h, --help  Show help message.\n",
                None,
                false,
                false,
                true,
                false
            )
        );
    }
}
