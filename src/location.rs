use percent_encoding::{utf8_percent_encode, CONTROLS};
use pyo3::prelude::*;
use url::Url;

use regex::Regex;

#[derive(Debug)]
pub struct Error(String);

pub fn parse_rcp_location(location: &str) -> Result<(String, Option<String>, String), Error> {
    let re = Regex::new(r"^(?P<user>[^@:/]+@)?(?P<host>[^/:]{2,}):(?P<path>.*)$").unwrap();
    if let Some(captures) = re.captures(location) {
        let host = captures["host"].to_string();
        let user = captures
            .name("user")
            .map(|user| user.as_str()[..user.as_str().len() - 1].to_string());
        let path = captures["path"].to_string();
        if path.starts_with("//") {
            Err(Error(
                "Not an RCP URL: already looks like a URL".to_string(),
            ))
        } else {
            Ok((host, user, path))
        }
    } else {
        Err(Error("Not an RCP URL: no match".to_string()))
    }
}

pub fn rcp_location_to_url(location: &str, scheme: &str) -> Result<url::Url, Error> {
    let (host, user, path) = parse_rcp_location(location)?;
    let quoted_user = if let Some(user) = user {
        format!("{}@", utf8_percent_encode(user.as_str(), CONTROLS))
    } else {
        "".to_string()
    };
    Url::parse(&format!(
        "{}://{}{}{}",
        scheme,
        quoted_user,
        utf8_percent_encode(host.as_str(), CONTROLS),
        utf8_percent_encode(path.as_str(), CONTROLS)
    ))
    .map_err(|e| Error(format!("Invalid URL: {}", e)))
}

pub fn parse_cvs_location(
    location: &str,
) -> Result<(String, String, Option<String>, String), Error> {
    let parts: Vec<&str> = location.split(':').collect();
    if !parts[0].is_empty() || !["pserver", "ssh", "extssh"].contains(&parts[1]) {
        return Err(Error(format!(
            "not a valid CVS location string: {}",
            location
        )));
    }
    let (username, hostname) = match parts[2].split_once('@') {
        Some((username, hostname)) => (Some(username.to_string()), hostname.to_string()),
        None => (None, parts[2].to_string()),
    };
    let scheme = if parts[1] == "extssh" {
        "ssh"
    } else {
        parts[1]
    };
    let path = match parts.get(3) {
        Some(&path) => {
            if path.starts_with('/') {
                path.to_string()
            } else {
                return Err(Error(format!(
                    "path element in CVS location {} does not start with /",
                    location
                )));
            }
        }
        None => {
            return Err(Error(format!(
                "no path element in CVS location {}",
                location
            )))
        }
    };
    Ok((scheme.to_string(), hostname, username, path))
}

pub fn cvs_to_url(location: &str) -> Result<Url, Error> {
    let (scheme, host, user, path) = parse_cvs_location(location)?;
    let quoted_user = if let Some(user) = user {
        format!("{}@", utf8_percent_encode(user.as_str(), CONTROLS))
    } else {
        "".to_string()
    };

    let url = Url::parse(&format!(
        "cvs+{}://{}{}{}",
        scheme,
        quoted_user,
        utf8_percent_encode(&host, CONTROLS),
        utf8_percent_encode(&path, CONTROLS)
    ))
    .map_err(|e| Error(format!("Invalid URL: {}", e)))?;
    Ok(url)
}

pub trait AsLocation {
    fn as_location(&self) -> PyObject;
}

impl AsLocation for &url::Url {
    fn as_location(&self) -> PyObject {
        Python::with_gil(|py| pyo3::types::PyString::new(py, self.to_string().as_str()).unbind())
            .into_any()
    }
}

impl AsLocation for &str {
    fn as_location(&self) -> PyObject {
        Python::with_gil(|py| pyo3::types::PyString::new(py, self).unbind()).into_any()
    }
}

impl AsLocation for &std::path::Path {
    fn as_location(&self) -> PyObject {
        Python::with_gil(|py| pyo3::types::PyString::new(py, self.to_str().unwrap()).unbind())
            .into_any()
    }
}
