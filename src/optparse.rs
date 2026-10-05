//! A command-line option parser.
//!
//! This module provides an option specification model and a tokenizer that
//! walks an argument vector, resolving each token against the spec into a
//! structured event. Type conversion, custom callbacks and registry validation
//! are left to the caller.
//!
//! It accepts the subset of Python's ``optparse`` syntax that breezy relies on:
//! ``--long`` and ``--long=value`` and ``--long value`` forms, clustered short
//! options (``-qq``), the ``--`` terminator, a bare ``-`` treated as a normal
//! argument, automatic ``--no-foo`` negations for boolean options, and
//! abbreviated long options.

/// The kind of value an option consumes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OptionKind {
    /// A boolean flag taking no argument (``--foo`` / ``--no-foo``).
    Flag,
    /// An option taking a single string argument (``--foo VALUE``).
    Value,
}

/// A single parseable option in the spec.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OptionSpec {
    /// A unique key identifying this option to the caller (e.g. the parameter
    /// name). Returned in events so the caller knows which option matched.
    pub key: String,
    /// The long name without the leading ``--`` (e.g. ``message``).
    pub long: String,
    /// The single-character short name, if any (without the leading ``-``).
    pub short: Option<char>,
    /// For boolean options, the negation long name (e.g. ``no-message``).
    pub negation: Option<String>,
    /// Whether the option takes an argument.
    pub kind: OptionKind,
}

/// A parsed option occurrence produced by the tokenizer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Token {
    /// A matched option. `value` is present for value options and for boolean
    /// options carries the boolean as ``"true"``/``"false"`` so the caller can
    /// distinguish the affirmative form from the negation.
    Option {
        /// The matched option's key.
        key: String,
        /// The option string as written by the user (e.g. ``--no-foo``, ``-v``),
        /// used for error messages and callbacks.
        opt_str: String,
        /// The argument for a value option; `None` for a flag.
        value: Option<String>,
        /// For a flag, whether this was the affirmative (`true`) or negation
        /// (`false`) form. Meaningless for value options (always `true`).
        flag_value: bool,
    },
    /// A positional (non-option) argument.
    Argument(String),
}

/// An error from option tokenizing, worded like ``optparse`` error messages.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OptionError {
    /// An unrecognised option was given. Carries the option string as written.
    NoSuchOption(String),
    /// A value option was given without its required argument.
    MissingArgument(String),
    /// A flag was given a value (``--flag=value``).
    TakesNoValue(String),
    /// An abbreviated long option matched more than one option.
    AmbiguousOption {
        /// The option string as written.
        opt_str: String,
        /// The matching long names.
        matches: Vec<String>,
    },
}

impl std::fmt::Display for OptionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            // These strings match optparse's wording (which breezy tests pin,
            // e.g. "no such option").
            OptionError::NoSuchOption(opt) => write!(f, "no such option: {opt}"),
            OptionError::MissingArgument(opt) => write!(f, "{opt} option requires an argument"),
            OptionError::TakesNoValue(opt) => write!(f, "{opt} option does not take a value"),
            OptionError::AmbiguousOption { opt_str, matches } => {
                let mut matches = matches.clone();
                matches.sort();
                write!(f, "ambiguous option: {opt_str} ({} ?)", matches.join(", "))
            }
        }
    }
}

impl std::error::Error for OptionError {}

/// The option spec: the set of options a parse recognises.
#[derive(Debug, Clone, Default)]
pub struct Spec {
    options: Vec<OptionSpec>,
}

impl Spec {
    /// Create an empty spec.
    pub fn new() -> Self {
        Spec {
            options: Vec::new(),
        }
    }

    /// Add an option to the spec.
    pub fn push(&mut self, option: OptionSpec) {
        self.options.push(option);
    }

    /// Build a spec from a list of options.
    pub fn from_options(options: Vec<OptionSpec>) -> Self {
        Spec { options }
    }

