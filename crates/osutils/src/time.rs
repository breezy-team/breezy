use chrono::{DateTime, FixedOffset, Local, NaiveDateTime, TimeZone, Utc};

const DEFAULT_DATE_FORMAT: &str = "%a %Y-%m-%d %H:%M:%S";

pub fn local_time_offset(t: Option<i64>) -> i64 {
    let timestamp = t.unwrap_or_else(|| Utc::now().timestamp());
    let local_time: DateTime<Local> = Utc.timestamp(timestamp, 0).with_timezone(&Local);
    let utc_time: DateTime<Utc> = Utc.timestamp(timestamp, 0);

    let local_naive_datetime = local_time.naive_utc();
    let utc_naive_datetime = utc_time.naive_utc();

    let offset = local_naive_datetime - utc_naive_datetime;
    offset.num_seconds()
}

pub fn format_local_date(
    t: i64,
    offset: Option<i32>,
    timezone: Timezone,
    date_fmt: Option<&str>,
    show_offset: bool,
) -> String {
    let offset = offset.unwrap_or(0);
    let tz: FixedOffset = match timezone {
        Timezone::Utc => FixedOffset::east_opt(0).unwrap(),
        Timezone::Original => FixedOffset::east_opt(offset).unwrap(),
        Timezone::Local => *Local::now().offset(),
    };
    let dt: DateTime<FixedOffset> = tz.timestamp_opt(t, 0).unwrap();
    let date_fmt = date_fmt.unwrap_or("%c");
    let date_str = dt.format(date_fmt).to_string();
    let offset_str = if show_offset {
        let offset_fmt = if offset < 0 { "%z" } else { "%:z" };
        dt.format(offset_fmt).to_string()
    } else {
        "".to_string()
    };
    date_str + &offset_str
}

pub enum Timezone {
    Local,
    Utc,
    Original,
}

impl Timezone {
    pub fn from(s: &str) -> Option<Self> {
        match s {
            "local" => Some(Timezone::Local),
            "utc" => Some(Timezone::Utc),
            "original" => Some(Timezone::Original),
            _ => None,
        }
    }
}

pub fn format_delta(delta: i64) -> String {
    let mut delta = delta;
    let direction: &str;
    if delta >= 0 {
        direction = "ago";
    } else {
        direction = "in the future";
        delta = -delta;
    }

    let seconds = delta;
    if seconds < 90 {
        if seconds == 1 {
            return format!("{} second {}", seconds, direction);
        } else {
            return format!("{} seconds {}", seconds, direction);
        }
    }

    let mut minutes = seconds / 60;
    let seconds = seconds % 60;
    let plural_seconds = if seconds == 1 { "" } else { "s" };

    if minutes < 90 {
        if minutes == 1 {
            return format!(
                "{} minute, {} second{} {}",
                minutes, seconds, plural_seconds, direction
            );
        } else {
            return format!(
                "{} minutes, {} second{} {}",
                minutes, seconds, plural_seconds, direction
            );
        }
    }

    let hours = minutes / 60;
    minutes %= 60;
    let plural_minutes = if minutes == 1 { "" } else { "s" };

    if hours == 1 {
        format!(
            "{} hour, {} minute{} {}",
            hours, minutes, plural_minutes, direction
        )
    } else {
        format!(
            "{} hours, {} minute{} {}",
            hours, minutes, plural_minutes, direction
        )
    }
}

pub fn format_date_with_offset_in_original_timezone(t: i64, offset: i64) -> String {
    let offset_hours = offset / 3600;
    let offset_minutes = (offset % 3600) / 60;

    let dt = Utc.timestamp(t + offset, 0);
    let date_str = dt.format(DEFAULT_DATE_FORMAT).to_string();
    let offset_str = format!(" {:+03}{:02}", offset_hours, offset_minutes);

    date_str + &offset_str
}

