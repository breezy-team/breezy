//! Pure helpers for command-line option definitions.
//!
//! These are the parts of ``breezy.option.Option`` that are plain string
//! manipulation rather than Python-callback dispatch. The `Option` class itself is a pyclass (in the cmd-py crate) because it carries Python
//! values (the type-conversion callable, the custom callback, registries) and is
//! subclassed across the codebase; this module holds the logic that needs no
//! PyO3.

use std::sync::atomic::{AtomicI32, Ordering};

/// The verbosity level detected during command-line parsing.
///
/// This is the counter the ``-v`` / ``-q`` option callbacks accumulate (``-vv``
/// -> 2, ``-qq`` -> -2); ``run_bzr`` saves, zeroes and restores it around each
/// command.
static VERBOSITY_LEVEL: AtomicI32 = AtomicI32::new(0);

/// Read the parse-time verbosity level.
pub fn verbosity_level() -> i32 {
    VERBOSITY_LEVEL.load(Ordering::Relaxed)
}

/// Set the parse-time verbosity level.
pub fn set_verbosity_level(level: i32) {
    VERBOSITY_LEVEL.store(level, Ordering::Relaxed);
}

/// Compute the new verbosity level after a ``-v`` / ``-q`` switch fires.
///
/// A falsy `value` (``--no-verbose`` / ``--no-quiet``) resets to 0; otherwise a ``verbose``
/// switch moves towards +, a quiet switch towards -, stepping further only when
/// already on the same side (so ``-q`` after ``-v`` jumps straight to -1).
pub fn bump_verbosity(current: i32, verbose: bool, value: bool) -> i32 {
    if !value {
        0
    } else if verbose {
        if current > 0 {
            current + 1
        } else {
            1
        }
    } else if current < 0 {
        current - 1
    } else {
        -1
    }
}

/// Apply a ``-v`` / ``-q`` switch to the stored verbosity level, returning the
/// new level. This is the side-effecting form used by the option callback.
pub fn apply_verbosity(verbose: bool, value: bool) -> i32 {
    let next = bump_verbosity(verbosity_level(), verbose, value);
    set_verbosity_level(next);
    next
}

/// Split a revision string on the ``..`` range separator.
///
/// The string is split on each ``..`` that is *not* followed by a ``/`` or
/// ``\`` (so ``branch:../../b`` keeps its ``../`` separators, while ``234..567``
/// splits). Matches are non-overlapping, left to right; the two ``.`` characters
/// of a separator are consumed. Each returned piece is a revision specifier (a
/// leading/trailing/double separator yields an empty piece, e.g. ``..`` ->
/// ``["", ""]`` and ``234....789`` -> ``["234", "", "789"]``).
pub fn split_revision_range(revstr: &str) -> Vec<String> {
    let bytes = revstr.as_bytes();
    let mut pieces = Vec::new();
    let mut start = 0;
    let mut i = 0;
    while i + 1 < bytes.len() {
        if bytes[i] == b'.' && bytes[i + 1] == b'.' {
            // The separator is a ".." not followed by '/' or '\'.
            let next = bytes.get(i + 2);
            if next != Some(&b'/') && next != Some(&b'\\') {
                pieces.push(revstr[start..i].to_string());
                i += 2;
                start = i;
                continue;
            }
        }
        i += 1;
    }
    pieces.push(revstr[start..].to_string());
    pieces
}

/// The negation name for an option.
///
/// A ``no-`` prefix is toggled: ``commit`` -> ``no-commit`` and ``no-commit`` ->
/// ``commit``.
pub fn negation_name(name: &str) -> String {
    match name.strip_prefix("no-") {
        Some(rest) => rest.to_string(),
        None => format!("no-{name}"),
    }
}

/// The parameter name an option binds to on the command's ``run`` method.
///
/// An explicit ``param_name`` wins, otherwise the option name with ``-``
/// replaced by ``_``.
pub fn param_name(name: &str, explicit: Option<&str>) -> String {
    match explicit {
        Some(p) => p.to_string(),
        None => name.replace('-', "_"),
    }
}

/// Resolve the argument name for an option: a value-taking option
/// (``has_type``) defaults a missing ``argname`` to ``"ARG"``; a boolean option
/// (no type) must not have an ``argname``.
///
/// Returns the resolved argname (``None`` for booleans), or an error message if a
/// boolean option was given an ``argname``.
pub fn resolve_argname(
    has_type: bool,
    argname: Option<&str>,
) -> Result<Option<String>, &'static str> {
    if !has_type {
        if argname.is_some() {
            return Err("argname not valid for booleans");
        }
        Ok(None)
    } else {
        Ok(Some(argname.unwrap_or("ARG").to_string()))
    }
}

