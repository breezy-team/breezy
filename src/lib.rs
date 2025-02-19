#![warn(
    rust_2018_idioms,
    unused_lifetimes,
    semicolon_in_expressions_from_macros
)]

#[cfg(feature = "i18n")]
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

pub mod bedding;
pub mod bugtracker;

pub mod branch;
pub mod controldir;
pub mod forge;
pub mod help;
pub mod location;
pub mod lockdir;
pub mod progress;
pub mod repository;
pub mod revspec;
pub mod tags;
pub mod trace;

pub mod debug;

pub mod tree;
pub mod treebuilder;

#[cfg(feature = "pyo3")]
pub mod pytree;

#[cfg(feature = "pyo3")]
pub mod pybranch;

#[cfg(feature = "pyo3")]
pub mod pyforge;

#[cfg(feature = "pyo3")]
pub mod pytags;

#[cfg(feature = "pyo3")]
pub mod pycontroldir;

pub mod uncommit;

// Until breezy-graph is complete
pub mod graphshim;

pub use bazaar::RevisionId;
