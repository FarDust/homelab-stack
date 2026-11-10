# Testing local models can read gigabytes from the model store

Loading an uncached model from a bucket-backed volume (the rclone volume plugin) reads the whole weights file through the bucket, and that read is billed as egress. Comparing four candidate models on one node read about 17 GB, and about 2 GB more on a second node: roughly 0.75 USD at a 0.04 USD/GiB cross-region rate, and up to about 2.2 USD at the 0.12 USD/GB list rate.

## Rules

- Prefer candidates already cached on node-local disk, or pull test models into node-local storage instead of the bucket-backed store.
- Budget a test before it starts: model sizes times nodes that will load them times the applicable rate.
- Registry and model-hub downloads are ingress and free; only reads from the bucket cost.
- A production fallback service should read weights from local disk only, so a restart never reaches the bucket.
- Loading a large model can raise node load for minutes on a node shared with other workloads; do not test on a node that serves latency-sensitive work.

## Related

- [Local text-only fallback design](litellm-local-text-only-fallback-design.md)
- [rclone Docker plugin recovery](rclone.md)

Entities: [[rclone Volume Plugin]], [[Ollama]]
