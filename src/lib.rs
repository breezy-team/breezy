//! Breezy: a Rust library for distributed version control.
#![deny(missing_docs)]
#![warn(
    rust_2018_idioms,
    unused_lifetimes,
    semicolon_in_expressions_from_macros
)]

/// Internationalization support.
pub mod i18n;

#[cfg(not(feature = "i18n"))]
pub mod i18n {
    pub fn gettext(msgid: &str) -> String {
        msgid.to_string()
    }

    pub fn nggettext(msgid: &str, msgid_plural: &str, n: usize) -> String {
        if n == 1 {
            msgid.to_string()
        } else {
            msgid_plural.to_string()
        }
    }
}

/// Bedding utilities for configuration and cache directories.
pub mod bedding;
pub mod bugtracker;

/// Command-line argument splitting.
pub mod cmdline;

/// Rename detection by content similarity.
pub mod rename_map;

/// Branch management traits and types.
pub mod branch;
/// Control directory management traits and types.
pub mod controldir;
/// Forge integration traits and types.
pub mod forge;
/// Help system and documentation utilities.
pub mod help;
/// Hook infrastructure.
pub mod hooks;
/// Location parsing and conversion utilities.
pub mod location;
/// Lock directory management.
pub mod lockdir;
/// Progress reporting utilities.
pub mod progress;
/// Repository trait.
pub mod repository;
/// Tag management traits and types.
pub mod tags;
/// Tracing and logging utilities.
pub mod trace;

/// Debugging utilities.
pub mod debug;

/// Unified diff generation.
pub mod diff;

/// Email message construction.
pub mod email_message;

/// Text wrapping with East Asian width support.
pub mod utextwrap;

/// Output formatting for ``brz shell-complete``.
pub mod shellcomplete;

/// Tree traits and types.
pub mod tree;
/// Tree builder utilities.
pub mod treebuilder;

/// Command trait and infrastructure.
pub mod command;

/// Command-line option parsing.
pub mod optparse;

/// Pure helpers for command-line option definitions (the `Option` class).
pub mod options;

/// Native command registry and the command-lookup traits.
pub mod registry;

#[doc(hidden)]
/// Re-export of the `inventory` crate for use by the `declare_command!` macro.
pub use inventory as __inventory;

/// Command-line option definitions and parsed option values.
pub mod option;

pub mod version;

#[cfg(feature = "pyo3")]
/// Python bindings for Tree.
pub mod pytree;

#[cfg(feature = "pyo3")]
/// Python bindings for Branch.
pub mod pybranch;

#[cfg(feature = "pyo3")]
/// Python bindings for Command.
pub mod pycommand;

#[cfg(feature = "pyo3")]
/// Command orchestration driven through PyO3 (entry path, lookup, parsing).
pub mod commands;

/// The command tables, holding Python as well as native commands.
pub mod pyregistry;

#[cfg(feature = "pyo3")]
/// The help indexes that render live Python objects.
pub mod pyhelp;

#[cfg(feature = "pyo3")]
/// Python bindings for hooks.
pub mod pyhooks;

#[cfg(feature = "pyo3")]
/// Python bindings for Forge.
pub mod pyforge;

#[cfg(feature = "pyo3")]
/// Python bindings for Tags.
pub mod pytags;

#[cfg(feature = "pyo3")]
/// Python bindings for ControlDir.
pub mod pycontroldir;

/// Uncommit functionality.
pub mod uncommit;

// Until breezy-graph is complete
/// Temporary graph shim until breezy-graph is complete.
pub mod graphshim;

pub use bazaar::RevisionId;
