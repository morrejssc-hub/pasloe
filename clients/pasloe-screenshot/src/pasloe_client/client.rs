use crate::pasloe_client::ScreenshotEvent;
use anyhow::{Context, Result};

use serde::Deserialize;

#[derive(Debug, Deserialize)]
pub struct PresignResponse {
    pub upload_url: String,
    pub access_url: String,
    pub object_name: String,
}

#[derive(Clone)]
pub struct PasloeClient {
    base_url: String,
    api_key: String,
    client: reqwest::Client,
}

impl PasloeClient {
    pub fn new(base_url: String, api_key: String) -> Self {
        Self {
            base_url,
            api_key,
            client: reqwest::Client::new(),
        }
    }

    pub async fn send_event(&self, event: &ScreenshotEvent) -> Result<()> {
        let url = format!("{}/events", self.base_url);
        let resp = self
            .client
            .post(&url)
            .header("X-API-Key", &self.api_key)
            .json(event)
            .send()
            .await
            .context("Failed to send event to pasloe")?;

        let status = resp.status();
        if status == 409 {
            return Ok(());
        }
        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            anyhow::bail!("pasloe returned {}: {}", status, body);
        }
        Ok(())
    }

    pub async fn get_presigned_url(&self, filename: &str, content_type: &str) -> Result<PresignResponse> {
        let url = format!("{}/artifacts/presign", self.base_url);
        let resp = self.client.post(&url)
            .header("X-API-Key", &self.api_key)
            .json(&serde_json::json!({
                "filename": filename,
                "content_type": content_type
            }))
            .send().await
            .context("Failed to request presigned URL")?;
        
        let status = resp.status();
        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            anyhow::bail!("Failed to get presigned URL: {}", body);
        }
        Ok(resp.json().await?)
    }

    pub async fn upload_image(&self, upload_url: &str, data: Vec<u8>, content_type: &str) -> Result<()> {
        let resp = self.client.put(upload_url)
            .header("Content-Type", content_type)
            .body(data)
            .send().await
            .context("Failed to upload image")?;
            
        let status = resp.status();
        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            anyhow::bail!("Failed to upload image: {}", body);
        }
        Ok(())
    }
}