/// Build the switch string for an option, e.g. ``-F MSGFILE, --file=MSGFILE``.
///
/// `takes_value` is whether the
/// option consumes an argument (always true for a registry option), `argname`
/// its argument name (already the raw, un-uppercased name) and `short` its short
/// letter. The metavar is the upper-cased argname when a value is taken.
pub fn option_string(
    name: &str,
    short: Option<&str>,
    argname: Option<&str>,
    takes_value: bool,
) -> String {
    let metavar = if takes_value {
        argname.filter(|a| !a.is_empty()).map(|a| a.to_uppercase())
    } else {
        None
    };
    let mut parts = Vec::new();
    if let Some(short) = short {
        parts.push(match &metavar {
            Some(m) => format!("-{short} {m}"),
            None => format!("-{short}"),
        });
    }
    parts.push(match &metavar {
        Some(m) => format!("--{name}={m}"),
        None => format!("--{name}"),
    });
    parts.join(", ")
}

/// One switch of the options help: its option strings (e.g. ``-m ARG,
/// --message=ARG``) and its help, `None` for a hidden switch. A hidden switch
/// is not shown but, as in optparse, still counts towards the help column.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HelpEntry {
    /// The option strings.
    pub switches: String,
    /// The help, or `None` if the switch is hidden.
    pub help: Option<String>,
}

/// The width of the options help: ``COLUMNS`` minus two, or 78, as optparse
/// determines it.
pub fn help_width_from_env() -> i64 {
    std::env::var("COLUMNS")
        .ok()
        .and_then(|c| c.trim().parse::<i64>().ok())
        .unwrap_or(80)
        - 2
}

/// Assemble the options help, laid out as optparse's ``IndentedHelpFormatter``
/// does: the ungrouped switches, then each titled group, separated by blank
/// lines, with the help in one column across all of them. `width` is the
/// total width (see [`help_width_from_env`]).
pub fn format_option_help(
    main: &[HelpEntry],
    groups: &[(String, Vec<HelpEntry>)],
    width: i64,
) -> String {
    let len = |e: &HelpEntry| e.switches.chars().count() as i64;
    let max_len = main
        .iter()
        .map(|e| len(e) + 2)
        .chain(
            groups
                .iter()
                .flat_map(|(_, g)| g.iter().map(|e| len(e) + 4)),
        )
        .max()
        .unwrap_or(0);
    let max_help_position = 24.min((width - 20).max(4));
    let help_position = (max_len + 2).min(max_help_position);
    let help_width = (width - help_position).max(11) as usize;

    let mut parts = vec!["Options:\n".to_string()];
    if !main.is_empty() {
        parts.push(format_entries(main, 2, help_position, help_width));
        parts.push("\n".to_string());
    }
    for (title, entries) in groups {
        parts.push(format!(
            "  {title}:\n{}",
            format_entries(entries, 4, help_position, help_width)
        ));
        parts.push("\n".to_string());
    }
    // Drop the last separator, or the heading if there are no options.
    parts.pop();
    parts.concat()
}

/// Lay out `entries` at `indent`, with their help at `help_position` wrapped to
/// `help_width` columns.
fn format_entries(
    entries: &[HelpEntry],
    indent: i64,
    help_position: i64,
    help_width: usize,
) -> String {
    let pad = |n: i64| " ".repeat(n.max(0) as usize);
    let mut out = String::new();
    for entry in entries {
        let Some(help) = &entry.help else {
            continue;
        };
        let opt_width = help_position - indent - 2;
        let indent_first = if entry.switches.chars().count() as i64 > opt_width {
            out.push_str(&format!("{}{}\n", pad(indent), entry.switches));
            help_position
        } else {
            let fill = opt_width - entry.switches.chars().count() as i64;
            out.push_str(&format!("{}{}{}  ", pad(indent), entry.switches, pad(fill)));
            0
        };
        if help.is_empty() {
            if !out.ends_with('\n') {
                out.push('\n');
            }
            continue;
        }
        let lines = crate::utextwrap::wrap_like_python(help, help_width, true);
        let mut lines = lines.iter();
        if let Some(first) = lines.next() {
            out.push_str(&format!("{}{}\n", pad(indent_first), first));
        }
        for line in lines {
            out.push_str(&format!("{}{}\n", pad(help_position), line));
        }
    }
    out
}