    /// Resolve a long option name (which may be an unambiguous abbreviation)
    /// against the spec, returning the matched option and whether it was the
    /// negation form.
    fn resolve_long(&self, name: &str) -> Result<(&OptionSpec, bool), OptionError> {
        // Exact match on the affirmative or negation long names first.
        for opt in &self.options {
            if opt.long == name {
                return Ok((opt, false));
            }
            if opt.negation.as_deref() == Some(name) {
                return Ok((opt, true));
            }
        }
        // Otherwise, an unambiguous prefix match, like optparse. Both the
        // affirmative and negation names participate in abbreviation.
        let mut matches: Vec<(&OptionSpec, bool, &str)> = Vec::new();
        for opt in &self.options {
            if opt.long.starts_with(name) {
                matches.push((opt, false, opt.long.as_str()));
            }
            if let Some(neg) = &opt.negation {
                if neg.starts_with(name) {
                    matches.push((opt, true, neg.as_str()));
                }
            }
        }
        match matches.len() {
            0 => Err(OptionError::NoSuchOption(format!("--{name}"))),
            1 => Ok((matches[0].0, matches[0].1)),
            _ => Err(OptionError::AmbiguousOption {
                opt_str: format!("--{name}"),
                matches: matches.iter().map(|m| format!("--{}", m.2)).collect(),
            }),
        }
    }

    /// Resolve a short option character against the spec.
    fn resolve_short(&self, c: char) -> Result<&OptionSpec, OptionError> {
        self.options
            .iter()
            .find(|opt| opt.short == Some(c))
            .ok_or_else(|| OptionError::NoSuchOption(format!("-{c}")))
    }
}

/// Tokenize `argv` against `spec`, producing the ordered list of option and
/// argument tokens.
///
/// Option processing stops after a ``--`` token; everything after it is an
/// argument. A bare ``-`` is treated as an argument. Clustered short options
/// (``-qv``) are expanded; a value short option consumes the rest of the
/// cluster or the next argument.
pub fn tokenize(spec: &Spec, argv: Vec<String>) -> Result<Vec<Token>, OptionError> {
    let mut tokens = Vec::new();
    let mut iter = argv.into_iter().peekable();
    let mut options_done = false;

    while let Some(arg) = iter.next() {
        if options_done {
            tokens.push(Token::Argument(arg));
            continue;
        }
        if arg == "--" {
            options_done = true;
            continue;
        }
        if arg == "-" || !arg.starts_with('-') {
            // A bare "-" or a non-option argument.
            tokens.push(Token::Argument(arg));
            continue;
        }
        if let Some(long) = arg.strip_prefix("--") {
            tokenize_long(spec, long, &mut iter, &mut tokens)?;
        } else {
            // A short option or cluster (arg starts with a single '-').
            let cluster: Vec<char> = arg[1..].chars().collect();
            tokenize_short(spec, &cluster, &mut iter, &mut tokens)?;
        }
    }
    Ok(tokens)
}

fn tokenize_long(
    spec: &Spec,
    long: &str,
    iter: &mut std::iter::Peekable<std::vec::IntoIter<String>>,
    tokens: &mut Vec<Token>,
) -> Result<(), OptionError> {
    // Split on the first '=' into name and inline value.
    let (name, inline_value) = match long.split_once('=') {
        Some((n, v)) => (n, Some(v.to_string())),
        None => (long, None),
    };
    let (opt, is_negation) = spec.resolve_long(name)?;
    let opt_str = format!("--{name}");
    match opt.kind {
        OptionKind::Flag => {
            if inline_value.is_some() {
                return Err(OptionError::TakesNoValue(opt_str));
            }
            tokens.push(Token::Option {
                key: opt.key.clone(),
                opt_str,
                value: None,
                flag_value: !is_negation,
            });
        }
        OptionKind::Value => {
            // ``--opt=value`` carries the value inline; ``--opt value`` consumes
            // the following argument.
            let value = match inline_value {
                Some(v) => v,
                None => iter
                    .next()
                    .ok_or_else(|| OptionError::MissingArgument(opt_str.clone()))?,
            };
            tokens.push(Token::Option {
                key: opt.key.clone(),
                opt_str,
                value: Some(value),
                flag_value: true,
            });
        }
    }
    Ok(())
}

fn tokenize_short(
    spec: &Spec,
    cluster: &[char],
    iter: &mut std::iter::Peekable<std::vec::IntoIter<String>>,
    tokens: &mut Vec<Token>,
) -> Result<(), OptionError> {
    let mut i = 0;
    while i < cluster.len() {
        let c = cluster[i];
        let opt = spec.resolve_short(c)?;
        let opt_str = format!("-{c}");
        match opt.kind {
            OptionKind::Flag => {
                tokens.push(Token::Option {
                    key: opt.key.clone(),
                    opt_str,
                    value: None,
                    flag_value: true,
                });
                i += 1;
            }
            OptionKind::Value => {
                // The value is the rest of the cluster, or the next argument.
                let rest: String = cluster[i + 1..].iter().collect();
                let value = if !rest.is_empty() {
                    rest
                } else {
                    iter.next()
                        .ok_or_else(|| OptionError::MissingArgument(opt_str.clone()))?
                };
                tokens.push(Token::Option {
                    key: opt.key.clone(),
                    opt_str,
                    value: Some(value),
                    flag_value: true,
                });
                return Ok(());
            }
        }
    }
    Ok(())
}

