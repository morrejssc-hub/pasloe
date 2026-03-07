use crate::pasloe_client::ScreenshotEvent;
use anyhow::{Context, Result};

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
            // 重复事件，忽略
            return Ok(());
        }
        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            anyhow::bail!("pasloe returned {}: {}", status, body);
        }
        Ok(())
    }
}
