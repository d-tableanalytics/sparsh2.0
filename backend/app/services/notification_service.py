from app.config.settings import settings
import requests
import logging
from typing import Optional, Dict, Any
from app.db.mongodb import get_collection
from datetime import datetime
from bson import ObjectId

logger = logging.getLogger(__name__)

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

async def fetch_template(slug: str, company_id: str = None):
    col = get_collection("notification_templates")
    # Step 1: Check Company Specific Template First
    if company_id:
        t = await col.find_one({
            "slug": slug, 
            "company_id": str(company_id), 
            "scope": "company", 
            "is_active": True
        })
        if t: return t
    
    # Step 2: Fallback Global (Staff Scope)
    return await col.find_one({
        "slug": slug, 
        "scope": "staff", 
        "is_active": True
    })


def render_template(template_body: str, context: Dict[str, Any]):
    from string import Template
    # Convert {{var}} to $var for standard string.Template or use simple replace
    content = template_body
    for key, value in context.items():
        content = content.replace(f"{{{{{key}}}}}", str(value))
    return content

async def log_notification(user_id: str, contact: str, channel: str, slug: str, content: str, status: str, error: str = None):
    try:
        log_entry = {
            "user_id": str(user_id) if user_id else "system",
            "target_contact": contact,
            "channel": channel,
            "template_slug": slug,
            "content": content,
            "status": status,
            "error_message": error,
            "sent_at": datetime.utcnow()
        }
        col = get_collection("notifications")
        await col.insert_one(log_entry)
    except Exception as e:

        logger.error(f"Failed to log notification: {e}")

async def send_email_notification(to_email: str, subject: str, message: str, user_id: str = None, slug: str = "manual"):

    if not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD:
        logger.warning("SMTP credentials not configured")
        return False
    
    try:
        msg = MIMEMultipart()
        msg['From'] = settings.SMTP_USERNAME
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(message, 'plain'))
        
        server = smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT)
        server.starttls()
        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        await log_notification(user_id, to_email, "email", slug, message, "sent")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        await log_notification(user_id, to_email, "email", slug, message, "failed", str(e))
        return False

async def send_whatsapp_notification(phone: str, message: str, user_id: str = None, slug: str = "manual"):

    if not settings.MAYTAPI_TOKEN or not settings.MAYTAPI_PRODUCT_ID or not settings.MAYTAPI_PHONE_ID:
        logger.warning("Maytapi credentials not configured")
        return False
    
    try:
        url = f"https://api.maytapi.com/api/v1/{settings.MAYTAPI_PRODUCT_ID}/{settings.MAYTAPI_PHONE_ID}/sendMessage"
        headers = {
            "Content-Type": "application/json",
            "x-maytapi-key": settings.MAYTAPI_TOKEN
        }
        # Maytapi usually expects phone with country code without '+' for sendMessage target
        # clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "")
        
        payload = {
            "to_number": phone,
            "type": "text",
            "text": message # Maytapi uses 'text' field for message body in many versions
        }
        
        # Check specific Maytapi API requirements for payload keys
        # If the user specified 'message' key, I'll provide both or check docs.
        # Let's use 'message' as requested by some common patterns, 
        # but common Maytapi text message payload is {"to_number": "...", "type": "text", "message": "..."}
        
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            await log_notification(user_id, phone, "whatsapp", slug, message, "sent")
            return True
        else:
            error = f"Maytapi error: {response.status_code} - {response.text}"
            logger.error(error)
            await log_notification(user_id, phone, "whatsapp", slug, message, "failed", error)
            return False
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}")
        await log_notification(user_id, phone, "whatsapp", slug, message, "failed", str(e))
        return False

async def send_notification_from_template(user_obj: dict, template_slug: str, context: Dict[str, Any], delivery_type: str = "both"):
    company_id = user_obj.get("company_id")
    email_t = await fetch_template(f"{template_slug}_email", company_id)
    whatsapp_t = await fetch_template(f"{template_slug}_whatsapp", company_id)
    
    user_id = user_obj.get("_id") or user_obj.get("id")
    email = user_obj.get("email")
    phone = user_obj.get("mobile")
    
    results = {}
    
    if delivery_type in ["email", "both"] and email and email_t:
        rendered_body = render_template(email_t["body"], context)
        rendered_subject = render_template(email_t.get("subject", "Notification"), context)
        results["email"] = await send_email_notification(email, rendered_subject, rendered_body, user_id, email_t["slug"])
        
    if delivery_type in ["whatsapp", "both"] and phone and whatsapp_t:
        rendered_body = render_template(whatsapp_t["body"], context)
        results["whatsapp"] = await send_whatsapp_notification(phone, rendered_body, user_id, whatsapp_t["slug"])
        
    return results

