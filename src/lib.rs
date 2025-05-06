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

/// Branch management traits and types.
pub mod branch;
/// Control directory management traits and types.
pub mod controldir;
/// Forge integration traits and types.
pub mod forge;
/// Help system and documentation utilities.
pub mod help;
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

/// Tree traits and types.
pub mod tree;
/// Tree builder utilities.
pub mod treebuilder;

#[cfg(feature = "pyo3")]
/// Python bindings for Tree.
pub mod pytree;

#[cfg(feature = "pyo3")]
/// Python bindings for Branch.
pub mod pybranch;

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
