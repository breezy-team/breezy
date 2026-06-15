//! Provides a shorthand for referring to bugs on a variety of bug trackers.
//!
//! 'commit --fixes' stores references to bugs as a <bug_url> -> <bug_status>
//! mapping in the properties for that revision.
//!
//! However, it's inconvenient to type out full URLs for bugs on the command line,
//! particularly given that many users will be using only a single bug tracker per
//! branch.
//!
//! Thus, this module provides a registry of types of bug tracker (e.g. Launchpad,
//! Trac). Given an abbreviated name (e.g. 'lp', 'twisted') and a branch with
//! configuration information, these tracker types can return an instance capable
//! of converting bug IDs into URLs.