/// What a [`ParserOption`] takes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Shape {
    /// A boolean switch with a ``--no-name`` negation.
    Flag,
    /// One argument; the last one given wins.
    Value,
    /// Repeated arguments, collected into a list; ``-`` empties the list.
    List,
    /// One of a set of keys.
    Registry {
        /// Whether ``--name=KEY`` is accepted.
        enum_switch: bool,
        /// The ``--key`` switches, with their short switches.
        value_switches: Vec<(String, Option<char>)>,
    },
}

/// An option as the parser sees it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParserOption {
    /// The long name, without ``--``.
    pub name: String,
    /// The short name, if any.
    pub short: Option<char>,
    /// The parameter the value is stored as.
    pub param: String,
    /// What the option takes.
    pub shape: Shape,
}

/// How a value reached the parser.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Via {
    /// As the argument of a value or registry option (``--name=VALUE``).
    Argument,
    /// As an item of a list option.
    ListItem,
    /// As a registry option's ``--key`` switch.
    Switch,
    /// As a flag (``--name`` or ``--no-name``).
    Flag,
}

/// A parsed value.
#[derive(Debug, Clone, PartialEq)]
pub enum Parsed<V> {
    /// The value of a flag.
    Bool(bool),
    /// The value of a value or registry option.
    Value(V),
    /// The values of a list option.
    List(Vec<V>),
}

/// Converts the arguments of options and is told about every value set.
pub trait Handler {
    /// A converted value.
    type Value;
    /// The error of a conversion or notification.
    type Error;

    /// Convert `raw`, given for option `option` (an index into the options
    /// being parsed) as described by `via`.
    fn convert(&mut self, option: usize, raw: &str, via: Via) -> Result<Self::Value, Self::Error>;

    /// Told that option `option` set its parameter to `value`; for a list
    /// option, `value` is the whole list so far.
    fn set(
        &mut self,
        option: usize,
        value: &Parsed<Self::Value>,
        via: Via,
    ) -> Result<(), Self::Error>;
}

/// Why parsing failed.
#[derive(Debug, Clone, PartialEq)]
pub enum ParseError<E> {
    /// The command line does not fit the options.
    Option(OptionError),
    /// The handler failed.
    Handler(E),
}

/// The options parsed from a command line, by parameter, in the order the
/// parameters were first set.
#[derive(Debug, Clone, PartialEq)]
pub struct ParsedArgs<V> {
    /// The values given, and an empty list for each list option not given.
    pub values: Vec<(String, Parsed<V>)>,
    /// The positional arguments.
    pub args: Vec<String>,
}

impl<V> ParsedArgs<V> {
    fn slot(&mut self, param: &str) -> Option<&mut Parsed<V>> {
        self.values
            .iter_mut()
            .find(|(p, _)| p == param)
            .map(|(_, v)| v)
    }

    fn store(&mut self, param: &str, value: Parsed<V>) {
        match self.slot(param) {
            Some(slot) => *slot = value,
            None => self.values.push((param.to_string(), value)),
        }
    }
}

/// The tokenizer spec for `options`. Each spec key is the option's index,
/// followed for a value switch by a NUL and the key.
fn parser_spec(options: &[ParserOption]) -> Spec {
    let mut spec = Spec::new();
    for (i, option) in options.iter().enumerate() {
        let entry = |kind, negation| OptionSpec {
            key: i.to_string(),
            long: option.name.clone(),
            short: option.short,
            negation,
            kind,
        };
        match &option.shape {
            Shape::Flag => spec.push(entry(
                OptionKind::Flag,
                Some(crate::options::negation_name(&option.name)),
            )),
            Shape::Value | Shape::List => spec.push(entry(OptionKind::Value, None)),
            Shape::Registry {
                enum_switch,
                value_switches,
            } => {
                if *enum_switch {
                    spec.push(entry(OptionKind::Value, None));
                }
                for (key, short) in value_switches {
                    spec.push(OptionSpec {
                        key: format!("{i}\0{key}"),
                        long: key.clone(),
                        short: *short,
                        negation: None,
                        kind: OptionKind::Flag,
                    });
                }
            }
        }
    }
    spec
}

