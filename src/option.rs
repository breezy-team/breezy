//! Command-line option definitions and parsed option values.
//!
//! An [`OptionDef`] describes an option: its switches, help and what kind of
//! value it takes. A command lists its options as [`OptionRef`]s, either
//! defined by the command itself or naming one of the [`shared_options`] that
//! many commands use (``--revision``, ``--message``, ...). The parsed values
//! reach the command as [`ParsedOptions`].

use std::collections::HashMap;

/// How the argument of a value option is turned into a value.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ValueKind {
    /// A string.
    Str,
    /// An integer.
    Int,
    /// A floating point number.
    Float,
    /// A revision or a range of revisions (``-r 3``, ``-r 3..5``).
    RevisionRange,
    /// A single revision, standing for the change it introduced (``-c 3``).
    /// Its value is the range from the revision before it to the revision.
    Change,
}

/// A registry the choices of a registry option come from.
///
/// The registry is looked up when it is used, so that entries registered by
/// plugins are offered.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RegistryRef {
    /// The Python module holding the registry.
    pub module: String,
    /// The name of the registry in that module.
    pub attribute: String,
}

/// One choice of a registry option with a fixed set of choices.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Choice {
    /// The value, also the name of its ``--key`` switch.
    pub key: String,
    /// The help for the choice.
    pub help: String,
}

/// Where the choices of a registry option come from.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Choices {
    /// A fixed set of choices.
    Fixed(Vec<Choice>),
    /// The entries of a registry.
    Registry(RegistryRef),
}

/// What an option takes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OptionKind {
    /// A boolean switch; ``--no-name`` turns it off again.
    Flag,
    /// An option taking one argument; the last one given wins.
    Value(ValueKind),
    /// An option that can be given repeatedly, collecting its arguments.
    /// ``--name=-`` empties the list.
    List(ValueKind),
    /// An option whose value is one of a set of choices.
    Registry {
        /// The choices.
        choices: Choices,
        /// Whether each choice has its own ``--key`` switch.
        value_switches: bool,
        /// Whether ``--name=KEY`` is accepted.
        enum_switch: bool,
        /// The title the value switches are listed under in the help; the
        /// option name if `None`.
        title: Option<String>,
        /// Short switches for some of the choices, e.g. ``-S`` for ``short``.
        short_value_switches: Vec<(String, char)>,
    },
}

/// The definition of a command-line option.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OptionDef {
    /// The long name, without ``--``.
    pub name: String,
    /// The single-character short name, if any.
    pub short: Option<char>,
    /// The help text.
    pub help: String,
    /// The parameter the value is passed as, if not the option name with ``-``
    /// replaced by ``_``.
    pub param_name: Option<String>,
    /// The name of the argument shown in the help (``ARG`` by default).
    pub argname: Option<String>,
    /// Whether the option is left out of the help.
    pub hidden: bool,
    /// What the option takes.
    pub kind: OptionKind,
}

impl OptionDef {
    fn new(name: &str, help: &str, kind: OptionKind) -> Self {
        OptionDef {
            name: name.to_string(),
            short: None,
            help: help.to_string(),
            param_name: None,
            argname: None,
            hidden: false,
            kind,
        }
    }

    /// A boolean switch.
    pub fn flag(name: &str, help: &str) -> Self {
        Self::new(name, help, OptionKind::Flag)
    }

    /// An option taking one argument of the given kind.
    pub fn value(name: &str, kind: ValueKind, help: &str) -> Self {
        Self::new(name, help, OptionKind::Value(kind))
    }

    /// An option collecting the arguments of each use.
    pub fn list(name: &str, kind: ValueKind, help: &str) -> Self {
        Self::new(name, help, OptionKind::List(kind))
    }

    /// An option choosing one of `choices`, with a ``--key`` switch for each
    /// choice listed under `title`, and ``--name=KEY``.
    pub fn registry(name: &str, choices: Choices, title: &str, help: &str) -> Self {
        Self::new(
            name,
            help,
            OptionKind::Registry {
                choices,
                value_switches: true,
                enum_switch: true,
                title: Some(title.to_string()),
                short_value_switches: Vec::new(),
            },
        )
    }

    /// Set the short name.
    pub fn short(mut self, short: char) -> Self {
        self.short = Some(short);
        self
    }

    /// Pass the value as `param_name` rather than as the option name.
    pub fn param_name(mut self, param_name: &str) -> Self {
        self.param_name = Some(param_name.to_string());
        self
    }

