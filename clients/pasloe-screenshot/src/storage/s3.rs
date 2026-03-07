use crate::config::S3Config;
use crate::event::CaptureResult;
use crate::storage::Storage;
use anyhow::Result;
use async_trait::async_trait;
use s3::creds::Credentials;
use s3::{Bucket, Region};

pub struct S3Storage {
    bucket: Bucket,
    prefix: String,
}

impl S3Storage {
    pub fn new(config: &S3Config) -> Result<Self> {
        let region = Region::Custom {
            region: config.region.clone(),
            endpoint: config.endpoint.clone(),
        };
        let credentials = Credentials::new(
            Some(&config.access_key),
            Some(&config.secret_key),
            None,
            None,
            None,
        )?;
        let bucket = Bucket::new(&config.bucket, region, credentials)?;
        Ok(Self { bucket, prefix: config.prefix.clone() })
    }
}

#[async_trait]
impl Storage for S3Storage {
    async fn save(&self, capture: &CaptureResult) -> Result<String> {
        let key = format!(
            "{}{}_{}.png",
            self.prefix,
            capture.monitor_id,
            capture.timestamp.format("%Y%m%d_%H%M%S_%3f")
        );

        let mut buffer = Vec::new();
        capture.image.save_with_format(
            &mut std::io::Cursor::new(&mut buffer),
            image::ImageFormat::Png,
        )?;

        self.bucket.put_object(&key, &buffer).await?;
        Ok(format!("{}/{}", self.bucket.url(), key))
    }
}
