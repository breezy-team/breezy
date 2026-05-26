use debversion::Version;

/// Return the name of the .orig.tar.gz for the given package and version.
///
/// # Arguments
/// * `package`: the name of the source package.
/// * `version`: the upstream version of the package.
/// * `component`: Component name (None for base)
/// * `format`: the format for the tarball. If None then 'gz' will be
///    used. You probably want on of 'gz', 'bz2', 'lzma' or 'xz'.
///
/// # Returns
/// a string that is the name of the upstream tarball to use.
pub fn tarball_name(package: &str, version: &Version, component: Option<&str>, format: Option<&str>) -> String {
    let format = format.unwrap_or("gz");
    let mut name = format!("{}_{}.orig", package, version);
    if let Some(component) = component {
        name += "-";
        name += component;
    }
    format!("{}.tar.{}", name, format)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::str::FromStr;

    #[test]
    fn test_tarball_name() {
       assert_eq!(
           tarball_name("package", &Version::from_str("0.1").unwrap(), None, None), "package_0.1.orig.tar.gz"
       );
       assert_eq!(
           tarball_name("package", &Version::from_str("0.1").unwrap(), None, Some("bz2")),
           "package_0.1.orig.tar.bz2",
       );
       assert_eq!(
           tarball_name("package", &Version::from_str("0.1").unwrap(), None, Some("xz")),
           "package_0.1.orig.tar.xz",
       );
       assert_eq!(
           tarball_name("package", &Version::from_str("0.1").unwrap(), Some("la"), Some("xz")),
           "package_0.1.orig-la.tar.xz",
       );
   }
}


