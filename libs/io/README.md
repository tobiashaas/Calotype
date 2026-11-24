# calotype-io

The blob store: previews and models in an S3-compatible bucket (`S3BlobStore`, configured by
`S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`) or in memory for tests
(`MemoryBlobStore`). It owns the object key layout (`photos/{id}.jpg`,
`models/{profile}/model-{version}.joblib`). Imports: stdlib and boto3 only (ADR 007).
