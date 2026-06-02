use crate::RevisionId;
use chrono::{DateTime, NaiveDateTime};
use std::collections::HashMap;

pub fn validate_properties(properties: &HashMap<String, Vec<u8>>) -> bool {
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
    pub properties: HashMap<String, Vec<u8>>,
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
        properties: HashMap<String, Vec<u8>>,
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

    pub fn datetime(&self) -> NaiveDateTime {
        DateTime::from_timestamp(self.timestamp as i64, 0)
            .expect("timestamp should be valid")
            .naive_utc()
    }

    pub fn timezone(&self) -> Option<chrono::FixedOffset> {
        self.timezone
            .map(|t| chrono::FixedOffset::east_opt(t).unwrap())
    }

    pub fn check_properties(&self) -> bool {
        validate_properties(&self.properties)
    }

    pub fn get_summary(&self) -> String {
        if self.message.is_empty() {
            String::new()
        } else {
            let mut summary = self.message.trim().lines().next().unwrap().to_string();
            summary = summary.trim().to_string();
            summary
        }
    }

    fn get_property_as_str(&self, key: &str) -> Option<String> {
        self.properties
            .get(key)
            .map(|x| String::from_utf8_lossy(x).to_string())
    }

    /// Return the apparent authors of this revision.
    ///
    /// If the revision properties contain the names of the authors,
    /// return them. Otherwise return the committer name.
    ///
    /// The return value will be a list containing at least one element.
    pub fn get_apparent_authors(&self) -> Vec<String> {
        let authors = match self.get_property_as_str("authors") {
            Some(authors) => {
                let authors = authors.split('\n').collect::<Vec<&str>>();
                authors.iter().map(|x| x.to_string()).collect()
            }
            None => self.get_property_as_str("author").map_or(
                self.committer.clone().map_or(vec![], |v| vec![v]),
                |author| vec![author],
            ),
        };

        authors.into_iter().filter(|x| !x.is_empty()).collect()
    }

    pub fn bug_urls(&self) -> Vec<String> {
        self.get_property_as_str("bugs").map_or(vec![], |bugs| {
            bugs.split('\n').map(|x| x.to_string()).collect()
        })
    }
}

impl std::fmt::Display for Revision {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "Revision({})", self.revision_id)
    }
}