/// Parse `args` against `options`, converting arguments through `handler`.
///
/// A list option not given is an empty list; any other option not given is
/// absent from the result.
pub fn parse<H: Handler>(
    options: &[ParserOption],
    args: Vec<String>,
    handler: &mut H,
) -> Result<ParsedArgs<H::Value>, ParseError<H::Error>> {
    let tokens = tokenize(&parser_spec(options), args).map_err(ParseError::Option)?;
    let mut parsed = ParsedArgs {
        values: Vec::new(),
        args: Vec::new(),
    };
    for option in options {
        if option.shape == Shape::List && parsed.slot(&option.param).is_none() {
            parsed
                .values
                .push((option.param.clone(), Parsed::List(Vec::new())));
        }
    }
    for token in tokens {
        let (key, value, flag_value) = match token {
            Token::Argument(arg) => {
                parsed.args.push(arg);
                continue;
            }
            Token::Option {
                key,
                value,
                flag_value,
                ..
            } => (key, value, flag_value),
        };
        let (index, switch) = match key.split_once('\0') {
            Some((index, switch)) => (index, Some(switch.to_string())),
            None => (key.as_str(), None),
        };
        let index: usize = index.parse().expect("spec keys are option indices");
        let option = &options[index];
        let (new, via) = match (&option.shape, switch, value) {
            (Shape::Flag, _, _) => (Parsed::Bool(flag_value), Via::Flag),
            (Shape::List, _, Some(raw)) => {
                let mut items = match parsed.slot(&option.param) {
                    Some(Parsed::List(items)) => std::mem::take(items),
                    _ => Vec::new(),
                };
                if raw == "-" {
                    items.clear();
                } else {
                    items.push(
                        handler
                            .convert(index, &raw, Via::ListItem)
                            .map_err(ParseError::Handler)?,
                    );
                }
                (Parsed::List(items), Via::ListItem)
            }
            (_, Some(key), _) => (
                Parsed::Value(
                    handler
                        .convert(index, &key, Via::Switch)
                        .map_err(ParseError::Handler)?,
                ),
                Via::Switch,
            ),
            (_, None, Some(raw)) => (
                Parsed::Value(
                    handler
                        .convert(index, &raw, Via::Argument)
                        .map_err(ParseError::Handler)?,
                ),
                Via::Argument,
            ),
            (_, None, None) => unreachable!("value options always carry a value"),
        };
        handler.set(index, &new, via).map_err(ParseError::Handler)?;
        parsed.store(&option.param, new);
    }
    Ok(parsed)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn flag(key: &str, long: &str, short: Option<char>) -> OptionSpec {
        OptionSpec {
            key: key.to_string(),
            long: long.to_string(),
            short,
            negation: Some(format!("no-{long}")),
            kind: OptionKind::Flag,
        }
    }

    fn value(key: &str, long: &str, short: Option<char>) -> OptionSpec {
        OptionSpec {
            key: key.to_string(),
            long: long.to_string(),
            short,
            negation: None,
            kind: OptionKind::Value,
        }
    }

    fn argv(items: &[&str]) -> Vec<String> {
        items.iter().map(|s| s.to_string()).collect()
    }

    fn opt(key: &str, opt_str: &str, value: Option<&str>, flag_value: bool) -> Token {
        Token::Option {
            key: key.to_string(),
            opt_str: opt_str.to_string(),
            value: value.map(|s| s.to_string()),
            flag_value,
        }
    }

    fn arg(s: &str) -> Token {
        Token::Argument(s.to_string())
    }

    #[test]
    fn long_flag_and_negation() {
        let spec = Spec::from_options(vec![flag("hello", "hello", None)]);
        assert_eq!(
            tokenize(&spec, argv(&["--hello"])).unwrap(),
            vec![opt("hello", "--hello", None, true)]
        );
        assert_eq!(
            tokenize(&spec, argv(&["--no-hello"])).unwrap(),
            vec![opt("hello", "--no-hello", None, false)]
        );
    }

    #[test]
    fn long_value_both_forms() {
        let spec = Spec::from_options(vec![value("message", "message", Some('m'))]);
        assert_eq!(
            tokenize(&spec, argv(&["--message=biter"])).unwrap(),
            vec![opt("message", "--message", Some("biter"), true)]
        );
        assert_eq!(
            tokenize(&spec, argv(&["--message", "biter"])).unwrap(),
            vec![opt("message", "--message", Some("biter"), true)]
        );
    }

    #[test]
    fn missing_value_argument() {
        let spec = Spec::from_options(vec![value("number", "number", None)]);
        let err = tokenize(&spec, argv(&["--number"])).unwrap_err();
        assert_eq!(err, OptionError::MissingArgument("--number".to_string()));
    }

    #[test]
    fn no_such_option() {
        let spec = Spec::from_options(vec![value("number", "number", None)]);
        let err = tokenize(&spec, argv(&["--nope"])).unwrap_err();
        assert_eq!(err, OptionError::NoSuchOption("--nope".to_string()));
        // The negation of a value option does not exist.
        let err = tokenize(&spec, argv(&["--no-number"])).unwrap_err();
        assert_eq!(err, OptionError::NoSuchOption("--no-number".to_string()));
    }

    #[test]
    fn double_dash_terminates_options() {
        let spec = Spec::from_options(vec![flag("hello", "hello", None)]);
        assert_eq!(
            tokenize(&spec, argv(&["--", "-file-with-dashes"])).unwrap(),
            vec![arg("-file-with-dashes")]
        );
    }

    #[test]
    fn bare_dash_is_argument() {
        let spec = Spec::from_options(vec![flag("hello", "hello", None)]);
        assert_eq!(tokenize(&spec, argv(&["-"])).unwrap(), vec![arg("-")]);
    }

    #[test]
    fn short_clustering_flags() {
        let spec = Spec::from_options(vec![
            flag("verbose", "verbose", Some('v')),
            flag("quiet", "quiet", Some('q')),
        ]);
        assert_eq!(
            tokenize(&spec, argv(&["-qq"])).unwrap(),
            vec![
                opt("quiet", "-q", None, true),
                opt("quiet", "-q", None, true),
            ]
        );
        assert_eq!(
            tokenize(&spec, argv(&["-vq"])).unwrap(),
            vec![
                opt("verbose", "-v", None, true),
                opt("quiet", "-q", None, true),
            ]
        );
    }

    #[test]
    fn short_value_consumes_next_or_rest() {
        let spec = Spec::from_options(vec![value("hello", "hello", Some('h'))]);
        // Separate argument.
        assert_eq!(
            tokenize(&spec, argv(&["-h", "mars"])).unwrap(),
            vec![opt("hello", "-h", Some("mars"), true)]
        );
        // Attached to the cluster.
        assert_eq!(
            tokenize(&spec, argv(&["-hmars"])).unwrap(),
            vec![opt("hello", "-h", Some("mars"), true)]
        );
    }

    #[test]
    fn abbreviated_long_option() {
        let spec = Spec::from_options(vec![value("message", "message", None)]);
        assert_eq!(
            tokenize(&spec, argv(&["--mess", "hi"])).unwrap(),
            vec![opt("message", "--mess", Some("hi"), true)]
        );
    }

    #[test]
    fn ambiguous_abbreviation() {
        let spec = Spec::from_options(vec![
            value("mark", "mark", None),
            value("mast", "mast", None),
        ]);
        let err = tokenize(&spec, argv(&["--ma", "x"])).unwrap_err();
        match err {
            OptionError::AmbiguousOption { opt_str, .. } => assert_eq!(opt_str, "--ma"),
            other => panic!("expected ambiguous, got {other:?}"),
        }
    }

    #[test]
    fn arguments_interleaved() {
        let spec = Spec::from_options(vec![flag("hello", "hello", None)]);
        assert_eq!(
            tokenize(&spec, argv(&["a", "--hello", "b"])).unwrap(),
            vec![arg("a"), opt("hello", "--hello", None, true), arg("b")]
        );
    }

    /// Converts by upper-casing, refusing "bad", and records each set.
    #[derive(Default)]
    struct Upper {
        sets: Vec<(usize, Parsed<String>, Via)>,
    }

    impl Handler for Upper {
        type Value = String;
        type Error = String;

        fn convert(&mut self, _option: usize, raw: &str, _via: Via) -> Result<String, String> {
            if raw == "bad" {
                Err(format!("bad value {raw}"))
            } else {
                Ok(raw.to_uppercase())
            }
        }

        fn set(&mut self, option: usize, value: &Parsed<String>, via: Via) -> Result<(), String> {
            self.sets.push((option, value.clone(), via));
            Ok(())
        }
    }

    fn parser_options() -> Vec<ParserOption> {
        vec![
            ParserOption {
                name: "verbose".to_string(),
                short: Some('v'),
                param: "verbose".to_string(),
                shape: Shape::Flag,
            },
            ParserOption {
                name: "message".to_string(),
                short: Some('m'),
                param: "message".to_string(),
                shape: Shape::Value,
            },
            ParserOption {
                name: "exclude".to_string(),
                short: Some('x'),
                param: "exclude".to_string(),
                shape: Shape::List,
            },
            ParserOption {
                name: "format".to_string(),
                short: None,
                param: "format".to_string(),
                shape: Shape::Registry {
                    enum_switch: true,
                    value_switches: vec![
                        ("long".to_string(), None),
                        ("short".to_string(), Some('S')),
                    ],
                },
            },
        ]
    }

    #[test]
    fn parse_all_shapes() {
        let mut handler = Upper::default();
        let parsed = parse(
            &parser_options(),
            argv(&[
                "-v",
                "a",
                "--no-verbose",
                "-mhi",
                "-x",
                "p",
                "--exclude=q",
                "-S",
                "b",
            ]),
            &mut handler,
        )
        .unwrap();
        assert_eq!(vec!["a".to_string(), "b".to_string()], parsed.args);
        assert_eq!(
            vec![
                (
                    "exclude".to_string(),
                    Parsed::List(vec!["P".to_string(), "Q".to_string()])
                ),
                ("verbose".to_string(), Parsed::Bool(false)),
                ("message".to_string(), Parsed::Value("HI".to_string())),
                ("format".to_string(), Parsed::Value("SHORT".to_string())),
            ],
            parsed.values
        );
        assert_eq!(
            vec![
                (0, Parsed::Bool(true), Via::Flag),
                (0, Parsed::Bool(false), Via::Flag),
                (1, Parsed::Value("HI".to_string()), Via::Argument),
                (2, Parsed::List(vec!["P".to_string()]), Via::ListItem),
                (
                    2,
                    Parsed::List(vec!["P".to_string(), "Q".to_string()]),
                    Via::ListItem
                ),
                (3, Parsed::Value("SHORT".to_string()), Via::Switch),
            ],
            handler.sets
        );
    }

    #[test]
    fn parse_list_reset_and_default() {
        let parsed = parse(
            &parser_options(),
            argv(&["--exclude=a", "--exclude=-", "--exclude=b"]),
            &mut Upper::default(),
        )
        .unwrap();
        assert_eq!(
            vec![("exclude".to_string(), Parsed::List(vec!["B".to_string()]))],
            parsed.values
        );
        let parsed = parse(&parser_options(), argv(&[]), &mut Upper::default()).unwrap();
        assert_eq!(
            vec![("exclude".to_string(), Parsed::List(Vec::new()))],
            parsed.values
        );
    }

    #[test]
    fn parse_registry_enum_switch() {
        let parsed = parse(
            &parser_options(),
            argv(&["--format=long"]),
            &mut Upper::default(),
        )
        .unwrap();
        assert_eq!(
            Some(&Parsed::Value("LONG".to_string())),
            parsed
                .values
                .iter()
                .find(|(p, _)| p == "format")
                .map(|(_, v)| v)
        );
    }

    #[test]
    fn parse_errors() {
        assert_eq!(
            Err(ParseError::Handler("bad value bad".to_string())),
            parse(
                &parser_options(),
                argv(&["-m", "bad"]),
                &mut Upper::default()
            )
        );
        assert_eq!(
            Err(ParseError::Option(OptionError::NoSuchOption(
                "--bogus".to_string()
            ))),
            parse(&parser_options(), argv(&["--bogus"]), &mut Upper::default())
        );
    }

    #[test]
    fn flag_with_value() {
        let spec = Spec::from_options(vec![flag("verbose", "verbose", Some('v'))]);
        let err = tokenize(&spec, argv(&["--verbose=yes"])).unwrap_err();
        assert_eq!(OptionError::TakesNoValue("--verbose".to_string()), err);
        assert_eq!("--verbose option does not take a value", err.to_string());
    }
}