pub fn format_date(
    t: i64,
    offset: Option<i64>,
    timezone: Timezone,
    date_fmt: Option<&str>,
    show_offset: bool,
) -> String {
    let (dt, offset_str) = match timezone {
        Timezone::Utc => (
            DateTime::from_utc(NaiveDateTime::from_timestamp(t, 0), Utc),
            if show_offset {
                " +0000".to_owned()
            } else {
                "".to_owned()
            },
        ),
        Timezone::Original => {
            let offset = offset.unwrap_or(0);
            let offset_str = if show_offset {
                let sign = if offset >= 0 { '+' } else { '-' };
                let hours = offset.abs() / 3600;
                let minutes = (offset.abs() / 60) % 60;
                format!(" {}{:02}{:02}", sign, hours, minutes)
            } else {
                "".to_owned()
            };
            (
                DateTime::from_utc(NaiveDateTime::from_timestamp(t + offset, 0), Utc),
                offset_str,
            )
        }
        Timezone::Local => {
            let local = Local.timestamp(t, 0);
            let offset = local.offset().local_minus_utc();
            let offset_str = if show_offset {
                let sign = if offset >= 0 { '+' } else { '-' };
                let hours = offset.abs() / 3600;
                let minutes = (offset.abs() / 60) % 60;
                format!(" {}{:02}{:02}", sign, hours, minutes)
            } else {
                "".to_owned()
            };
            (local.with_timezone(&Utc), offset_str)
        }
    };
    dt.format(date_fmt.unwrap_or(DEFAULT_DATE_FORMAT))
        .to_string()
        + &offset_str
}

pub fn format_highres_date(t: f64, offset: Option<i32>) -> String {
    let offset = offset.unwrap_or(0);
    let datetime = Utc.timestamp_opt(t as i64 + offset as i64, 0).unwrap();
    let highres_seconds = format!("{:.9}", t - t.floor())[1..].to_string();
    let offset_str = format!(" {:+03}{:02}", offset / 3600, (offset / 60) % 60);
    format!(
        "{}{}{}",
        datetime.format(DEFAULT_DATE_FORMAT),
        highres_seconds,
        offset_str
    )
}

const WEEKDAYS: [&str; 7] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

pub fn unpack_highres_date(date: &str) -> Result<(f64, i32), String> {
    let space_loc = date.find(' ');
    if space_loc.is_none() {
        return Err(format!(
            "date string does not contain a day of week: {}",
            date
        ));
    }
    let weekday = &date[..space_loc.unwrap()];
    if !WEEKDAYS.iter().any(|&d| d == weekday) {
        return Err(format!(
            "date string does not contain a valid day of week: {}",
            date
        ));
    }
    let dot_loc = date.find('.');
    if dot_loc.is_none() {
        return Err(format!(
            "Date string does not contain high-precision seconds: {}",
            date
        ));
    }
    let base_time_str = &date[space_loc.unwrap() + 1..dot_loc.unwrap()];
    let offset_loc = date[dot_loc.unwrap()..].find(' ');
    if offset_loc.is_none() {
        return Err(format!("Date string does not contain a timezone: {}", date));
    }
    let fract_seconds_str = &date[dot_loc.unwrap()..dot_loc.unwrap() + offset_loc.unwrap()];
    let offset_str = &date[dot_loc.unwrap() + 1 + offset_loc.unwrap()..];

    let base_time = Utc
        .datetime_from_str(base_time_str, "%Y-%m-%d %H:%M:%S")
        .map_err(|e| format!("Failed to parse datetime string ({}): {}", base_time_str, e))?;

    let fract_seconds = fract_seconds_str.parse::<f64>().map_err(|e| {
        format!(
            "Failed to parse high-precision seconds({}) : {}",
            fract_seconds_str, e
        )
    })?;

    let offset = offset_str
        .parse::<i32>()
        .map_err(|e| format!("Failed to parse offset ({}): {}", offset_str, e))?;

    let offset_hours = offset / 100;
    let offset_minutes = offset % 100;
    let seconds_offset = (offset_hours * 3600) + (offset_minutes * 60);

    let timestamp = base_time.timestamp() - seconds_offset as i64;
    let timestamp_with_fract_seconds = timestamp as f64 + fract_seconds;

    Ok((timestamp_with_fract_seconds, seconds_offset))
}

pub fn compact_date(when: u64) -> String {
    let system_time = Utc.timestamp(when as i64, 0);
    let date_time: DateTime<Utc> = system_time;
    date_time.format("%Y%m%d%H%M%S").to_string()
}
