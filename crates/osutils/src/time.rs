use std::time::{SystemTime, UNIX_EPOCH};
use chrono::{DateTime, Local, TimeZone, Utc, FixedOffset};

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
    let dt: DateTime<FixedOffset> = tz.timestamp(t, 0);
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
