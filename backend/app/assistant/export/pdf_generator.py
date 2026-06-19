"""Render a chat conversation to a well-formatted, multi-page PDF.

Uses ReportLab's Platypus document model so long conversations flow across
pages automatically with consistent margins, headings, spacing, and footer
page numbers. Lightweight markdown-ish formatting (bullets, numbered lists,
**bold**, *italic*) from assistant turns is preserved where practical.

The only public entry point is `build_conversation_pdf`, which returns the PDF
as raw bytes so the caller decides how to stream/store it.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import List

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    ListFlowable,
    ListItem,
    PageTemplate,
    Paragraph,
    Spacer,
)

from app.assistant.schemas.conversation import Conversation

# Page geometry — generous margins keep text well inside the printable area.
_PAGE_SIZE = A4
_MARGIN = 20 * mm

# Roles we render as conversation turns; everything else (tool/system) is hidden
# so the export mirrors what the user actually sees on screen.
_VISIBLE_ROLES = ("user", "assistant")

_BULLET_RE = re.compile(r"^\s*[-*•]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$")


def _styles():
    """Build the paragraph styles used across the document (once per render)."""
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "ChatTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            spaceAfter=4,
            textColor=colors.HexColor("#1e1b4b"),
        ),
        "subtitle": ParagraphStyle(
            "ChatSubtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#6b7280"),
            spaceAfter=2,
        ),
        "role_user": ParagraphStyle(
            "RoleUser",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#4338ca"),
            spaceBefore=12,
            spaceAfter=3,
        ),
        "role_assistant": ParagraphStyle(
            "RoleAssistant",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#047857"),
            spaceBefore=12,
            spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=15,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#111827"),
            spaceAfter=4,
        ),
        "timestamp": ParagraphStyle(
            "Timestamp",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#9ca3af"),
            spaceAfter=2,
        ),
    }
    return styles


def _escape(text: str) -> str:
    """Escape XML special chars, then re-apply a tiny markdown→ReportLab subset."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # **bold** and __bold__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    # *italic* and _italic_ (avoid matching the bold markers already consumed)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<i>\1</i>", text)
    # `code`
    text = re.sub(r"`(.+?)`", r'<font face="Courier">\1</font>', text)
    return text


def _content_flowables(content: str, styles) -> list:
    """Convert one message body into a list of flowables.

    Splits on blank lines into blocks; consecutive bullet/numbered lines become
    a single proper list so indentation and markers render cleanly. Plain lines
    collapse into wrapped paragraphs.
    """
    flowables: list = []
    if not content or not content.strip():
        flowables.append(Paragraph("<i>(no content)</i>", styles["body"]))
        return flowables

    lines = content.replace("\r\n", "\n").split("\n")
    i = 0
    n = len(lines)

    def flush_paragraph(buf: List[str]):
        if buf:
            flowables.append(Paragraph(_escape(" ".join(buf)), styles["body"]))
            buf.clear()

    para_buf: List[str] = []
    while i < n:
        line = lines[i]
        bullet = _BULLET_RE.match(line)
        numbered = _NUMBERED_RE.match(line)

        if bullet or numbered:
            flush_paragraph(para_buf)
            ordered = bool(numbered)
            items: List[ListItem] = []
            while i < n:
                bm = _BULLET_RE.match(lines[i])
                nm = _NUMBERED_RE.match(lines[i])
                if ordered and nm:
                    items.append(ListItem(Paragraph(_escape(nm.group(1)), styles["body"])))
                elif (not ordered) and bm:
                    items.append(ListItem(Paragraph(_escape(bm.group(1)), styles["body"])))
                else:
                    break
                i += 1
            flowables.append(
                ListFlowable(
                    items,
                    bulletType="1" if ordered else "bullet",
                    bulletColor=colors.HexColor("#6b7280"),
                    leftIndent=14,
                    bulletFontSize=9,
                )
            )
            continue

        if not line.strip():
            flush_paragraph(para_buf)
        else:
            para_buf.append(line.strip())
        i += 1

    flush_paragraph(para_buf)
    return flowables


def _fmt_dt(dt: datetime) -> str:
    try:
        return dt.strftime("%d %b %Y, %I:%M %p")
    except Exception:
        return str(dt)


def _footer(canvas, doc):
    """Draw 'Page N' centered in the bottom margin of every page."""
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#9ca3af"))
    width, _ = _PAGE_SIZE
    canvas.drawCentredString(width / 2.0, 12 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_conversation_pdf(conversation: Conversation) -> bytes:
    """Render `conversation` to PDF bytes (A4, multi-page, page-numbered)."""
    buffer = io.BytesIO()
    styles = _styles()

    doc = BaseDocTemplate(
        buffer,
        pagesize=_PAGE_SIZE,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=_MARGIN,
        title="Chat Conversation",
        author="Sparsh Assistant",
    )
    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="body",
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_footer)])

    story: list = []

    # ── Header ────────────────────────────────────────────────────────────
    title = (conversation.title or "Chat Conversation").strip() or "Chat Conversation"
    story.append(Paragraph(_escape(title), styles["title"]))
    story.append(Paragraph("Chat Conversation", styles["subtitle"]))
    story.append(
        Paragraph(f"Generated on {_fmt_dt(datetime.utcnow())} UTC", styles["subtitle"])
    )
    story.append(Spacer(1, 6))

    # ── Turns ─────────────────────────────────────────────────────────────
    visible = [m for m in conversation.messages if m.role in _VISIBLE_ROLES]
    if not visible:
        story.append(Spacer(1, 10))
        story.append(Paragraph("<i>This conversation has no messages yet.</i>", styles["body"]))
    for msg in visible:
        if msg.role == "user":
            story.append(Paragraph("User", styles["role_user"]))
        else:
            story.append(Paragraph("Assistant", styles["role_assistant"]))
        if msg.timestamp:
            story.append(Paragraph(_fmt_dt(msg.timestamp), styles["timestamp"]))
        story.extend(_content_flowables(msg.content or "", styles))
        story.append(Spacer(1, 6))

    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf
