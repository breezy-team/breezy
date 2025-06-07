/// A repository format.
///
/// Formats provide four things:
///  * An initialization routine to construct repository data on disk.
///  * a optional format string which is used when the BzrDir supports
///    versioned children.
///  * an open routine which returns a Repository instance.
///  * A network name for referring to the format in smart server RPC
///    methods.
///
/// There is one and only one Format subclass for each on-disk format. But
/// there can be one Repository subclass that is used for several different
/// formats. The _format attribute on a Repository instance can be used to
/// determine the disk format.
///
/// Formats are placed in a registry by their format string for reference
/// during opening. These should be subclasses of RepositoryFormat for
/// consistency.
///
/// Once a format is deprecated, just deprecate the initialize and open
/// methods on the format class. Do not deprecate the object, as the
/// object may be created even when a repository instance hasn't been
/// created.
///
/// Common instance attributes:
/// _matchingcontroldir - the controldir format that the repository format was
/// originally written to work with. This can be used if manually
/// constructing a bzrdir and repository, or more commonly for test suite
/// parameterization.
pub trait RepositoryFormat {
    fn get_format_description(&self) -> String;

    /// Is this format supported?
    ///
    /// Supported formats must be initializable and openable.
    /// Unsupported formats may not support initialization or committing or
    /// some other features depending on the reason for not being supported.
    fn is_supported(&self) -> bool;

    /// Is this format deprecated?
    ///
    /// Deprecated formats may trigger a user-visible warning recommending
    /// the user to upgrade. They are still fully supported.
    fn is_deprecated(&self) -> bool;

    /// A simple byte string uniquely identifying this format for RPC calls.
    ///
    /// MetaDir repository formats use their disk format string to identify the
    /// repository over the wire. All in one formats such as bzr < 0.8, and
    /// foreign formats like svn/git and hg should use some marker which is
    /// unique and immutable.
    fn network_name(&self) -> Vec<u8>;
}
