//! Breezy command-line interface: command dispatch, option parsing and help.
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

/// Command trait and infrastructure.
pub mod command;

/// Command-line option parsing (a replacement for Python's optparse).
pub mod optparse;

/// Help system and documentation utilities.
pub mod help;

#[cfg(feature = "pyo3")]
/// Python bindings for Command.
pub mod pycommand;

mod bugtracker_help;
