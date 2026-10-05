//! Command registries.
//!
//! Commands implemented in Rust register themselves with [`declare_command!`];
//! [`command_registry`] collects them. A [`CommandTable`] maps the names of all
//! commands, native or not, to how each is provided.

use std::collections::{BTreeMap, HashMap};

use crate::command::{Command, CommandSpec};

/// A registered command together with its description.
pub struct Entry {
    /// The command's description, read once at registration.
    pub spec: CommandSpec,
    /// The command itself.
    pub command: Box<dyn Command>,
}

/// The native commands, looked up by name or alias.
#[derive(Default)]
pub struct Registry {
    entries: Vec<Entry>,
}

impl Registry {
    /// An empty registry.
    pub fn new() -> Self {
        Registry::default()
    }

    /// Register a command.
    pub fn register(&mut self, command: Box<dyn Command>) {
        self.entries.push(Entry {
            spec: command.spec(),
            command,
        });
    }

    /// Find the command registered under `name` or one of its aliases.
    pub fn get(&self, name: &str) -> Option<&Entry> {
        self.entries
            .iter()
            .find(|e| e.spec.name == name || e.spec.aliases.iter().any(|a| a == name))
    }

    /// The registered commands, in registration order.
    pub fn entries(&self) -> &[Entry] {
        &self.entries
    }

    /// The number of registered commands.
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    /// Whether the registry has no commands.
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}

/// A native command's registration, collected by the [`inventory`] crate.
///
/// Each native command submits one of these (via [`declare_command!`]) at its
/// definition site; [`command_registry`] gathers them all. `factory` builds a
/// fresh boxed command, so the registry owns its entries.
pub struct CommandRegistration {
    /// Builds a boxed instance of the command.
    pub factory: fn() -> Box<dyn Command>,
}

inventory::collect!(CommandRegistration);

/// Register a native command so [`command_registry`] picks it up.
///
/// The argument is a command type implementing [`Command`] and `Default`.
/// Place the invocation next to the command's definition:
///
/// ```ignore
/// declare_command!(CmdRocks);
/// ```
#[macro_export]
macro_rules! declare_command {
    ($cmd:ty) => {
        $crate::__inventory::submit! {
            $crate::registry::CommandRegistration {
                factory: || ::std::boxed::Box::new(<$cmd>::default()) as ::std::boxed::Box<dyn $crate::command::Command>,
            }
        }
    };
}

/// The registry of native commands, built on first use from every
/// [`declare_command!`] registration.
pub fn command_registry() -> &'static Registry {
    static REGISTRY: std::sync::OnceLock<Registry> = std::sync::OnceLock::new();
    REGISTRY.get_or_init(|| {
        let mut reg = Registry::new();
        for registration in inventory::iter::<CommandRegistration>() {
            reg.register((registration.factory)());
        }
        reg
    })
}

/// How a command in a [`CommandTable`] is provided.
pub enum Provider<P> {
    /// A command implemented in Rust.
    Native(&'static Entry),
    /// A command object supplied by the host language (a Python class).
    Object(P),
    /// A command in a module that is only imported when the command is used.
    Lazy {
        /// The module defining the command.
        module: String,
        /// The name of the command in that module.
        member: String,
    },
}

/// A command registered in a [`CommandTable`].
pub struct Registration<P> {
    /// The command name.
    pub name: String,
    /// The names the command can also be invoked as.
    pub aliases: Vec<String>,
    /// How the command is provided.
    pub provider: Provider<P>,
}

/// A command name that is already registered.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AlreadyRegistered(pub String);

impl std::fmt::Display for AlreadyRegistered {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Key '{}' already registered", self.0)
    }
}

impl std::error::Error for AlreadyRegistered {}

/// Commands by name, with their aliases.
pub struct CommandTable<P> {
    entries: BTreeMap<String, Registration<P>>,
    aliases: HashMap<String, String>,
}

impl<P> Default for CommandTable<P> {
    fn default() -> Self {
        CommandTable {
            entries: BTreeMap::new(),
            aliases: HashMap::new(),
        }
    }
}

impl<P> CommandTable<P> {
    /// An empty table.
    pub fn new() -> Self {
        Self::default()
    }

    /// Register a command, replacing one registered under the same name only
    /// if `replace` is set. Returns the replaced registration.
    pub fn insert(
        &mut self,
        registration: Registration<P>,
        replace: bool,
    ) -> Result<Option<Registration<P>>, AlreadyRegistered> {
        if !replace && self.entries.contains_key(&registration.name) {
            return Err(AlreadyRegistered(registration.name));
        }
        for alias in &registration.aliases {
            self.aliases
                .insert(alias.clone(), registration.name.clone());
        }
        Ok(self.entries.insert(registration.name.clone(), registration))
    }

    /// The name `name` refers to: the command it is an alias of, or itself.
    pub fn resolve<'a>(&'a self, name: &'a str) -> &'a str {
        self.aliases.get(name).map_or(name, String::as_str)
    }

