/// A trait representing a control directory in a version control system.
///
/// A control directory is the root of a version control repository and contains
/// metadata about the repository, such as branch information, configuration,
/// and other repository-specific data.
pub trait ControlDir {}

/// A trait for probing and detecting control directories.
///
/// Implementations of this trait are responsible for detecting and identifying
/// control directories in a filesystem, allowing the system to determine
/// whether a given directory is a valid control directory and what type it is.
pub trait Prober {}
