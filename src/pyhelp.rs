//! PyO3 implementations of the help indexes that need Python objects.
//!
//! The search order, the shadowing rules and the topic lookup are pure
//! ([`crate::help`]); these are the indexes that cannot be, because they read
//! live Python objects: a command instance's help text, a loaded plugin
//! module's docstring and the config option registry.

use crate::help::{FoundTopic, HelpError, HelpIndex};
use pyo3::prelude::*;

/// The index serving per-command help.
///
/// Resolving a command means instantiating the Python command class and asking
/// it for its help text, so this index is PyO3 by necessity.
pub struct CommandIndex<'py> {
    py: Python<'py>,
}

impl<'py> CommandIndex<'py> {
    /// Build an index looking commands up in the given interpreter.
    pub fn new(py: Python<'py>) -> Self {
        CommandIndex { py }
    }
}

impl HelpIndex for CommandIndex<'_> {
    fn prefix(&self) -> &str {
        "commands/"
    }

    fn get_topics(&self, topic: Option<&str>) -> Result<Vec<FoundTopic>, HelpError> {
        let Some(topic) = topic.filter(|t| !t.is_empty()) else {
            return Ok(vec![]);
        };
        let name = topic.strip_prefix(self.prefix()).unwrap_or(topic);
        // check_missing=False: an unknown command is simply not a help topic.
        // A KeyError means "not found"; any other failure is real and propagates.
        let cmd = match crate::commands::get_cmd_object_inner(self.py, name, true, false) {
            Ok(Some(cmd)) => cmd,
            Ok(None) => return Ok(vec![]),
            Err(e) if e.is_instance_of::<pyo3::exceptions::PyKeyError>(self.py) => {
                return Ok(vec![])
            }
            Err(e) => return Err(HelpError::Python(e)),
        };
        let cmd_name = cmd
            .bind(self.py)
            .call_method0("name")
            .and_then(|n| n.extract::<String>())
            .map_err(HelpError::Python)?;
        Ok(vec![FoundTopic {
            prefix: self.prefix().to_string(),
            topic: cmd_name,
            text: Box::new(move |shadowed| {
                Python::attach(|py| {
                    crate::commands::get_help_text(
                        py,
                        cmd.bind(py),
                        Some(shadowed.to_vec()),
                        true,
                        false,
                        true,
                    )
                    .map_err(HelpError::Python)
                })
            }),
        }])
    }
}

/// The index serving help for loaded plugins.
///
/// A plugin's help is its module docstring, read from the already-imported
/// module; this never triggers loading a new plugin.
pub struct PluginIndex<'py> {
    py: Python<'py>,
}

impl<'py> PluginIndex<'py> {
    /// Build an index reading plugin modules from the given interpreter.
    pub fn new(py: Python<'py>) -> Self {
        PluginIndex { py }
    }
}

impl HelpIndex for PluginIndex<'_> {
    fn prefix(&self) -> &str {
        "plugins/"
    }

    fn get_topics(&self, topic: Option<&str>) -> Result<Vec<FoundTopic>, HelpError> {
        let Some(topic) = topic.filter(|t| !t.is_empty()) else {
            return Ok(vec![]);
        };
        let name = topic.strip_prefix(self.prefix()).unwrap_or(topic);
        let plugin = self.py.import("breezy.plugin").map_err(HelpError::Python)?;
        let module_prefix: String = plugin
            .getattr("_MODULE_PREFIX")
            .and_then(|p| p.extract())
            .map_err(HelpError::Python)?;
        let modules = self
            .py
            .import("sys")
            .and_then(|sys| sys.getattr("modules"))
            .map_err(HelpError::Python)?;
        let module = match modules.get_item(format!("{module_prefix}{name}")) {
            Ok(module) => module,
            // Not imported: not a plugin help topic.
            Err(e) if e.is_instance_of::<pyo3::exceptions::PyKeyError>(self.py) => {
                return Ok(vec![]);
            }
            Err(e) => return Err(HelpError::Python(e)),
        };
        let help_topic = plugin
            .getattr("ModuleHelpTopic")
            .and_then(|c| c.call1((module,)))
            .map_err(HelpError::Python)?
            .unbind();
        Ok(vec![FoundTopic {
            prefix: self.prefix().to_string(),
            topic: name.to_string(),
            text: Box::new(move |shadowed| {
                Python::attach(|py| {
                    help_topic
                        .bind(py)
                        .call_method1("get_help_text", (shadowed.to_vec(),))
                        .and_then(|t| t.extract())
                        .map_err(HelpError::Python)
                })
            }),
        }])
    }
}

