"""Student-domain tools (learner self-service).

Catalog (Phase 1+): get_my_profile, get_my_batches, get_my_courses,
get_course_progress, get_my_sessions, get_upcoming_sessions, get_session_details,
get_my_attendance, get_attendance_summary, get_latest_quiz_result,
get_my_assessment_results, get_subject_wise_scores, analyze_student_performance,
get_learning_progress, get_pending_assignments, recommend_study_plan,
get_my_notifications.

Phase 1 implements: get_my_profile, get_my_sessions, get_latest_quiz_result.
Importing the submodules here runs their @tool decorators so they self-register.
"""

from app.assistant.tools.student import (  # noqa: E402,F401
    assessment_tools,
    profile_tools,
    session_tools,
)
