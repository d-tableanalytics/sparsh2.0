import boto3
import uuid
from app.config.settings import settings

def get_s3_client():
    return boto3.client(
        's3',
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION
    )

def get_signed_url(s3_key: str, expires_in: int = 3600) -> str:
    """
    Generate a pre-signed URL for an S3 object to allow secure temporary access.
    """
    s3_client = get_s3_client()
    try:
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': settings.S3_BUCKET_NAME, 'Key': s3_key},
            ExpiresIn=expires_in
        )
        return url
    except Exception as e:
        print(f"Error generating signed URL: {e}")
        return ""

def upload_file_to_s3(file_obj, filename: str, content_type: str) -> str:
    s3_client = get_s3_client()
    bucket_name = settings.S3_BUCKET_NAME

    unique_filename = f"{uuid.uuid4()}_{filename}"

    s3_client.upload_fileobj(
        file_obj,
        bucket_name,
        unique_filename,
        ExtraArgs={
            "ContentType": content_type
        }
    )

    # Return a fresh signed URL for the newly uploaded file
    return get_signed_url(unique_filename)


def upload_file_to_s3_with_key(file_obj, filename: str, content_type: str) -> dict:
    """Upload a file and return both the persistent S3 key and a fresh signed URL.

    Use this when the caller needs to store a long-lived reference: signed URLs
    expire, so persist the key and regenerate URLs on demand via get_signed_url.
    """
    s3_client = get_s3_client()
    bucket_name = settings.S3_BUCKET_NAME

    unique_filename = f"{uuid.uuid4()}_{filename}"

    s3_client.upload_fileobj(
        file_obj,
        bucket_name,
        unique_filename,
        ExtraArgs={"ContentType": content_type},
    )

    return {"key": unique_filename, "url": get_signed_url(unique_filename)}


def download_file_from_s3(s3_key: str, local_path: str) -> bool:
    """Download an S3 object to a local path. Used when we need the raw bytes
    of a media-library file (e.g. to transcribe audio/video already in S3)."""
    s3_client = get_s3_client()
    try:
        s3_client.download_file(settings.S3_BUCKET_NAME, s3_key, local_path)
        return True
    except Exception as e:
        print(f"Error downloading S3 object {s3_key}: {e}")
        return False


def delete_file_from_s3(s3_key: str) -> bool:
    """Delete an object from S3 by its key. Returns True on success."""
    if not s3_key:
        return False
    s3_client = get_s3_client()
    try:
        s3_client.delete_object(Bucket=settings.S3_BUCKET_NAME, Key=s3_key)
        return True
    except Exception as e:
        print(f"Error deleting S3 object {s3_key}: {e}")
        return False

def create_multipart_upload(filename: str, content_type: str) -> dict:
    """Initialize a multipart upload and return the UploadId and generated S3 Key."""
    s3_client = get_s3_client()
    unique_filename = f"{uuid.uuid4()}_{filename}"
    res = s3_client.create_multipart_upload(
        Bucket=settings.S3_BUCKET_NAME,
        Key=unique_filename,
        ContentType=content_type
    )
    return {
        "upload_id": res["UploadId"],
        "key": unique_filename
    }

def upload_part(key: str, upload_id: str, part_number: int, file_obj) -> dict:
    """Upload a single chunk/part to an ongoing multipart upload."""
    s3_client = get_s3_client()
    res = s3_client.upload_part(
        Bucket=settings.S3_BUCKET_NAME,
        Key=key,
        PartNumber=part_number,
        UploadId=upload_id,
        Body=file_obj
    )
    return {"ETag": res["ETag"], "PartNumber": part_number}

def complete_multipart_upload(key: str, upload_id: str, parts: list) -> dict:
    """Complete the multipart upload once all parts are uploaded."""
    s3_client = get_s3_client()
    
    # Parts must be sorted by PartNumber
    sorted_parts = sorted(parts, key=lambda x: int(x["PartNumber"]))
    
    s3_client.complete_multipart_upload(
        Bucket=settings.S3_BUCKET_NAME,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={'Parts': sorted_parts}
    )
    return {"key": key, "url": get_signed_url(key)}

def abort_multipart_upload(key: str, upload_id: str) -> bool:
    """Abort an ongoing multipart upload to free up partial storage."""
    s3_client = get_s3_client()
    try:
        s3_client.abort_multipart_upload(
            Bucket=settings.S3_BUCKET_NAME,
            Key=key,
            UploadId=upload_id
        )
        return True
    except Exception as e:
        print(f"Error aborting multipart upload {upload_id}: {e}")
        return False