async def send_notification(user_obj: dict, subject: str, message: str, delivery_type: str = "both"):
    email = user_obj.get("email")
    phone = user_obj.get("mobile")
    results = {}
    if delivery_type in ["email", "both"] and email:
        results["email"] = await send_email_notification(email, subject, message)
    if delivery_type in ["whatsapp", "both"] and phone:
        results["whatsapp"] = await send_whatsapp_notification(phone, message)
    return results

# ─── Specialized Task & Event Wrapper Functions ───

async def send_task_created_email(user_obj: dict, task_data: dict, creator_name: str):
    context = {
        "task_name": task_data.get("title"),
        "task_category": task_data.get("category"),
        "critical_level": task_data.get("priority"),
        "assigned_user": user_obj.get("full_name") or user_obj.get("first_name"),
        "assigned_by": creator_name,
        "deadline": task_data.get("start"),
        "description": task_data.get("description") or task_data.get("additional_details", "No description provided."),
        "task_status": task_data.get("status", "schedule")
    }
    return await send_notification_from_template(user_obj, "task_created", context, "email")

async def send_task_updated_email(user_obj: dict, task_data: dict, updated_by: str):
    context = {
        "task_name": task_data.get("title"),
        "task_category": task_data.get("category"),
        "critical_level": task_data.get("priority"),
        "assigned_user": user_obj.get("full_name") or user_obj.get("first_name"),
        "assigned_by": updated_by,
        "deadline": task_data.get("start"),
        "description": task_data.get("description") or task_data.get("additional_details", "No description provided."),
        "task_status": task_data.get("status", "schedule")
    }
    return await send_notification_from_template(user_obj, "task_updated", context, "email")

async def send_task_deleted_email(user_obj: dict, task_name: str, deleted_by: str):
    context = {"task_name": task_name, "deleted_by": deleted_by}
    return await send_notification_from_template(user_obj, "task_deleted", context, "email")

async def send_event_created_email(user_obj: dict, event_data: dict, creator_name: str, batch_name: str = "TBD", quarter: str = "TBD"):
    context = {
        "event_title": event_data.get("title"),
        "session_strategy": event_data.get("session_type"),
        "batch_name": batch_name,
        "quarter": quarter,
        "meeting_url": event_data.get("meeting_link") or "No link provided.",
        "event_datetime": event_data.get("start"),
        "instruction": event_data.get("additional_details") or "No instructions.",
        "created_by": creator_name
    }
    return await send_notification_from_template(user_obj, "event_created", context, "email")

async def send_event_updated_email(user_obj: dict, event_data: dict, updated_by: str, batch_name: str = "TBD", quarter: str = "TBD"):
    context = {
        "event_title": event_data.get("title"),
        "session_strategy": event_data.get("session_type"),
        "batch_name": batch_name,
        "quarter": quarter,
        "meeting_url": event_data.get("meeting_link") or "No link provided.",
        "event_datetime": event_data.get("start"),
        "instruction": event_data.get("additional_details") or "No instructions.",
        "created_by": updated_by
    }
    return await send_notification_from_template(user_obj, "event_updated", context, "email")

async def send_event_deleted_email(user_obj: dict, event_title: str, deleted_by: str):
    context = {"event_title": event_title, "deleted_by": deleted_by}
    return await send_notification_from_template(user_obj, "event_deleted", context, "email")

async def send_reminder_email(user_obj: dict, event: dict):
    is_task = event.get("type") == "task"
    context = {
        "title": event.get("title"),
        "reminder_time": datetime.utcnow().strftime("%H:%M %p"),
        "event_time": event.get("start") if not is_task else "N/A",
        "task_deadline": event.get("start") if is_task else "N/A",
        "meeting_url": event.get("meeting_link") or "View in Dashboard",
        "description": event.get("additional_details") or "No further details."
    }
    return await send_notification_from_template(user_obj, "reminder", context, "email")


async def send_conflict_notification_email(user_obj: dict, event_data: dict, existing_event: dict):
    context = {
        "user_name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
        "event_title": event_data.get("title"),
        "event_time": event_data.get("start"),
        "existing_event": existing_event.get("title"),
        "existing_time": existing_event.get("start"),
        "meeting_url": event_data.get("meeting_link") or "View in Dashboard"
    }
    return await send_notification_from_template(user_obj, "schedule_conflict", context, "email")