    /// Set the argument name shown in the help.
    pub fn argname(mut self, argname: &str) -> Self {
        self.argname = Some(argname.to_string());
        self
    }

    /// Leave the option out of the help.
    pub fn hidden(mut self) -> Self {
        self.hidden = true;
        self
    }

    /// Give choice `key` of a registry option the short switch `short`.
    ///
    /// # Panics
    ///
    /// If the option is not a registry option.
    pub fn short_value_switch(mut self, key: &str, short: char) -> Self {
        match &mut self.kind {
            OptionKind::Registry {
                short_value_switches,
                ..
            } => short_value_switches.push((key.to_string(), short)),
            _ => panic!("{} is not a registry option", self.name),
        }
        self
    }

    /// The parameter the value is passed as.
    pub fn param(&self) -> String {
        crate::options::param_name(&self.name, self.param_name.as_deref())
    }
}

/// An option of a command: its own, or one of the [`shared_options`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OptionRef {
    /// An option defined by the command.
    Own(OptionDef),
    /// The shared option with this name.
    Shared(String),
}

impl OptionRef {
    /// The shared option `name`.
    pub fn shared(name: &str) -> Self {
        OptionRef::Shared(name.to_string())
    }

    /// The definition of the option.
    pub fn resolve(&self) -> Result<OptionDef, UnknownOption> {
        match self {
            OptionRef::Own(def) => Ok(def.clone()),
            OptionRef::Shared(name) => {
                shared_option(name).ok_or_else(|| UnknownOption(name.clone()))
            }
        }
    }
}

impl From<OptionDef> for OptionRef {
    fn from(def: OptionDef) -> Self {
        OptionRef::Own(def)
    }
}

/// A reference to a shared option that does not exist.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UnknownOption(pub String);

impl std::fmt::Display for UnknownOption {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "no shared option named {:?}", self.0)
    }
}

impl std::error::Error for UnknownOption {}

/// The options shared between commands (``Option.OPTIONS``).
pub fn shared_options() -> Vec<OptionDef> {
    let lazy = |module: &str, attribute: &str| {
        Choices::Registry(RegistryRef {
            module: module.to_string(),
            attribute: attribute.to_string(),
        })
    };
    vec![
        OptionDef::value(
            "change",
            ValueKind::Change,
            "Select changes introduced by the specified revision. See also \"help revisionspec\".",
        )
        .short('c')
        .param_name("revision"),
        OptionDef::value(
            "directory",
            ValueKind::Str,
            "Branch to operate on, instead of working directory.",
        )
        .short('d'),
        OptionDef::value("file", ValueKind::Str, "").short('F'),
        OptionDef::registry(
            "log-format",
            lazy("breezy.log", "log_formatter_registry"),
            "Log format",
            "Use specified log format.",
        )
        .short_value_switch("short", 'S'),
        OptionDef::registry(
            "merge-type",
            lazy("breezy.merge", "merge_type_registry"),
            "Merge algorithm",
            "Select a particular merge algorithm.",
        ),
        OptionDef::value("message", ValueKind::Str, "Message string.").short('m'),
        OptionDef::flag(
            "null",
            "Use an ASCII NUL (\\0) separator rather than a newline.",
        )
        .short('0'),
        OptionDef::flag(
            "overwrite",
            "Ignore differences between branches and overwrite unconditionally.",
        ),
        OptionDef::flag("remember", "Remember the specified location as a default."),
        OptionDef::flag("reprocess", "Reprocess to reduce spurious conflicts."),
        OptionDef::value(
            "revision",
            ValueKind::RevisionRange,
            "See \"help revisionspec\" for details.",
        )
        .short('r'),
        OptionDef::flag("show-ids", "Show internal object ids."),
        OptionDef::value(
            "timezone",
            ValueKind::Str,
            "Display timezone as local, original, or utc.",
        ),
    ]
}

/// The shared option `name`, if there is one.
pub fn shared_option(name: &str) -> Option<OptionDef> {
    shared_options().into_iter().find(|o| o.name == name)
}

/// A parsed option value.
#[derive(Debug, Clone, PartialEq)]
pub enum OptionValue {
    /// The value of a flag.
    Bool(bool),
    /// A string.
    Str(String),
    /// An integer.
    Int(i64),
    /// A floating point number.
    Float(f64),
    /// Revision specifiers, one per end of a range; `None` for an open end
    /// (as in ``..5``).
    Revisions(Vec<Option<String>>),
    /// The chosen key of a registry option.
    Key(String),
    /// The values of a list option.
    List(Vec<OptionValue>),
}