/// The switch string for one registry value switch, e.g. ``-S, --short``, as
/// used by both the parser and the help grouping.
///
/// `names` is the value key followed by its non-hidden aliases; `short` is the
/// short value switch for the key, if any, which optparse renders first.
pub fn value_switch_string(names: &[String], short: Option<char>) -> String {
    let longs = names
        .iter()
        .map(|n| format!("--{n}"))
        .collect::<Vec<_>>()
        .join(", ");
    match short {
        Some(c) => format!("-{c}, {longs}"),
        None => longs,
    }
}

/// Parse a command line against `cmd`'s options.
///
/// Builds the option parser from the command's sorted options, prepends
/// `alias_argv`, parses, and returns the positional args plus the options dict
/// with the parser's `DEFAULT_VALUE` sentinels removed.
#[cfg(feature = "pyo3")]
pub fn parse_args<'py>(
    cmd: &pyo3::Bound<'py, pyo3::PyAny>,
    argv: Vec<String>,
    alias_argv: Option<Vec<String>>,
) -> pyo3::PyResult<(
    pyo3::Bound<'py, pyo3::PyAny>,
    pyo3::Bound<'py, pyo3::types::PyDict>,
)> {
    use pyo3::prelude::*;
    use pyo3::types::{PyDict, PyList};

    let py = cmd.py();
    let option = py.import("breezy.option")?;

    // Options in name order.
    let items = cmd.call_method0("options")?.call_method0("items")?;
    let sorted = py.import("builtins")?.call_method1("sorted", (items,))?;
    let values = PyList::empty(py);
    for pair in sorted.try_iter()? {
        values.append(pair?.get_item(1)?)?;
    }
    let parser = option.call_method1("get_optparser", (values,))?;

    let args = match alias_argv {
        Some(mut a) => {
            a.extend(argv);
            a
        }
        None => argv,
    };

    let parsed = parser.call_method1("parse_args", (args,))?;
    let (options, args): (Bound<'_, PyAny>, Bound<'_, PyAny>) = parsed.extract()?;

    // Leave out options that were not given.
    let default_value = option.getattr("OptionParser")?.getattr("DEFAULT_VALUE")?;
    let opts = PyDict::new(py);
    let option_dict = options.getattr("__dict__")?;
    for pair in option_dict.call_method0("items")?.try_iter()? {
        let pair = pair?;
        let v = pair.get_item(1)?;
        if !v.is(&default_value) {
            opts.set_item(pair.get_item(0)?, v)?;
        }
    }
    Ok((args, opts))
}

#[cfg(test)]
mod tests {
    fn entry(switches: &str, help: Option<&str>) -> HelpEntry {
        HelpEntry {
            switches: switches.to_string(),
            help: help.map(str::to_string),
        }
    }

    // The expected layouts below are what optparse produces for the same
    // options.

    #[test]
    fn format_option_help_groups() {
        let main = vec![
            entry("-v, --verbose", Some("Be verbose.")),
            entry("--no-verbose", None),
        ];
        let groups = vec![(
            "Log format".to_string(),
            vec![
                entry("--long", Some("Long.")),
                entry("-S, --short", Some("Short.")),
            ],
        )];
        assert_eq!(
            "Options:\n  -v, --verbose  Be verbose.\n\n  Log format:\n    --long       Long.\n    -S, --short  Short.\n",
            format_option_help(&main, &groups, 78)
        );
    }

    #[test]
    fn format_option_help_no_help() {
        assert_eq!(
            "Options:\n  --quiet  \n",
            format_option_help(&[entry("--quiet", Some(""))], &[], 78)
        );
    }

    #[test]
    fn format_option_help_long_switches() {
        assert_eq!(
            "Options:\n  --a-very-long-option-name=VALUE\n                        Help.\n",
            format_option_help(
                &[entry("--a-very-long-option-name=VALUE", Some("Help."))],
                &[],
                78
            )
        );
    }

