use breezy_osutils::time::{format_date, Timezone};
use lazy_static::lazy_static;

#[derive(Debug)]
pub enum ParsePatchDateError {
    InvalidDate(String),
    MissingTimezoneOffset(String),
    InvalidTimezoneOffset(String),
}

#[derive(Debug)]
pub enum FormatPatchDateError {
    InvalidTimezoneOffset(i64),
    NegativeTime(i64, i64),
}

pub fn format_patch_date(secs: i64, mut offset: i64) -> Result<String, FormatPatchDateError> {
    if offset % 60 != 0 {
        return Err(FormatPatchDateError::InvalidTimezoneOffset(offset));
    }

    // so that we don't need to do calculations on pre-epoch times,
    // which doesn't work with win32 python gmtime, we always
    // give the epoch in utc
    if secs == 0 {
        offset = 0;
    }
    if secs + offset < 0 {
        return Err(FormatPatchDateError::NegativeTime(secs, offset));
    }

    Ok(format_date(
        secs,
        Some(offset),
        Timezone::Original,
        Some("%Y-%m-%d %H:%M:%S"),
        true,
    ))
}

pub fn parse_patch_date(date_str: &str) -> Result<(i64, i64), ParsePatchDateError> {
    lazy_static! {
        // Format for patch dates: %Y-%m-%d %H:%M:%S [+-]%H%M
        // Groups: 1 = %Y-%m-%d %H:%M:%S; 2 = [+-]%H; 3 = %M
        static ref RE_PATCHDATE: regex::Regex = regex::Regex::new(r"(\d+-\d+-\d+\s+\d+:\d+:\d+)\s*([+-]\d\d)(\d\d)$").unwrap();
        static ref RE_PATCHDATE_NOOFFSET: regex:: Regex = regex::Regex::new(r"\d+-\d+-\d+\s+\d+:\d+:\d+$").unwrap();
    }

    let m = RE_PATCHDATE.captures(date_str);
    if m.is_none() {
        if RE_PATCHDATE_NOOFFSET.captures(date_str).is_some() {
            return Err(ParsePatchDateError::MissingTimezoneOffset(
                date_str.to_string(),
            ));
        } else {
            return Err(ParsePatchDateError::InvalidDate(date_str.to_string()));
        }
    }
    let m = m.unwrap();

    let secs_str = m.get(1).unwrap().as_str();
    let offset_hours = m
        .get(2)
        .unwrap()
        .as_str()
        .parse::<i64>()
        .map_err(|_| ParsePatchDateError::InvalidTimezoneOffset(date_str.to_string()))?;
    let offset_minutes = m
        .get(3)
        .unwrap()
        .as_str()
        .parse::<i64>()
        .map_err(|_| ParsePatchDateError::InvalidTimezoneOffset(date_str.to_string()))?;

    if offset_hours.abs() >= 24 || offset_minutes >= 60 {
        return Err(ParsePatchDateError::InvalidTimezoneOffset(
            date_str.to_string(),
        ));
    }

    let offset = offset_hours * 3600 + offset_minutes * 60;
    // Parse secs_str with a time format %Y-%m-%d %H:%M:%S using the chrono crate
    let dt = chrono::NaiveDateTime::parse_from_str(secs_str, "%Y-%m-%d %H:%M:%S")
        .map_err(|_| ParsePatchDateError::InvalidDate(date_str.to_string()))?
        - chrono::Duration::seconds(offset);

    Ok((dt.and_utc().timestamp(), offset))
}

#[cfg(test)]
mod test {
    #[test]
    fn test_parse_patch_date() {
        assert_eq!(
            super::parse_patch_date("2019-01-01 00:00:00 +0000").unwrap(),
            (1546300800, 0)
        );
        match super::parse_patch_date("2019-01-01 00:00:00") {
            Err(super::ParsePatchDateError::MissingTimezoneOffset(_)) => (),
            e => panic!("Expected MissingTimezoneOffset error, got {:?}", e),
        }
    }
}
