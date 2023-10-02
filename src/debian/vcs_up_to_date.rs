use crate::tree::Tree;
use debversion::Version;
use pyo3::prelude::*;

#[derive(PartialEq, Eq)]
pub enum UpToDateStatus {
    UpToDate,
    MissingChangelog,
    PackageMissingInArchive {
        package: String,
    },
    TreeVersionNotInArchive {
        tree_version: Version,
        archive_versions: Vec<Version>,
    },
    NewArchiveVersion {
        archive_version: Version,
        tree_version: Version,
    },
}

pub struct Apt(pub PyObject);

pub fn check_up_to_date(
    tree: &dyn Tree,
    subpath: &std::path::Path,
    apt: &Apt,
) -> PyResult<UpToDateStatus> {
    use pyo3::import_exception;
    import_exception!(breezy.plugins.debian.vcs_up_to_date, MissingChangelogError);
    import_exception!(
        breezy.plugins.debian.vcs_up_to_date,
        PackageMissingInArchive
    );
    import_exception!(
        breezy.plugins.debian.vcs_up_to_date,
        TreeVersionNotInArchive
    );
    import_exception!(breezy.plugins.debian.vcs_up_to_date, NewArchiveVersion);
    Python::with_gil(|py| {
        let m = py.import("breezy.plugins.debian.vcs_up_to_date")?;
        let check_up_to_date = m.getattr("check_up_to_date")?;
        match check_up_to_date.call1((tree.to_object(py), subpath.to_path_buf(), &apt.0)) {
            Err(e) if e.is_instance_of::<MissingChangelogError>(py) => {
                Ok(UpToDateStatus::MissingChangelog)
            }
            Err(e) if e.is_instance_of::<PackageMissingInArchive>(py) => {
                Ok(UpToDateStatus::PackageMissingInArchive {
                    package: e.value(py).getattr("package")?.extract()?,
                })
            }
            Err(e) if e.is_instance_of::<TreeVersionNotInArchive>(py) => {
                Ok(UpToDateStatus::TreeVersionNotInArchive {
                    tree_version: e.value(py).getattr("tree_version")?.extract()?,
                    archive_versions: e
                        .value(py)
                        .getattr("archive_versions")?
                        .extract::<Vec<Version>>()?,
                })
            }
            Err(e) if e.is_instance_of::<NewArchiveVersion>(py) => {
                Ok(UpToDateStatus::NewArchiveVersion {
                    archive_version: e.value(py).getattr("archive_version")?.extract()?,
                    tree_version: e.value(py).getattr("tree_version")?.extract()?,
                })
            }
            Ok(_o) => Ok(UpToDateStatus::UpToDate),
            Err(e) => Err(e),
        }
    })
}