/// The index serving help for configuration options.
///
/// The options live in the Python ``config.option_registry``, so the lookup is
/// PyO3 even though the surrounding search is not.
pub struct ConfigOptionIndex<'py> {
    py: Python<'py>,
}

impl<'py> ConfigOptionIndex<'py> {
    /// Build an index reading the Python config option registry.
    pub fn new(py: Python<'py>) -> Self {
        ConfigOptionIndex { py }
    }
}

impl HelpIndex for ConfigOptionIndex<'_> {
    fn prefix(&self) -> &str {
        "configuration/"
    }

    fn get_topics(&self, topic: Option<&str>) -> Result<Vec<FoundTopic>, HelpError> {
        let Some(topic) = topic else {
            return Ok(vec![]);
        };
        let name = topic.strip_prefix(self.prefix()).unwrap_or(topic);
        let registry = self
            .py
            .import("breezy.config")
            .and_then(|c| c.getattr("option_registry"))
            .map_err(HelpError::Python)?;
        if !registry.contains(name).map_err(HelpError::Python)? {
            return Ok(vec![]);
        }
        let option = registry
            .call_method1("get", (name,))
            .map_err(HelpError::Python)?
            .unbind();
        Ok(vec![FoundTopic {
            prefix: self.prefix().to_string(),
            topic: name.to_string(),
            text: Box::new(move |shadowed| {
                Python::attach(|py| {
                    option
                        .bind(py)
                        .call_method1("get_help_text", (shadowed.to_vec(),))
                        .and_then(|t| t.extract())
                        .map_err(HelpError::Python)
                })
            }),
        }])
    }
}

/// Render the help for `topic` over the standard search path: topics,
/// commands, plugins, then configuration options.
pub fn help_text(py: Python<'_>, topic: Option<&str>) -> PyResult<String> {
    // breezy.help registers the "commands" and "hidden-commands" topics.
    py.import("breezy.help")?;
    let topics = crate::help::TopicIndex;
    let commands = CommandIndex::new(py);
    let plugins = PluginIndex::new(py);
    let config = ConfigOptionIndex::new(py);
    let indexes: [&dyn HelpIndex; 4] = [&topics, &commands, &plugins, &config];

    // An alias is reported even when it names no help topic.
    let alias = match topic {
        Some(topic) => py
            .import("breezy.commands")?
            .call_method1("get_alias", (topic,))?
            .extract::<Option<Vec<String>>>()?,
        None => None,
    };
    crate::help::help_text(&indexes, topic, alias.as_deref()).map_err(|e| match e {
        HelpError::NoHelpTopic(_) => no_help_topic(py, topic.unwrap_or_default()),
        // A carried Python exception is re-raised unchanged, keeping its type.
        HelpError::Python(err) => err,
        // A duplicate prefix is a programming error in the search path.
        other => pyo3::exceptions::PyRuntimeError::new_err(other.message()),
    })
}

/// Build the Python ``breezy.help.NoHelpTopic`` for `topic`.
fn no_help_topic(py: Python<'_>, topic: &str) -> PyErr {
    match py
        .import("breezy.help")
        .and_then(|h| h.getattr("NoHelpTopic"))
        .and_then(|c| c.call1((topic,)))
    {
        Ok(err) => PyErr::from_value(err),
        Err(e) => e,
    }
}

/// Gather the ``brz help commands`` listing for the visible commands (the body
/// of ``help._help_commands_to_text``, less the wrapping).
///
/// `hidden` selects the hidden commands instead of the normal ones. Returns the
/// unwrapped lines and the indent their continuations should use; the caller
/// wraps them, since breezy's wrapping is East-Asian aware.
pub fn command_listing(py: Python<'_>, hidden: bool) -> PyResult<(Vec<String>, usize)> {
    let commands = py.import("breezy.commands")?;
    let mut names: Vec<String> = commands
        .call_method0("all_command_names")?
        .extract::<std::collections::HashSet<String>>()?
        .into_iter()
        .collect();
    names.sort();

    let mut summaries = Vec::new();
    for name in names {
        let cmd = commands.call_method1("get_cmd_object", (&name,))?;
        if cmd.getattr("hidden")?.is_truthy()? != hidden {
            continue;
        }
        let plugin: Option<String> = cmd.call_method0("plugin_name")?.extract()?;
        let help: Option<String> = cmd.call_method0("help")?.extract()?;
        let first_line = help
            .as_deref()
            .and_then(|h| h.split('\n').next())
            .unwrap_or_default()
            .to_string();
        summaries.push(crate::help::CommandSummary {
            name,
            first_line,
            plugin,
        });
    }
    Ok(crate::help::command_listing_lines(&summaries))
}