    /// The command registered under `name` or as an alias `name`.
    pub fn get(&self, name: &str) -> Option<&Registration<P>> {
        self.entries.get(self.resolve(name))
    }

    /// Mutable access to the command registered under `name` or as an alias
    /// `name`.
    pub fn get_mut(&mut self, name: &str) -> Option<&mut Registration<P>> {
        let name = self.resolve(name).to_string();
        self.entries.get_mut(&name)
    }

    /// Remove the command registered under `name`, and the aliases referring to
    /// it.
    pub fn remove(&mut self, name: &str) -> Option<Registration<P>> {
        let removed = self.entries.remove(name)?;
        self.aliases.retain(|_, target| target != name);
        Some(removed)
    }

    /// Whether a command is registered under `name` (not an alias).
    pub fn contains(&self, name: &str) -> bool {
        self.entries.contains_key(name)
    }

    /// The registered command names, sorted.
    pub fn names(&self) -> impl Iterator<Item = &str> {
        self.entries.keys().map(String::as_str)
    }

    /// The registrations, sorted by name.
    pub fn iter(&self) -> impl Iterator<Item = &Registration<P>> {
        self.entries.values()
    }

    /// The number of registered commands.
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    /// Whether no commands are registered.
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}

impl<P> Registration<P> {
    /// The registration of the native command `entry`.
    pub fn native(entry: &'static Entry) -> Self {
        Registration {
            name: entry.spec.name.clone(),
            aliases: entry.spec.aliases.clone(),
            provider: Provider::Native(entry),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::command::MatchedArgs;
    use crate::command::{CommandContext, CommandError};
    use crate::option::ParsedOptions;

    struct Echo;
    impl Command for Echo {
        fn spec(&self) -> CommandSpec {
            CommandSpec {
                aliases: vec!["e".to_string()],
                ..CommandSpec::new("echo")
            }
        }
        fn run(
            &self,
            _ctx: &mut dyn CommandContext,
            _opts: &ParsedOptions,
            _args: &MatchedArgs,
        ) -> Result<i32, CommandError> {
            Ok(0)
        }
    }

    #[test]
    fn register_and_get() {
        let mut reg = Registry::new();
        reg.register(Box::new(Echo));
        assert_eq!(1, reg.len());

        // Lookup by name and by alias.
        assert_eq!("echo", reg.get("echo").unwrap().spec.name);
        assert_eq!("echo", reg.get("e").unwrap().spec.name);
        assert!(reg.get("nope").is_none());
    }

    fn object(name: &str, aliases: &[&str], tag: u32) -> Registration<u32> {
        Registration {
            name: name.to_string(),
            aliases: aliases.iter().map(|a| a.to_string()).collect(),
            provider: Provider::Object(tag),
        }
    }

    fn tag(r: Option<&Registration<u32>>) -> Option<u32> {
        match r?.provider {
            Provider::Object(t) => Some(t),
            _ => None,
        }
    }

    #[test]
    fn table_lookup_by_name_and_alias() {
        let mut table = CommandTable::new();
        table
            .insert(object("status", &["st", "stat"], 1), false)
            .unwrap();
        assert_eq!(Some(1), tag(table.get("status")));
        assert_eq!(Some(1), tag(table.get("st")));
        assert_eq!(None, tag(table.get("nope")));
        assert_eq!("status", table.resolve("stat"));
        assert!(table.contains("status"));
        assert!(!table.contains("st"));
    }

    #[test]
    fn table_duplicates() {
        let mut table = CommandTable::new();
        table.insert(object("log", &[], 1), false).unwrap();
        assert_eq!(
            Err(AlreadyRegistered("log".to_string())),
            table.insert(object("log", &[], 2), false).map(|_| ())
        );
        assert_eq!(Some(1), tag(table.get("log")));
        let replaced = table.insert(object("log", &[], 3), true).unwrap();
        assert_eq!(Some(1), tag(replaced.as_ref()));
        assert_eq!(Some(3), tag(table.get("log")));
    }

    #[test]
    fn table_remove_drops_aliases() {
        let mut table = CommandTable::new();
        table.insert(object("commit", &["ci"], 1), false).unwrap();
        table.insert(object("diff", &["di"], 2), false).unwrap();
        assert_eq!(Some(1), tag(table.remove("commit").as_ref()));
        assert!(table.get("ci").is_none());
        assert_eq!(Some(2), tag(table.get("di")));
        assert!(table.remove("commit").is_none());
        assert_eq!(vec!["diff"], table.names().collect::<Vec<_>>());
    }

    #[test]
    fn table_names_sorted() {
        let mut table = CommandTable::new();
        for (i, name) in ["push", "add", "merge"].iter().enumerate() {
            table.insert(object(name, &[], i as u32), false).unwrap();
        }
        assert_eq!(
            vec!["add", "merge", "push"],
            table.names().collect::<Vec<_>>()
        );
    }
}
