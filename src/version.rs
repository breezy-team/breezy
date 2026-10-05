//! The Breezy version.

/// The Breezy version, in the format of ``breezy.version_info``: major, minor,
/// micro, release level and serial. It has to match ``breezy.version_info``,
/// which the build reads, and the crate version.
pub const VERSION_INFO: (u32, u32, u32, &str, u32) = (3, 4, 0, "dev", 0);

/// The version as shown to users, e.g. ``3.4.0.dev``, formatted like
/// ``breezy._format_version_tuple``.
pub fn version_string() -> String {
    format_version_info(VERSION_INFO)
}

fn format_version_info(
    (major, minor, micro, release, serial): (u32, u32, u32, &str, u32),
) -> String {
    let full = format!("{major}.{minor}.{micro}");
    match (release, serial) {
        ("final", 0) => full,
        ("final", n) => format!("{full}.{n}"),
        ("dev", 0) => format!("{full}.dev"),
        ("dev", n) => format!("{full}.dev{n}"),
        ("alpha" | "beta", n) => {
            let main = if micro == 0 {
                format!("{major}.{minor}")
            } else {
                full
            };
            format!("{main}.{}{n}", &release[..1])
        }
        ("candidate", n) => format!("{full}.rc{n}"),
        (other, n) => format!("{full}.{other}.{n}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matches_crate_version() {
        let (major, minor, micro, _, _) = VERSION_INFO;
        assert_eq!(
            env!("CARGO_PKG_VERSION"),
            format!("{major}.{minor}.{micro}")
        );
    }

    #[test]
    fn format_like_python() {
        // The examples of breezy._format_version_tuple.
        for (info, expected) in [
            ((1, 0, 0, "final", 0), "1.0.0"),
            ((1, 2, 0, "dev", 0), "1.2.0.dev"),
            ((1, 2, 0, "dev", 1), "1.2.0.dev1"),
            ((1, 1, 1, "candidate", 2), "1.1.1.rc2"),
            ((2, 1, 0, "beta", 1), "2.1.b1"),
            ((2, 1, 0, "final", 42), "2.1.0.42"),
            ((1, 4, 0, "wibble", 0), "1.4.0.wibble.0"),
        ] {
            assert_eq!(expected, format_version_info(info));
        }
    }
}
