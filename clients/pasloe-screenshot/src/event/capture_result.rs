use chrono::{DateTime, Utc};
use image::RgbaImage;

pub struct CaptureResult {
    pub monitor_id: String,
    pub image: RgbaImage,
    pub timestamp: DateTime<Utc>,
}

impl CaptureResult {
    pub fn new(monitor_id: String, image: RgbaImage, timestamp: DateTime<Utc>) -> Self {
        Self {
            monitor_id,
            image,
            timestamp,
        }
    }
}
