from __future__ import annotations

from google.api_core.exceptions import Forbidden, NotFound
from google.cloud import storage


PROJECT_ID = "paperlens-dev-26"
BUCKET_NAME = "paperlens-dev-26-paper-storage"


def main() -> None:
    client = storage.Client(project=PROJECT_ID)

    try:
        bucket = client.get_bucket(BUCKET_NAME)
    except NotFound as exc:
        raise RuntimeError(
            f"Bucket {BUCKET_NAME!r} does not exist. "
            "Create it or update BUCKET_NAME."
        ) from exc
    except Forbidden as exc:
        raise RuntimeError(
            f"Your account cannot access bucket {BUCKET_NAME!r}."
        ) from exc

    object_name = "test/authentication-test.txt"
    blob = bucket.blob(object_name)

    blob.upload_from_string(
        "PaperLens authentication works.",
        content_type="text/plain",
    )

    print(f"Uploaded to gs://{BUCKET_NAME}/{object_name}")
    print(f"Downloaded content: {blob.download_as_text()}")

    blob.delete()
    print("Deleted test object.")


if __name__ == "__main__":
    main()