pub mod filters;
use chrono::{DateTime, FixedOffset, NaiveDateTime, TimeZone, Utc};
use std::collections::HashMap;
use std::fmt::{Debug, Error, Formatter};

pub mod gen_ids;
pub mod globbing;

#[derive(Clone, PartialEq, Eq, Hash)]
pub struct FileId(Vec<u8>);

impl Debug for FileId {
    fn fmt(&self, f: &mut Formatter) -> Result<(), Error> {
        write!(f, "{}", String::from_utf8(self.0.clone()).unwrap())
    }
}

impl From<Vec<u8>> for FileId {
    fn from(v: Vec<u8>) -> Self {
        FileId(v)
    }
}

impl From<FileId> for Vec<u8> {
    fn from(v: FileId) -> Self {
        v.0
    }
}

impl FileId {
    pub fn generate(name: &str) -> Self {
        Self::from(gen_ids::gen_file_id(name))
    }
}

#[derive(Clone, PartialEq, Eq, Hash)]
pub struct RevisionId(Vec<u8>);

impl Debug for RevisionId {
    fn fmt(&self, f: &mut Formatter) -> Result<(), Error> {
        write!(f, "{}", String::from_utf8(self.0.clone()).unwrap())
    }
}

impl std::fmt::Display for RevisionId {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "{}", String::from_utf8(self.0.clone()).unwrap())
    }
}

impl From<Vec<u8>> for RevisionId {
    fn from(v: Vec<u8>) -> Self {
        RevisionId(v)
    }
}

impl From<RevisionId> for Vec<u8> {
    fn from(v: RevisionId) -> Self {
        v.0
    }
}

const NULL_REVISION: &[u8] = b"null:";

impl RevisionId {
    pub fn is_null(&self) -> bool {
        self.0 == NULL_REVISION
    }

    pub fn generate(username: &str, timestamp: Option<u64>) -> Self {
        Self::from(gen_ids::gen_revision_id(username, timestamp))
    }

    pub fn bytes(&self) -> &[u8] {
        &self.0
    }
}

pub fn validate_properties(properties: &HashMap<String, String>) -> bool {
    for (key, _value) in properties.iter() {
        if breezy_osutils::contains_whitespace(key.as_str()) {
            return false;
        }
    }
    true
}

#[derive(Clone, PartialEq)]
pub struct Revision {
    pub revision_id: RevisionId,
    pub parent_ids: Vec<RevisionId>,
    pub committer: Option<String>,
    pub message: String,
    pub properties: HashMap<String, String>,
    pub inventory_sha1: Option<Vec<u8>>,
    pub timestamp: f64,
    pub timezone: Option<i32>,
}

impl Revision {
    pub fn new(
        revision_id: RevisionId,
        parent_ids: Vec<RevisionId>,
        committer: Option<String>,
        message: String,
        properties: HashMap<String, String>,
        inventory_sha1: Option<Vec<u8>>,
        timestamp: f64,
        timezone: Option<i32>,
    ) -> Self {
        Revision {
            revision_id,
            parent_ids,
            committer,
            message,
            properties,
            inventory_sha1,
            timestamp,
            timezone,
        }
    }

    pub fn datetime(&self) -> DateTime<Utc> {
        let dt = NaiveDateTime::from_timestamp(self.timestamp as i64, 0);
        let offset = FixedOffset::east(self.timezone.unwrap_or(0));
        offset.from_utc_datetime(&dt).into()
    }

    pub fn check_properties(&self) -> bool {
        validate_properties(&self.properties)
    }

    pub fn get_summary(&self) -> String {
        if self.message.is_empty() {
            String::new()
        } else {
            let mut summary = self.message.lines().next().unwrap().to_string();
            summary = summary.trim().to_string();
            summary
        }
    }

    /// Return the apparent authors of this revision.
    ///
    /// If the revision properties contain the names of the authors,
    /// return them. Otherwise return the committer name.
    ///
    /// The return value will be a list containing at least one element.
    pub fn get_apparent_authors(&self) -> Vec<String> {
        match self.properties.get("authors") {
            Some(authors) => {
                let authors = authors.split('\n').collect::<Vec<&str>>();
                authors
                    .iter()
                    .filter(|x| !x.is_empty())
                    .map(|x| x.to_string())
                    .collect()
            }
            None => self.properties.get("author").map_or(
                self.committer.clone().map_or(vec![], |v| vec![v]),
                |author| vec![author.clone()],
            ),
        }
    }

    pub fn bug_urls(&self) -> Vec<String> {
        self.properties.get("bugs").map_or(vec![], |bugs| {
            bugs.split('\n').map(|x| x.to_string()).collect()
        })
    }
}

impl std::fmt::Display for Revision {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "Revision({})", self.revision_id)
    }
}
