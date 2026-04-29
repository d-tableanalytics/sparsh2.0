import os
import asyncio
import subprocess
import tempfile
import uuid
from datetime import datetime
from bson import ObjectId
from app.db.mongodb import get_collection
from app.services.s3_service import get_s3_client, get_signed_url
from app.services.event_sync_service import sync_event_to_collection
from app.config.settings import settings
from boto3.s3.transfer import TransferConfig
import speech_recognition as sr

async def upload_large_file_to_s3(local_path: str, filename: str, content_type: str) -> str:
    s3_client = get_s3_client()
    bucket_name = settings.S3_BUCKET_NAME
    unique_filename = f"{uuid.uuid4()}_{filename}"
    
    config = TransferConfig(
        multipart_threshold=8 * 1024 * 1024,
        max_concurrency=10,
        multipart_chunksize=8 * 1024 * 1024,
        use_threads=True
    )
    
    loop = asyncio.get_event_loop()
    def _upload():
        s3_client.upload_file(
            local_path,
            bucket_name,
            unique_filename,
            ExtraArgs={"ContentType": content_type},
            Config=config
        )
    await loop.run_in_executor(None, _upload)
    
    return get_signed_url(unique_filename)


def sync_transcribe_wav(filepath: str) -> str:
    recognizer = sr.Recognizer()
    with sr.AudioFile(filepath) as source:
        audio = recognizer.record(source)
    try:
        return recognizer.recognize_google(audio)
    except sr.UnknownValueError:
        return "" 
    except sr.RequestError as e:
        print(f"Google SR request error: {e}")
        return ""

async def transcribe_audio_chunk(filepath: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sync_transcribe_wav, filepath)

async def transcribe_media_file(local_file_path: str, progress_callback=None) -> str:
    """
    General purpose transcription for audio/video files.
    """
    final_transcription = ""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Segment exactly 60 seconds of 16kHz mono audio
        out_pattern = os.path.join(temp_dir, "chunk_%04d.wav")
        cmd = [
            "ffmpeg", "-i", local_file_path, 
            "-f", "segment", "-segment_time", "60", 
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            "-vn", out_pattern
        ]
        
        # Run FFmpeg
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        
        chunks = sorted([f for f in os.listdir(temp_dir) if f.startswith("chunk_") and f.endswith(".wav")])
        
        if chunks:
            valid_texts = []
            total_chunks = len(chunks)
            
            # Process sequentially or in smaller batches to report progress
            batch_size = 5
            for i in range(0, total_chunks, batch_size):
                batch = chunks[i:i+batch_size]
                tasks = [transcribe_audio_chunk(os.path.join(temp_dir, cf)) for cf in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for res in results:
                    if not isinstance(res, Exception) and res:
                        valid_texts.append(res)
                        
                if progress_callback:
                    # Report progress from 10% (ffmpeg done) up to 90%
                    percent = 10 + int(80 * min(i + batch_size, total_chunks) / total_chunks)
                    await progress_callback(percent)
            
            
            final_transcription = " ".join(valid_texts)
    return final_transcription

async def process_background_upload_and_transcribe(
    event_id: str, 
    resource_id: str,
    local_file_path: str, 
    filename: str, 
    content_type: str, 
    system_type: str,
    col_name: str = "calendar_events"
):
    try:
        col = get_collection(col_name)
        
        async def update_progress(percent: int):
            await col.update_one(
                {"_id": ObjectId(event_id), "resources.id": resource_id},
                {"$set": {"resources.$.progress": percent}}
            )

        # Start at 5% to indicate processing has begun
        await update_progress(5)

        # 1. Start S3 Upload in background
        s3_task = asyncio.create_task(upload_large_file_to_s3(local_file_path, filename, content_type))

        final_transcription = None
        if system_type in ["audio", "video"]:
            print(f"[{resource_id}] Starting Fast Transcription Pipeline...")
            final_transcription = await transcribe_media_file(local_file_path, update_progress)
        
        # Set to 95% while waiting for upload to finish
        await update_progress(95)
        
        # 2. Wait for S3 Upload to finish
        url = await s3_task

        # 3. Finalize
        update_doc = {
            "resources.$.status": "ready",
            "resources.$.url": url,
            "resources.$.progress": 100,
            "updated_at": datetime.utcnow()
        }
        if final_transcription:
            update_doc["resources.$.transcription"] = final_transcription
            
        await col.update_one(
            {"_id": ObjectId(event_id), "resources.id": resource_id},
            {"$set": update_doc}
        )
        print(f"[{resource_id}] Pipeline Complete!")
        await sync_event_to_collection(event_id)

    except Exception as e:
        print(f"[{resource_id}] Background Error: {e}")
        col = get_collection("calendar_events")
        await col.update_one(
            {"_id": ObjectId(event_id), "resources.id": resource_id},
            {"$set": {"resources.$.status": "failed", "resources.$.error": str(e)}}
        )
    finally:
        if os.path.exists(local_file_path):
            try:
                os.remove(local_file_path)
            except Exception:
                pass
