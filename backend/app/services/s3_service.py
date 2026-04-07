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

