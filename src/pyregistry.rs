//! The command tables, holding Python as well as native commands.
//!
//! The builtin and plugin command registries are [`CommandTable`]s owned here.
//! A Python command is registered as its class, and a lazily registered one as
//! the module that defines it; looking a command up from Python yields a class
//! to instantiate, which for a native command is its generated class in
//! ``breezy.builtins``.

use std::sync::{Arc, Mutex, MutexGuard};

use pyo3::prelude::*;

use crate::registry::{AlreadyRegistered, CommandTable, Provider, Registration};

/// A command table shared between its Python views and the Rust code using it.
#[derive(Clone, Default)]
pub struct SharedTable(Arc<Mutex<CommandTable<Py<PyAny>>>>);

impl SharedTable {
    /// A new, empty table.
    pub fn new() -> Self {
        Self::default()
    }

    /// Lock the table. The lock must not be held while calling into Python,
    /// which may register commands itself.
    pub fn lock(&self) -> MutexGuard<'_, CommandTable<Py<PyAny>>> {
        // A panic while the table was locked leaves no partial update behind:
        // every mutation is a single CommandTable call.
        self.0.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// The registered command names, sorted.
    pub fn names(&self) -> Vec<String> {
        self.lock().names().map(str::to_string).collect()
    }

    /// The aliases of the command registered under `name`, if any.
    pub fn aliases(&self, name: &str) -> Option<Vec<String>> {
        self.lock().get(name).map(|r| r.aliases.clone())
    }

    /// The class of the command registered under `name` or as an alias `name`,
    /// importing it if it was registered lazily.
    pub fn class(&self, py: Python<'_>, name: &str) -> PyResult<Option<Py<PyAny>>> {
        let (resolved, lazy) = {
            let table = self.lock();
            let Some(registration) = table.get(name) else {
                return Ok(None);
            };
            let resolved = registration.name.clone();
            match &registration.provider {
                Provider::Object(class) => return Ok(Some(class.clone_ref(py))),
                Provider::Native(entry) => {
                    let class_name = crate::command::squish_command_name(&entry.spec.name);
                    drop(table);
                    let class = py.import("breezy.builtins")?.getattr(class_name)?;
                    return Ok(Some(class.unbind()));
                }
                Provider::Lazy { module, member } => (resolved, (module.clone(), member.clone())),
            }
        };
        let (module, member) = lazy;
        let mut class = py.import(module.as_str())?.into_any();
        for attr in member.split('.') {
            class = class.getattr(attr)?;
        }
        // Remember the class, unless the registration changed while importing.
        if let Some(registration) = self.lock().get_mut(&resolved) {
            if matches!(&registration.provider, Provider::Lazy { module: m, member: n } if *m == module && *n == member)
            {
                registration.provider = Provider::Object(class.clone().unbind());
            }
        }
        Ok(Some(class.unbind()))
    }

    /// Register the Python command class `cmd`, replacing a command of the same
    /// name only if `decorate` is set.
    ///
    /// Returns the command class previously registered under that name, here or
    /// in `overridden`. Registering a second command of the same name without
    /// `decorate` keeps the first and warns.
    pub fn register_class(
        &self,
        cmd: &Bound<'_, PyAny>,
        decorate: bool,
        overridden: Option<&SharedTable>,
    ) -> PyResult<Option<Py<PyAny>>> {
        let py = cmd.py();
        let class_name: String = cmd.getattr("__name__")?.extract()?;
        let name = command_name(&class_name);
        let previous = match self.class(py, &name)? {
            Some(previous) => Some(previous),
            None => match overridden {
                Some(overridden) => overridden.class(py, &name)?,
                None => None,
            },
        };
        let registration = Registration {
            name,
            aliases: cmd.getattr("aliases")?.extract()?,
            provider: Provider::Object(cmd.clone().unbind()),
        };
        let inserted = self.lock().insert(registration, decorate);
        if let Err(AlreadyRegistered(_)) = inserted {
            let trace = py.import("breezy.trace")?;
            let modules = py.import("sys")?.getattr("modules")?;
            let class_repr = class_name.into_pyobject(py)?.repr()?;
            trace.call_method1(
                "warning",
                (format!(
                    "Two plugins defined the same command: {class_repr}"
                ),),
            )?;
            let module = modules.get_item(cmd.getattr("__module__")?)?;
            trace.call_method1(
                "warning",
                (format!("Not loading the one in {}", module.repr()?),),
            )?;
            if let Some(previous) = &previous {
                let previous_module = modules.get_item(previous.bind(py).getattr("__module__")?)?;
                trace.call_method1(
                    "warning",
                    (format!(
                        "Previously this command was registered from {}",
                        previous_module.repr()?
                    ),),
                )?;
            }
        }
        Ok(previous)
    }

    /// Register the command class `member` of `module` (``cmd_foo``) without
    /// importing the module until the command is used.
    pub fn register_lazy(
        &self,
        member: &str,
        aliases: Vec<String>,
        module: &str,
    ) -> Result<(), AlreadyRegistered> {
        let registration = Registration {
            name: command_name(member),
            aliases,
            provider: Provider::Lazy {
                module: module.to_string(),
                member: member.to_string(),
            },
        };
        self.lock().insert(registration, false).map(|_| ())
    }
}

/// The command name for a command class name: ``cmd_foo_bar`` is ``foo-bar``;
/// a name without the ``cmd_`` prefix is used as is.
pub fn command_name(class_name: &str) -> String {
    if class_name.starts_with("cmd_") {
        crate::command::unsquish_command_name(class_name)
    } else {
        class_name.to_string()
    }
}

/// The builtin commands.
pub fn builtin_commands() -> &'static SharedTable {
    static TABLE: std::sync::OnceLock<SharedTable> = std::sync::OnceLock::new();
    TABLE.get_or_init(SharedTable::new)
}

/// The commands registered by plugins, which take precedence over the builtin
/// ones.
pub fn plugin_commands() -> &'static SharedTable {
    static TABLE: std::sync::OnceLock<SharedTable> = std::sync::OnceLock::new();
    TABLE.get_or_init(SharedTable::new)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn command_names() {
        assert_eq!("foo-bar", command_name("cmd_foo_bar"));
        assert_eq!("foo", command_name("foo"));
    }
}