/// The options given to a command, keyed by parameter name (see
/// [`OptionDef::param`]).
#[derive(Debug, Default, Clone, PartialEq)]
pub struct ParsedOptions {
    values: HashMap<String, OptionValue>,
}

impl ParsedOptions {
    /// Record `value` for parameter `param`.
    pub fn set(&mut self, param: &str, value: OptionValue) {
        self.values.insert(param.to_string(), value);
    }

    /// The value given for parameter `param`, if any.
    pub fn get(&self, param: &str) -> Option<&OptionValue> {
        self.values.get(param)
    }

    /// Whether flag `param` was turned on.
    pub fn flag(&self, param: &str) -> bool {
        matches!(self.get(param), Some(OptionValue::Bool(true)))
    }

    /// The string given for `param`.
    pub fn str(&self, param: &str) -> Option<&str> {
        match self.get(param) {
            Some(OptionValue::Str(s)) => Some(s),
            _ => None,
        }
    }

    /// The integer given for `param`.
    pub fn int(&self, param: &str) -> Option<i64> {
        match self.get(param) {
            Some(OptionValue::Int(i)) => Some(*i),
            _ => None,
        }
    }

    /// The number given for `param`.
    pub fn float(&self, param: &str) -> Option<f64> {
        match self.get(param) {
            Some(OptionValue::Float(f)) => Some(*f),
            _ => None,
        }
    }

    /// The revision specifiers given for `param`.
    pub fn revisions(&self, param: &str) -> Option<&[Option<String>]> {
        match self.get(param) {
            Some(OptionValue::Revisions(r)) => Some(r),
            _ => None,
        }
    }

    /// The registry key chosen for `param`.
    pub fn key(&self, param: &str) -> Option<&str> {
        match self.get(param) {
            Some(OptionValue::Key(k)) => Some(k),
            _ => None,
        }
    }

    /// The values of list option `param`; empty if it was not given.
    pub fn list(&self, param: &str) -> &[OptionValue] {
        match self.get(param) {
            Some(OptionValue::List(v)) => v,
            _ => &[],
        }
    }

    /// The strings of a list option of strings; empty if it was not given.
    pub fn str_list(&self, param: &str) -> Vec<&str> {
        self.list(param)
            .iter()
            .filter_map(|v| match v {
                OptionValue::Str(s) => Some(s.as_str()),
                _ => None,
            })
            .collect()
    }
}

/// A keyword argument a command's Python ``run`` was called with, before it is
/// matched to an option or a positional parameter.
#[derive(Debug, Clone, PartialEq)]
pub enum KwValue {
    /// ``None``: not given.
    None,
    /// A boolean.
    Bool(bool),
    /// An integer.
    Int(i64),
    /// A float.
    Float(f64),
    /// A string.
    Str(String),
    /// A list or tuple.
    Seq(Vec<KwValue>),
    /// A revision specifier object, by the string it was parsed from; `None`
    /// for an open end of a range.
    RevisionSpec(Option<String>),
}

/// Why the keyword arguments for a command's ``run`` were rejected.
#[derive(Debug, Clone, PartialEq)]
pub enum KwargsError {
    /// The keyword is neither an option nor a positional parameter.
    Unexpected {
        /// The command name.
        command: String,
        /// The keyword.
        key: String,
    },
    /// The value does not have the type the option or parameter takes.
    WrongType {
        /// The command name.
        command: String,
        /// The keyword.
        key: String,
        /// The value that was passed.
        value: KwValue,
    },
}

impl std::fmt::Display for KwargsError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            KwargsError::Unexpected { command, key } => {
                write!(
                    f,
                    "command '{command}' got an unexpected keyword argument '{key}'"
                )
            }
            KwargsError::WrongType {
                command,
                key,
                value,
            } => write!(
                f,
                "command '{command}' got an invalid value for '{key}': {value:?}"
            ),
        }
    }
}

impl std::error::Error for KwargsError {}

/// Convert `value` to the value of an option of `kind`, or `None` if it does
/// not fit.
fn option_value(kind: &OptionKind, value: KwValue) -> Option<OptionValue> {
    match kind {
        OptionKind::Flag => match value {
            KwValue::Bool(b) => Some(OptionValue::Bool(b)),
            _ => None,
        },
        OptionKind::Value(kind) => scalar_value(*kind, value),
        OptionKind::List(kind) => match value {
            KwValue::Seq(items) => items
                .into_iter()
                .map(|item| scalar_value(*kind, item))
                .collect::<Option<Vec<_>>>()
                .map(OptionValue::List),
            _ => None,
        },
        OptionKind::Registry { .. } => match value {
            KwValue::Str(key) => Some(OptionValue::Key(key)),
            _ => None,
        },
    }
}