    #[test]
    fn format_option_help_wraps() {
        assert_eq!(
            "Options:\n  --revision=ARG  See \"help revisionspec\" for details on how to specify\n                  revisions and ranges of revisions across multiple lines of\n                  wrapped text here.\n",
            format_option_help(
                &[entry(
                    "--revision=ARG",
                    Some(
                        "See \"help revisionspec\" for details on how to specify revisions \
                         and ranges of revisions across multiple lines of wrapped text here."
                    )
                )],
                &[],
                78
            )
        );
        assert_eq!(
            "Options:\n  --message=ARG  A message that is long enough\n                 to wrap.\n",
            format_option_help(
                &[entry(
                    "--message=ARG",
                    Some("A message that is long enough to wrap.")
                )],
                &[],
                48
            )
        );
    }

    #[test]
    fn format_option_help_empty() {
        assert_eq!("", format_option_help(&[], &[], 78));
    }

    #[test]
    fn value_switch_strings() {
        assert_eq!("--short", value_switch_string(&["short".to_string()], None));
        assert_eq!(
            "-S, --short",
            value_switch_string(&["short".to_string()], Some('S'))
        );
        // Aliases follow the key, in the order given.
        assert_eq!(
            "--short, --brief",
            value_switch_string(&["short".to_string(), "brief".to_string()], None)
        );
    }

    use super::*;

    #[test]
    fn split_revision_range_cases() {
        let split = |s: &str| split_revision_range(s);
        assert_eq!(split("234..567"), vec!["234", "567"]);
        assert_eq!(split(".."), vec!["", ""]);
        assert_eq!(split("..234"), vec!["", "234"]);
        assert_eq!(split("234.."), vec!["234", ""]);
        assert_eq!(split("234..456..789"), vec!["234", "456", "789"]);
        assert_eq!(split("234....789"), vec!["234", "", "789"]);
        // ".." followed by '/' or '\' is not a separator.
        assert_eq!(
            split("branch:../../branch2..23"),
            vec!["branch:../../branch2", "23"]
        );
        assert_eq!(split(r"branch:..\branch2"), vec![r"branch:..\branch2"]);
        // No separator: a single piece.
        assert_eq!(split("234"), vec!["234"]);
        assert_eq!(split(""), vec![""]);
    }

    #[test]
    fn negation_name_toggles() {
        assert_eq!(negation_name("commit"), "no-commit");
        assert_eq!(negation_name("no-commit"), "commit");
        assert_eq!(negation_name("no-"), "");
    }

    #[test]
    fn option_string_cases() {
        // Boolean option: just the long switch.
        assert_eq!(
            option_string("verbose", Some("v"), None, false),
            "-v, --verbose"
        );
        assert_eq!(
            option_string("no-recurse", None, None, false),
            "--no-recurse"
        );
        // Value option: metavar from the uppercased argname.
        assert_eq!(
            option_string("file", Some("F"), Some("msgfile"), true),
            "-F MSGFILE, --file=MSGFILE"
        );
        assert_eq!(
            option_string("revision", None, Some("ARG"), true),
            "--revision=ARG"
        );
    }

    #[test]
    fn bump_verbosity_cases() {
        // --no-verbose / --no-quiet reset to 0.
        assert_eq!(bump_verbosity(3, true, false), 0);
        assert_eq!(bump_verbosity(-2, false, false), 0);
        // -v from 0 -> 1, then accumulates.
        assert_eq!(bump_verbosity(0, true, true), 1);
        assert_eq!(bump_verbosity(1, true, true), 2);
        // -v from a quiet level jumps to 1 (not 0).
        assert_eq!(bump_verbosity(-1, true, true), 1);
        // -q from 0 -> -1, then accumulates.
        assert_eq!(bump_verbosity(0, false, true), -1);
        assert_eq!(bump_verbosity(-1, false, true), -2);
        // -q from a verbose level jumps to -1.
        assert_eq!(bump_verbosity(2, false, true), -1);
    }

    #[test]
    fn param_name_derivation() {
        assert_eq!(param_name("file-ids-from", None), "file_ids_from");
        assert_eq!(param_name("revision", None), "revision");
        assert_eq!(param_name("change", Some("revision")), "revision");
    }

    #[test]
    fn argname_rules() {
        // Boolean (no type): no argname.
        assert_eq!(resolve_argname(false, None), Ok(None));
        assert_eq!(
            resolve_argname(false, Some("X")),
            Err("argname not valid for booleans")
        );
        // Value option: defaults to ARG, or keeps the given name.
        assert_eq!(resolve_argname(true, None), Ok(Some("ARG".to_string())));
        assert_eq!(
            resolve_argname(true, Some("PATH")),
            Ok(Some("PATH".to_string()))
        );
    }
}
