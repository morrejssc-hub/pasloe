use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// 发送到 pasloe 的截图事件
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScreenshotEvent {
    pub source: String,
    pub kind: String,
    pub payload: ScreenshotPayload,
    pub tags: Vec<String>,
    pub ts: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScreenshotPayload {
    pub url: String,
    pub monitor_id: String,
}

impl ScreenshotEvent {
    pub fn new(url: String, monitor_id: String, timestamp: DateTime<Utc>) -> Self {
        Self {
            source: "pasloe-screenshot".to_string(),
            kind: "screenshot.captured".to_string(),
            payload: ScreenshotPayload { url, monitor_id },
            tags: vec!["screenshot".to_string(), "activity".to_string()],
            ts: timestamp,
        }
    }
}
