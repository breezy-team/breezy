//! High-performance smart server (HPSS) protocol for breezy.
//!
//! This crate is the Rust home for the breezy smart protocol, currently
//! implemented in Python under `breezy/bzr/smart/`. Code is ported here
//! incrementally; see the porting plan for the intended order.
//!
//! Protocol version markers live in the `bazaar` crate (exposed to Python as
//! `bzrformats.smart`) and are re-exported there; this crate owns the
//! breezy-specific protocol logic that is not part of bzrformats.

pub mod protocol;
