//! This crate contains a rust wrapper for the Breezy API, which is written in Python.
//!
//! Breezy itself is being ported to Rust, but until that port has completed, this crate allows
//! access to the most important Breezy APIs via Rust.
//!
//! The Rust API here will follow the Breezy 4.0 Rust API as much as possible, to make porting
//! easier.
//!
//! # Example
//!
//! ```
//! let b = Branch.open("lp:breezy")?;
//! println!("Last revision: {:?}", b.last_revision());
//! ```

pub mod branch;
pub mod controldir;
pub mod diff;
pub mod dirty_tracker;
pub mod forge;
pub mod graph;
pub mod lock;
pub mod repository;
pub mod revisionid;
pub mod transport;
pub mod tree;
pub mod urlutils;
pub mod workspace;

#[cfg(feature = "debian")]
pub mod debian;

pub use branch::Branch;
pub use controldir::{ControlDir, Prober};
pub use dirty_tracker::DirtyTracker;
pub use forge::{get_forge, Forge, MergeProposal, MergeProposalStatus};
pub use lock::Lock;
pub use revisionid::RevisionId;
pub use transport::{get_transport, Transport};
pub use tree::{RevisionTree, Tree, WorkingTree};
pub use urlutils::{join_segment_parameters, split_segment_parameters};
pub use workspace::reset_tree;