fn scalar_value(kind: ValueKind, value: KwValue) -> Option<OptionValue> {
    match (kind, value) {
        (ValueKind::Str, KwValue::Str(s)) => Some(OptionValue::Str(s)),
        (ValueKind::Int, KwValue::Int(i)) => Some(OptionValue::Int(i)),
        (ValueKind::Float, KwValue::Float(f)) => Some(OptionValue::Float(f)),
        (ValueKind::Float, KwValue::Int(i)) => Some(OptionValue::Float(i as f64)),
        (ValueKind::RevisionRange | ValueKind::Change, KwValue::Seq(items)) => items
            .into_iter()
            .map(|item| match item {
                KwValue::RevisionSpec(spec) => Some(spec),
                _ => None,
            })
            .collect::<Option<Vec<_>>>()
            .map(OptionValue::Revisions),
        _ => None,
    }
}

/// Sort the keyword arguments a command's ``run`` was called with into its
/// options and its positional parameters (named as by
/// [`crate::command::argform_param`]).
///
/// A ``None`` value means the option was not given. Two options may share a
/// parameter (``--change`` and ``--revision`` both set ``revision``); the
/// first definition whose kind fits the value is used.
pub fn parse_kwargs(
    command: &str,
    options: &[OptionDef],
    takes_args: &[String],
    kwargs: Vec<(String, KwValue)>,
) -> Result<(ParsedOptions, crate::command::MatchedArgs), KwargsError> {
    use crate::command::ArgValue;

    let mut opts = ParsedOptions::default();
    let mut args = crate::command::MatchedArgs::default();
    let params: Vec<String> = takes_args
        .iter()
        .map(|spec| crate::command::argform_param(spec))
        .collect();
    for (key, value) in kwargs {
        let wrong_type = |key: String, value: KwValue| KwargsError::WrongType {
            command: command.to_string(),
            key,
            value,
        };
        let defs: Vec<&OptionDef> = options.iter().filter(|o| o.param() == key).collect();
        if !defs.is_empty() {
            if value == KwValue::None {
                continue;
            }
            match defs
                .iter()
                .find_map(|def| option_value(&def.kind, value.clone()))
            {
                Some(v) => opts.set(&key, v),
                None => return Err(wrong_type(key, value)),
            }
        } else if params.contains(&key) {
            let list_param = key.ends_with("_list");
            match (list_param, value) {
                (true, KwValue::None) => args.set(key, ArgValue::List(None)),
                (true, KwValue::Seq(items)) => {
                    let strings = items
                        .iter()
                        .map(|item| match item {
                            KwValue::Str(s) => Some(s.clone()),
                            _ => None,
                        })
                        .collect::<Option<Vec<_>>>();
                    match strings {
                        Some(v) => args.set(key, ArgValue::List(Some(v))),
                        None => return Err(wrong_type(key, KwValue::Seq(items))),
                    }
                }
                (false, KwValue::Str(v)) => args.set(key, ArgValue::Scalar(v)),
                (_, value) => return Err(wrong_type(key, value)),
            }
        } else {
            return Err(KwargsError::Unexpected {
                command: command.to_string(),
                key,
            });
        }
    }
    Ok((opts, args))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn options() -> Vec<OptionDef> {
        vec![
            OptionDef::flag("dry-run", "Do nothing."),
            OptionDef::value("message", ValueKind::Str, "Message.").short('m'),
            OptionDef::value("limit", ValueKind::Int, "Limit.").short('l'),
            OptionDef::value("ratio", ValueKind::Float, "Ratio."),
            OptionDef::list("exclude", ValueKind::Str, "Exclude.").short('x'),
            OptionDef::registry(
                "format",
                Choices::Fixed(vec![Choice {
                    key: "short".to_string(),
                    help: "Short.".to_string(),
                }]),
                "Format",
                "Format.",
            ),
            shared_option("revision").unwrap(),
            shared_option("change").unwrap(),
        ]
    }

    fn takes_args() -> Vec<String> {
        vec!["location?".to_string(), "file*".to_string()]
    }

    fn parse(
        kwargs: Vec<(&str, KwValue)>,
    ) -> Result<(ParsedOptions, crate::command::MatchedArgs), KwargsError> {
        parse_kwargs(
            "probe",
            &options(),
            &takes_args(),
            kwargs
                .into_iter()
                .map(|(k, v)| (k.to_string(), v))
                .collect(),
        )
    }

    fn spec(s: &str) -> KwValue {
        KwValue::RevisionSpec(Some(s.to_string()))
    }

    #[test]
    fn options_by_kind() {
        let (opts, _) = parse(vec![
            ("dry_run", KwValue::Bool(true)),
            ("message", KwValue::Str("hi".to_string())),
            ("limit", KwValue::Int(3)),
            ("ratio", KwValue::Float(0.5)),
            (
                "exclude",
                KwValue::Seq(vec![
                    KwValue::Str("a".to_string()),
                    KwValue::Str("b".to_string()),
                ]),
            ),
            ("format", KwValue::Str("short".to_string())),
            (
                "revision",
                KwValue::Seq(vec![spec("3"), KwValue::RevisionSpec(None)]),
            ),
        ])
        .unwrap();
        assert!(opts.flag("dry_run"));
        assert_eq!(Some("hi"), opts.str("message"));
        assert_eq!(Some(3), opts.int("limit"));
        assert_eq!(Some(0.5), opts.float("ratio"));
        assert_eq!(vec!["a", "b"], opts.str_list("exclude"));
        assert_eq!(Some("short"), opts.key("format"));
        assert_eq!(
            Some(&[Some("3".to_string()), None][..]),
            opts.revisions("revision")
        );
    }

    #[test]
    fn options_not_given() {
        let (opts, _) = parse(vec![
            ("dry_run", KwValue::Bool(false)),
            ("message", KwValue::None),
            ("limit", KwValue::None),
        ])
        .unwrap();
        assert!(!opts.flag("dry_run"));
        assert_eq!(None, opts.str("message"));
        assert_eq!(None, opts.int("limit"));
        assert!(opts.list("exclude").is_empty());
    }

    #[test]
    fn int_for_float_option() {
        let (opts, _) = parse(vec![("ratio", KwValue::Int(2))]).unwrap();
        assert_eq!(Some(2.0), opts.float("ratio"));
    }

    #[test]
    fn change_shares_the_revision_parameter() {
        let (opts, _) = parse(vec![(
            "revision",
            KwValue::Seq(vec![spec("before:3"), spec("3")]),
        )])
        .unwrap();
        assert_eq!(
            Some(&[Some("before:3".to_string()), Some("3".to_string())][..]),
            opts.revisions("revision")
        );
    }

    #[test]
    fn positional_parameters() {
        let (_, args) = parse(vec![
            ("location", KwValue::Str("there".to_string())),
            (
                "file_list",
                KwValue::Seq(vec![KwValue::Str("x".to_string())]),
            ),
        ])
        .unwrap();
        assert_eq!(Some("there"), args.scalar("location"));
        assert_eq!(vec!["x".to_string()], args.list("file_list"));

        let (_, args) = parse(vec![("file_list", KwValue::None)]).unwrap();
        assert_eq!(None, args.scalar("location"));
        assert!(args.list("file_list").is_empty());
    }

    #[test]
    fn unexpected_keyword() {
        let err = parse(vec![("bogus", KwValue::Bool(true))]).unwrap_err();
        assert_eq!(
            "command 'probe' got an unexpected keyword argument 'bogus'",
            err.to_string()
        );
    }

    #[test]
    fn wrong_type() {
        assert_eq!(
            KwargsError::WrongType {
                command: "probe".to_string(),
                key: "limit".to_string(),
                value: KwValue::Str("3".to_string()),
            },
            parse(vec![("limit", KwValue::Str("3".to_string()))]).unwrap_err()
        );
        assert!(parse(vec![("location", KwValue::Seq(Vec::new()))]).is_err());
        assert!(parse(vec![("dry_run", KwValue::Str("yes".to_string()))]).is_err());
        assert!(parse(vec![(
            "revision",
            KwValue::Seq(vec![KwValue::Str("3".to_string())])
        )])
        .is_err());
    }

    #[test]
    fn shared_options_resolve() {
        let def = OptionRef::shared("change").resolve().unwrap();
        assert_eq!(Some('c'), def.short);
        assert_eq!("revision", def.param());
        assert_eq!(OptionKind::Value(ValueKind::Change), def.kind);
        assert_eq!(
            Err(UnknownOption("bogus".to_string())),
            OptionRef::shared("bogus").resolve()
        );
    }

    #[test]
    fn shared_option_names_are_unique() {
        let mut names: Vec<String> = shared_options().into_iter().map(|o| o.name).collect();
        let count = names.len();
        names.sort();
        names.dedup();
        assert_eq!(count, names.len());
    }
}
