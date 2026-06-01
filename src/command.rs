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
}
