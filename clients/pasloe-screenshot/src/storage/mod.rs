mod local;
mod s3;

pub use local::LocalStorage;
pub use s3::S3Storage;

use crate::config::StorageConfig;
use crate::event::CaptureResult;
use crate::pasloe_client::PasloeClient;
use anyhow::Result;
use async_trait::async_trait;

#[async_trait]
pub trait Storage: Send + Sync {
    async fn save(&self, capture: &CaptureResult) -> Result<String>;
}

pub struct StorageManager {
    storages: Vec<Box<dyn Storage>>,
}

impl StorageManager {
    pub fn new(config: &StorageConfig, client: PasloeClient) -> Result<Self> {
        let mut storages: Vec<Box<dyn Storage>> = Vec::new();

        if config.local.enable {
            storages.push(Box::new(LocalStorage::new(&config.local)?));
        }

        if config.s3.enable {
            storages.push(Box::new(S3Storage::new(&config.s3, client)?));
        }

        Ok(Self { storages })
    }

    pub async fn save(&self, capture: &CaptureResult) -> Result<String> {
        let mut url = String::new();
        for storage in &self.storages {
            url = storage.save(capture).await?;
        }
        Ok(url)
    }
}
