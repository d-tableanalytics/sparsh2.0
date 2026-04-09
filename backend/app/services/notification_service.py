from app.config.settings import settings
import requests
import logging
from typing import Optional, Dict, Any
from app.db.mongodb import get_collection
from datetime import datetime
from bson import ObjectId
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import asyncio

logger = logging.getLogger(__name__)

SESSION_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 0; background-color: #f9f9f9; }
        .container { max-width: 600px; margin: 20px auto; background: #ffffff; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 10px rgba(0,0,0,0.05); }
        .header { background-color: #00684a; color: #ffffff; padding: 20px; text-align: center; }
        .header h1 { margin: 0; font-size: 24px; font-weight: 700; }
        .content { padding: 30px; }
        .footer { padding: 20px; text-align: center; border-top: 1px solid #eeeeee; background-color: #fafafa; }
        .session-type { font-weight: bold; }
        .meeting-link { display: block; margin: 15px 0; color: #1a73e8; font-weight: bold; text-decoration: none; word-break: break-all; }
        .details-header { font-size: 16px; font-weight: 800; color: #00684a; border-bottom: 2px solid #00684a; margin-top: 25px; margin-bottom: 15px; padding-bottom: 5px; }
        .details-table { width: 100%; border-collapse: collapse; }
        .details-table td { padding: 8px 0; font-size: 14px; }
        .details-label { width: 80px; font-weight: bold; color: #666; }
        .details-value { font-weight: bold; }
        .time-value { color: #d32f2f; }
        .important-box { background-color: #fdf5d7; border: 1px solid #fbe8a1; border-radius: 6px; padding: 15px; margin-top: 25px; font-size: 14px; }
        .important-box strong { color: #856404; }
        .regards { margin-top: 25px; color: #555; font-size: 14px; }
        .team-name { color: #00684a; font-weight: 900; font-size: 18px; margin: 5px 0; }
        .website { font-size: 12px; color: #888; text-decoration: none; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Greetings from Sparsh Magic!</h1>
        </div>
        <div class="content">
            <p>Hello,</p>
            <p>This is to inform you that the <span class="session-type">{{session_type}}</span> session has been scheduled.</p>
            <p><strong>Please join the session using the link below:</strong></p><a href="{{meeting_link}}" class="meeting-link">{{meeting_link}}</a>
            
            <div class="details-header">SESSION DETAILS</div>
            <table class="details-table">
                <tr>
                    <td class="details-label">Topic:</td>
                    <td class="details-value">{{topic}}</td>
                </tr>
                <tr>
                    <td class="details-label">Date:</td>
                    <td class="details-value">{{date}}</td>
                </tr>
                <tr>
                    <td class="details-label">Day:</td>
                    <td class="details-value">{{day}}</td>
                </tr>
                <tr>
                    <td class="details-label">Time:</td>
                    <td class="details-value time-value">{{time}}</td>
                </tr>
            </table>

            <div class="important-box"><strong>IMPORTANT:</strong> Kindly join on time and ensure you are on camera during the meeting.</div>

            <div class="regards">
                With Best Regards,<br>
                <div class="team-name">Sparsh Magic Team</div>
                Website - <a href="https://www.sparshmagic.com" class="website">www.sparshmagic.com</a>
            </div>
        </div>
    </div>
</body>
</html>"""

CONFLICT_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 0; background-color: #fff4f4; }
        .container { max-width: 600px; margin: 20px auto; background: #ffffff; border: 2px solid #ffcccc; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(220, 53, 69, 0.1); }
        .header { background-color: #dc3545; color: #ffffff; padding: 25px; text-align: center; }
        .header h1 { margin: 0; font-size: 22px; font-weight: 900; text-transform: uppercase; letter-spacing: 2px; }
        .content { padding: 30px; }
        .conflict-box { background-color: #fff8f8; border: 1px solid #ffdfdf; border-radius: 8px; padding: 20px; margin: 20px 0; }
        .event-title { font-weight: 800; color: #dc3545; font-size: 16px; }
        .time-label { font-size: 12px; color: #888; text-transform: uppercase; font-weight: bold; margin-top: 10px; display: block; }
        .time-value { font-size: 14px; font-weight: 700; color: #333; }
        .divider { border: 0; border-top: 2px dashed #ffdfdf; margin: 20px 0; }
        .action-btn { display: inline-block; padding: 12px 25px; background-color: #dc3545; color: #ffffff; text-decoration: none; border-radius: 6px; font-weight: 800; text-transform: uppercase; font-size: 12px; letter-spacing: 1px; margin-top: 20px; }
        .footer { padding: 20px; text-align: center; font-size: 11px; color: #999; border-top: 1px solid #eeeeee; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚠️ Schedule Conflict Detected</h1>
        </div>
        <div class="content">
            <p>Hello <strong>{{user_name}}</strong>,</p>
            <p>Our scheduling engine has detected a timing overlap in your calendar. To maintain operational flow, one of these entries requires rescheduling.</p>
            
            <div class="conflict-box">
                <span class="time-label">New Entry [Conflict Caused By]:</span>
                <div class="event-title">{{event_title}}</div>
                <div class="time-value">{{event_time}}</div>
                
                <hr class="divider">
                
                <span class="time-label">Existing Entry [Overlapped]:</span>
                <div class="event-title">{{existing_event}}</div>
                <div class="time-value">{{existing_time}}</div>
            </div>

            <p>Please log in to the <strong>Sparsh ERP Dashboard</strong> to resolve this conflict immediately.</p>
            <center><a href="https://sparshmagic.com/calendar" class="action-btn">Resolve Conflict Now</a></center>

            <p style="font-size: 12px; color: #666; margin-top: 30px; font-style: italic;">Note: A copy of this notification has been sent to your registered organization for coordination.</p>
        </div>
        <div class="footer">
            © 2026 Sparsh Magic Operational Support • Automatic System Alert
        </div>
    </div>
</body>
</html>"""

DEFAULT_TEMPLATES = {
    "user_creation_email": {
        "subject": "Welcome to Sparsh 2.0 - Your Account Details",
        "body": "Hello {{name}},\n\nWelcome to Sparsh 2.0! Your account has been created successfully.\n\nCredentials:\nEmail: {{email}}\nTemporary Password: {{password}}\n\nYou can login here: {{login_url}}\n\nRegards,\nTeam Sparsh"
    },
    "task_created_email": {
        "subject": "New Task Assigned: {{task_name}}",
        "body": "Hello {{assigned_user}},\n\nA new task '{{task_name}}' has been assigned to you by {{assigned_by}}.\n\nDeadline: {{deadline}}\nPriority: {{critical_level}}\nDescription: {{description}}\n\nRegards,\nSparsh Notifications"
    },
    "event_created_email": {
        "subject": "Session Scheduled: {{event_title}}",
        "body": SESSION_HTML_TEMPLATE
    }
}

async def fetch_template(slug: str, company_id: str = None):
    col = get_collection("notification_templates")
    if company_id:
        t = await col.find_one({
            "slug": slug, 
            "company_id": str(company_id), 
            "scope": "company", 
            "is_active": True
        })
        if t: return t
    
    res = await col.find_one({
        "slug": slug, 
        "scope": "staff", 
        "is_active": True
    })
    if res: return res
    return DEFAULT_TEMPLATES.get(slug)

def render_template(template_body: str, context: Dict[str, Any]):
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
        msg.attach(MIMEText(message, 'html'))
        
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
        headers = {"Content-Type": "application/json", "x-maytapi-key": settings.MAYTAPI_TOKEN}
        payload = {"to_number": phone, "type": "text", "text": message}
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
        results["email"] = await send_email_notification(email, rendered_subject, rendered_body, user_id, email_t.get("slug", f"{template_slug}_email"))
    if delivery_type in ["whatsapp", "both"] and phone and whatsapp_t:
        rendered_body = render_template(whatsapp_t["body"], context)
        results["whatsapp"] = await send_whatsapp_notification(phone, rendered_body, user_id, whatsapp_t.get("slug", f"{template_slug}_whatsapp"))
    return results

def format_datetime_standard(dt_str: str) -> str:
    if not dt_str: return "TBD"
    try:
        if isinstance(dt_str, datetime):
            dt = dt_str
        else:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y, %I:%M %p")
    except Exception as e:
        logger.error(f"Date parsing error for {dt_str}: {e}")
        return dt_str

async def send_notification(user_obj: dict, subject: str, message: str, delivery_type: str = "both"):
    email = user_obj.get("email")
    phone = user_obj.get("mobile")
    results = {}
    if delivery_type in ["email", "both"] and email:
        results["email"] = await send_email_notification(email, subject, message)
    if delivery_type in ["whatsapp", "both"] and phone:
        results["whatsapp"] = await send_whatsapp_notification(phone, message)
    return results

async def send_task_created_email(user_obj: dict, task_data: dict, creator_name: str):
    dt_str = task_data.get("start", "")
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        parsed_date = dt.strftime("%d %b %Y")
        parsed_day = dt.strftime("%A")
        parsed_time = dt.strftime("%I:%M %p")
    except:
        parsed_date = parsed_day = parsed_time = dt_str

    context = {
        "task_name": task_data.get("title"),
        "topic": task_data.get("title"), 
        "task_category": task_data.get("category"),
        "critical_level": task_data.get("priority"),
        "assigned_user": user_obj.get("full_name") or user_obj.get("first_name"),
        "assigned_by": creator_name,
        "deadline": format_datetime_standard(dt_str),
        "date": parsed_date,
        "day": parsed_day,
        "time": parsed_time,
        "description": task_data.get("description") or task_data.get("additional_details", "No description provided."),
        "task_status": task_data.get("status", "schedule"),
        "session_type": "Task"
    }
    return await send_notification_from_template(user_obj, "task_created", context, "email")

async def send_task_updated_email(user_obj: dict, task_data: dict, updated_by: str):
    dt_str = task_data.get("start", "")
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        parsed_date = dt.strftime("%d %b %Y")
        parsed_day = dt.strftime("%A")
        parsed_time = dt.strftime("%I:%M %p")
    except:
        parsed_date = parsed_day = parsed_time = dt_str

    context = {
        "task_name": task_data.get("title"),
        "topic": task_data.get("title"), 
        "task_category": task_data.get("category"),
        "critical_level": task_data.get("priority"),
        "assigned_user": user_obj.get("full_name") or user_obj.get("first_name"),
        "assigned_by": updated_by,
        "deadline": format_datetime_standard(dt_str),
        "date": parsed_date,
        "day": parsed_day,
        "time": parsed_time,
        "description": task_data.get("description") or task_data.get("additional_details", "No description provided."),
        "task_status": task_data.get("status", "schedule"),
        "session_type": "Task Update"
    }
    return await send_notification_from_template(user_obj, "task_updated", context, "email")

async def send_task_deleted_email(user_obj: dict, task_name: str, deleted_by: str):
    context = {"task_name": task_name, "deleted_by": deleted_by}
    return await send_notification_from_template(user_obj, "task_deleted", context, "email")

async def send_user_updated_email(user_obj: dict, updated_by: str):
    context = {
        "name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
        "email": user_obj.get("email"),
        "updated_by": updated_by,
        "login_url": "https://sparsh.app/login"
    }
    return await send_notification_from_template(user_obj, "user_edit", context, "email")

async def send_access_control_email(user_obj: dict, new_role: str, updated_by: str):
    context = {
        "name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
        "new_role": new_role,
        "updated_by": updated_by,
        "login_url": "https://sparsh.app/login"
    }
    return await send_notification_from_template(user_obj, "user_access_control_change", context, "email")

async def send_company_registration_email(admin_obj: dict, company_name: str, raw_password: str):
    context = {
        "name": admin_obj.get("first_name", "Admin"),
        "company_name": company_name,
        "email": admin_obj.get("email"),
        "password": raw_password,
        "login_url": "https://sparsh.app/login"
    }
    return await send_notification_from_template(admin_obj, "company_registration", context, "email")

async def send_event_created_email(user_obj: dict, event_data: dict, creator_name: str, batch_name: str = "TBD", quarter: str = "TBD"):
    try:
        dt_str = event_data.get("start", "")
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        context = {
            "session_type": event_data.get("session_type") or event_data.get("type", "General"),
            "meeting_link": event_data.get("meeting_link") or "No link provided.",
            "topic": event_data.get("title"),
            "date": dt.strftime("%d %b %Y"),
            "day": dt.strftime("%A"),
            "time": dt.strftime("%I:%M %p"),
            "description": event_data.get("additional_details") or "No instructions.",
            "event_title": event_data.get("title"),
            "session_strategy": event_data.get("session_type"),
            "batch_name": batch_name,
            "quarter": quarter,
            "event_datetime": dt.strftime("%d %b %Y, %I:%M %p"),
            "instruction": event_data.get("additional_details") or "No instructions.",
            "created_by": creator_name,
            "user_name": user_obj.get("full_name") or user_obj.get("first_name", "User")
        }
    except Exception as e:
        logger.error(f"Error parsing date for email: {e}")
        context = {"session_type": "Session", "meeting_link": event_data.get("meeting_link", ""), "topic": event_data.get("title"), "date": "TBD", "day": "TBD", "time": "TBD", "description": ""}
    return await send_notification_from_template(user_obj, "event_created", context, "email")

async def send_event_updated_email(user_obj: dict, event_data: dict, updated_by: str, batch_name: str = "TBD", quarter: str = "TBD"):
    try:
        dt_str = event_data.get("start", "")
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        context = {
            "session_type": event_data.get("session_type") or event_data.get("type", "General"),
            "meeting_link": event_data.get("meeting_link") or "No link provided.",
            "topic": event_data.get("title"),
            "date": dt.strftime("%d %b %Y"),
            "day": dt.strftime("%A"),
            "time": dt.strftime("%I:%M %p"),
            "description": event_data.get("additional_details") or "No instructions.",
            "event_title": event_data.get("title"),
            "session_strategy": event_data.get("session_type"),
            "batch_name": batch_name,
            "quarter": quarter,
            "event_datetime": dt.strftime("%d %b %Y, %I:%M %p"),
            "instruction": event_data.get("additional_details") or "No instructions.",
            "created_by": updated_by,
            "user_name": user_obj.get("full_name") or user_obj.get("first_name", "User")
        }
    except Exception as e:
        logger.error(f"Error parsing date for email: {e}")
        context = {"session_type": "Session", "meeting_link": event_data.get("meeting_link", ""), "topic": event_data.get("title"), "date": "TBD", "day": "TBD", "time": "TBD", "description": ""}
    return await send_notification_from_template(user_obj, "event_updated", context, "email")

async def send_event_deleted_email(user_obj: dict, event_title: str, deleted_by: str):
    context = {"event_title": event_title, "deleted_by": deleted_by}
    return await send_notification_from_template(user_obj, "event_deleted", context, "email")

async def send_reminder_email(user_obj: dict, event: dict):
    is_task = event.get("type") == "task"
    dt_str = event.get("start", "")
    formatted_dt = format_datetime_standard(dt_str)
    
    context = {
        "title": event.get("title"),
        "reminder_time": datetime.utcnow().strftime("%H:%M %p"),
        "event_time": formatted_dt if not is_task else "N/A",
        "task_deadline": formatted_dt if is_task else "N/A",
        "meeting_url": event.get("meeting_link") or "View in Dashboard",
        "description": event.get("additional_details") or "No further details."
    }
    return await send_notification_from_template(user_obj, "reminder", context, "email")

async def send_conflict_notification_email(user_obj: dict, event_data: dict, existing_event: dict):
    # Subject: Reschedule time mail due to conflict
    subject = "⚠️ Action Required: Reschedule time mail due to conflict"
    
    # 1. Standardize Timestamps for Template
    try:
        e_dt = datetime.fromisoformat(event_data["start"].replace("Z", "+00:00"))
        event_time_str = e_dt.strftime("%d %b, %I:%M %p")
        ex_dt = datetime.fromisoformat(existing_event["start"].replace("Z", "+00:00"))
        existing_time_str = ex_dt.strftime("%d %b, %I:%M %p")
    except:
        event_time_str = event_data.get("start")
        existing_time_str = existing_event.get("start")

    context = {
        "user_name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
        "event_title": event_data.get("title"),
        "event_time": event_time_str,
        "existing_event": existing_event.get("title"),
        "existing_time": existing_time_str
    }
    
    rendered_body = render_template(CONFLICT_HTML_TEMPLATE, context)
    user_id = user_obj.get("_id") or user_obj.get("id")
    
    # Send to User
    results = {"user": await send_email_notification(user_obj.get("email"), subject, rendered_body, user_id, "schedule_conflict")}
    
    # 2. Fetch Company Email and Send Copy
    company_id = user_obj.get("company_id")
    if company_id:
        try:
            company = await get_collection("companies").find_one({"_id": ObjectId(company_id)})
            if company and company.get("email"):
                results["company"] = await send_email_notification(company["email"], f"[COPY] Conflict Alert: {user_obj.get('full_name')}", rendered_body, user_id, "schedule_conflict_company_copy")
        except Exception as e:
            logger.error(f"Failed to send conflict copy to company: {e}")

    return results

async def send_attendance_thanks_email(user_obj: dict, event_data: dict):
    context = {
        "user_name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
        "event_title": event_data.get("title"),
        "event_time": format_datetime_standard(event_data.get("start"))
    }
    return await send_notification_from_template(user_obj, "attendance_thanks", context, "email")

async def send_attendance_absent_email(user_obj: dict, event_data: dict):
    context = {
        "user_name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
        "event_title": event_data.get("title"),
        "event_time": format_datetime_standard(event_data.get("start"))
    }
    return await send_notification_from_template(user_obj, "attendance_absent", context, "email")
