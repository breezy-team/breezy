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
}
