//! Command infrastructure.
//!
//! This module defines the [`Command`] trait, the abstract interface that all
//! breezy commands implement. The existing Python `Command` base class (and its
//! ~150 subclasses across builtins and plugins) is grandfathered in through the
//! [`crate::pycommand::PyCommand`] wrapper, which implements this trait by
//! delegating to a Python command object. Native Rust commands implement the
//! trait directly.

/// Error raised while looking up or running a command.
///
/// At the Python boundary this maps to `breezy.errors.CommandError`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CommandError {
    /// A user-facing error message, already translated.
    User(String),
}

impl std::fmt::Display for CommandError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            CommandError::User(msg) => f.write_str(msg),
        }
    }
}

impl std::error::Error for CommandError {}

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
/// `None` for the empty-`*` case to match the Python behaviour exactly.
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
/// Python binding layer renders them through `breezy.i18n.gettext` so the
/// translated wording stays identical to the original Python implementation.
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

/// Match the supplied positional `args` against the `takes_args` specification.
///
/// This is a direct port of the Python ``_match_argform``. It returns the bound
/// arguments as an ordered list of (parameter-name, value) pairs, preserving the
/// declaration order of `takes_args`. The trailing character of each entry in
/// `takes_args` selects the matching behaviour:
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
        // Everything but the trailing specifier character, mirroring Python's
        // ``ap[:-1]``. For a plain argument (handled in the default branch)
        // this prefix is unused.
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
                // Capture all but the last argument; the Python code does
                // ``argdict[..] = args[:-1]; args[:-1] = []`` which leaves the
                // single last argument in ``args`` for a later spec (or the
                // trailing extra-argument check) to handle.
                let last_arg = args.pop().unwrap();
                let rest = std::mem::replace(&mut args, vec![last_arg]);
                argdict.push((format!("{argname}_list"), ArgValue::List(Some(rest))));
            }
            _ => {
                // Just a plain arg. Note the Python code rebinds argname to the
                // whole spec here (no trailing specifier to strip).
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
/// A port of the Python ``Command._usage``. It describes only the positional
/// arguments (not options): ``$``/``+`` become ``NAME...``, ``?`` becomes
/// ``[NAME]`` and ``*`` becomes ``[NAME...]``.
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
    // Remove the trailing space (matching Python's ``s[:-1]``).
    s.pop();
    s
}

/// Split command help text into a summary line and named sections.
///
/// A port of the Python ``Command._get_help_parts``. The first line is the
/// summary. A line of the form ``:xxx:`` starts a named section ``xxx``; the
/// default section (text outside any named section) is keyed with `None`.
/// Returns the summary plus the sections as an ordered list of
/// (label, body) pairs, in first-appearance order, with repeated labels merged
/// (their bodies joined with a newline) exactly as the Python implementation does.
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

    // ``text.rstrip().splitlines()`` then pop the first line as the summary.
    let trimmed = text.trim_end();
    let mut lines = trimmed.lines();
    let summary = lines.next().unwrap_or("").to_string();

    let mut label: Option<String> = None;
    let mut section = String::new();

    for line in lines {
        // Python uses ``len(line)`` (character count) and ``str.splitlines``;
        // help docstrings are ASCII/``\n``-delimited in practice, but count
        // characters here so a multi-byte single character matches Python.
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
/// edit distance, matching the Python ``guess_command`` heuristic.
///
/// The two names are compared character by character. Deletions, insertions and
/// replacements add to the distance; equal runs subtract a small amount so that
/// similarly-shaped names of equal length sort ahead of arbitrary ones.
fn guess_distance(cmd_name: &[char], candidate: &[char]) -> f64 {
    let mut matcher = patiencediff::SequenceMatcher::new(cmd_name, candidate);
    let mut distance = 0.0f64;
    for opcode in matcher.get_opcodes() {
        // Python unpacks (opcode, l1, l2, r1, r2): l = a-range (cmd_name),
        // r = b-range (candidate).
        let l1 = opcode.a_start() as i64;
        let l2 = opcode.a_end() as i64;
        let r1 = opcode.b_start() as i64;
        let r2 = opcode.b_end() as i64;
        match opcode {
            patiencediff::Opcode::Delete(..) => distance += (l2 - l1) as f64,
            // Note the second term is ``r2 - l1`` in the original Python; it is
            // reproduced verbatim rather than "corrected".
            patiencediff::Opcode::Replace(..) => distance += (l2 - l1).max(r2 - l1) as f64,
            patiencediff::Opcode::Insert(..) => distance += (r2 - r1) as f64,
            patiencediff::Opcode::Equal(..) => distance -= 0.1 * (l2 - l1) as f64,
        }
    }
    distance
}

/// Guess which command a user meant when `cmd_name` was not found.
///
/// A port of the Python ``guess_command`` scoring. `candidates` is the full set
/// of known command names and aliases (gathered by the caller, which needs the
/// registries). `overrides` are the hard-coded cost overrides for this
/// `cmd_name` (``_GUESS_OVERRIDES``); they replace or add costs before the
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
    // ``costs.update(_GUESS_OVERRIDES.get(cmd_name, {}))`` -- replace or add.
    for (key, value) in overrides {
        costs.insert(key.clone(), *value);
    }

    // ``sorted((costs[key], key) for key in costs)`` then take the first.
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

/// The abstract interface implemented by every breezy command.
///
/// Each method mirrors an attribute or method of the Python `Command` class.
/// Implementors that wrap a Python object (see [`crate::pycommand::PyCommand`])
/// delegate to it; native Rust commands provide the behaviour directly.
pub trait Command {
    /// The canonical command name (e.g. ``status``).
    fn name(&self) -> String;

    /// Alternative names the command is also known by (e.g. ``st``, ``stat``).
    fn aliases(&self) -> Vec<String>;

    /// The positional argument specification (e.g. ``["file*"]``).
    fn takes_args(&self) -> Vec<String>;

    /// Whether the command is hidden from the command list.
    fn hidden(&self) -> bool;

    /// Output encoding handling: ``"strict"``, ``"replace"`` or ``"exact"``.
    fn encoding_type(&self) -> String;

    /// The name the command was actually invoked as, if known.
    fn invoked_as(&self) -> Option<String>;

    /// The name of the plugin providing this command, or `None` if builtin.
    fn plugin_name(&self) -> Option<String>;

    /// The command's help text, or `None` if it has no docstring of its own.
    fn help(&self) -> Option<String>;
}

#[cfg(test)]
mod tests {
    use super::*;

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
        // newline, matching the Python implementation.
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
        // so it stays part of the default section, exactly as Python does.
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
        // smaller name wins, matching Python's ``sorted((cost, key))``.
        let candidates = specs(&["b", "a"]);
        assert_eq!(guess_command("z", &candidates, &[]), Some("a".to_string()));
    }
}
