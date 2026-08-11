"""Metric definitions-as-data and the D9 funnel stage mapping.

Every consumer imports FUNNEL_STAGE_BY_STATE / stage_for_state from here.
Nobody re-lists states inline.
"""

from __future__ import annotations

from dataclasses import dataclass

from thesisound.domain import ProjectState

FUNNEL_STAGES: dict[int, str] = {
    1: "Created",
    2: "Brief confirmed",
    3: "Sources gathered",
    4: "Corpus confirmed",
    5: "Episode planned",
    6: "Script verified",
    7: "Audio complete",
}

# D9 — single source of truth. failed_* map to None (not stages).
FUNNEL_STAGE_BY_STATE: dict[ProjectState, int | None] = {
    ProjectState.DRAFT: 1,
    ProjectState.BRIEF_READY: 2,
    ProjectState.SOURCES_COLLECTING: 3,
    ProjectState.SOURCE_SELECTION_REQUIRED: 3,
    ProjectState.CORPUS_BUILDING: 4,
    ProjectState.CORPUS_READY: 4,
    ProjectState.EPISODE_PLANNING: 5,
    ProjectState.EPISODE_PLANNED: 5,
    ProjectState.SCRIPT_DRAFTING: 6,
    ProjectState.SCRIPT_READY: 6,
    ProjectState.SCRIPT_VERIFYING: 6,
    ProjectState.SCRIPT_REVIEW_REQUIRED: 6,
    ProjectState.SCRIPT_VERIFIED: 6,
    ProjectState.AUDIO_GENERATING: 7,
    ProjectState.AUDIO_READY: 7,
    ProjectState.AUDIO_VERIFYING: 7,
    ProjectState.COMPLETE: 7,
    ProjectState.FAILED_RETRYABLE: None,
    ProjectState.FAILED_PERMANENT: None,
}


def stage_for_state(state: ProjectState | str) -> int | None:
    if isinstance(state, str):
        try:
            state = ProjectState(state)
        except ValueError:
            return None
    return FUNNEL_STAGE_BY_STATE.get(state)


_REAL = "is_synthetic = 0 AND environment = 'production'"


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    key: str
    question: str
    sql: str
    grain: str
    owner: str
    caveat: str = ""


# ---------------------------------------------------------------------------
# Catalogue — one definition per metric in §6
# Each query returns: day, dimension_json, value, numerator, denominator
# ---------------------------------------------------------------------------

A1 = MetricDefinition(
    key="trusted_episodes_weekly",
    question="How many trusted episodes were delivered this week?",
    grain="week",
    owner="product",
    caveat="Requires both stage 7 and an audio download; completion alone is not enough.",
    sql=f"""
    WITH completed AS (
      SELECT DISTINCT project_id,
             date(occurred_at, 'weekday 1', '-7 days') AS week
        FROM product_events
       WHERE name = 'project.stage_entered'
         AND json_extract(properties_json, '$.stage') = 7
         AND {_REAL}
    ),
    downloaded AS (
      SELECT DISTINCT project_id
        FROM product_events
       WHERE name = 'episode.audio_downloaded' AND {_REAL}
    )
    SELECT c.week AS day, '{{}}' AS dimension_json,
           CAST(COUNT(*) AS REAL) AS value,
           CAST(COUNT(*) AS REAL) AS numerator,
           NULL AS denominator
      FROM completed c
      JOIN downloaded d ON d.project_id = c.project_id
     GROUP BY c.week
    """,
)

B1 = MetricDefinition(
    key="auth_request_to_verify_rate",
    question="Do people who ask for a code get in?",
    grain="day",
    owner="product",
    caveat="SMS delivery outages look like UX failure — read next to B3.",
    sql=f"""
    SELECT date(occurred_at) AS day, '{{}}' AS dimension_json,
           CAST(SUM(CASE WHEN name = 'auth.code_verified' THEN 1 ELSE 0 END) AS REAL)
             / NULLIF(SUM(CASE WHEN name = 'auth.code_requested' THEN 1 ELSE 0 END), 0) AS value,
           CAST(SUM(CASE WHEN name = 'auth.code_verified' THEN 1 ELSE 0 END) AS REAL) AS numerator,
           CAST(SUM(CASE WHEN name = 'auth.code_requested' THEN 1 ELSE 0 END) AS REAL) AS denominator
      FROM product_events
     WHERE name IN ('auth.code_requested', 'auth.code_verified') AND {_REAL}
     GROUP BY date(occurred_at)
    """,
)

B2 = MetricDefinition(
    key="auth_verify_failure_rate",
    question="Is OTP entry painful?",
    grain="day",
    owner="product",
    sql=f"""
    SELECT date(occurred_at) AS day, '{{}}' AS dimension_json,
           CAST(SUM(CASE WHEN name = 'auth.code_failed' THEN 1 ELSE 0 END) AS REAL)
             / NULLIF(SUM(CASE WHEN name IN ('auth.code_verified', 'auth.code_failed')
                               THEN 1 ELSE 0 END), 0) AS value,
           CAST(SUM(CASE WHEN name = 'auth.code_failed' THEN 1 ELSE 0 END) AS REAL) AS numerator,
           CAST(SUM(CASE WHEN name IN ('auth.code_verified', 'auth.code_failed')
                         THEN 1 ELSE 0 END) AS REAL) AS denominator
      FROM product_events
     WHERE name IN ('auth.code_verified', 'auth.code_failed') AND {_REAL}
     GROUP BY date(occurred_at)
    """,
)

B3 = MetricDefinition(
    key="auth_median_seconds_to_verify",
    question="How long does the code round-trip take?",
    grain="day",
    owner="product",
    caveat="Includes SMS delivery latency.",
    sql=f"""
    WITH paired AS (
      SELECT date(v.occurred_at) AS day,
             (julianday(v.occurred_at) - julianday(
                (SELECT MAX(r.occurred_at) FROM product_events r
                  WHERE r.name = 'auth.code_requested'
                    AND r.is_synthetic = 0 AND r.environment = 'production'
                    AND r.occurred_at <= v.occurred_at
                    AND (
                      (r.user_id IS NOT NULL AND r.user_id = v.user_id)
                      OR (r.anon_id IS NOT NULL AND r.anon_id = v.anon_id)
                    )
                )
             )) * 86400 AS secs
        FROM product_events v
       WHERE v.name = 'auth.code_verified' AND v.is_synthetic = 0
         AND v.environment = 'production'
    )
    SELECT day, '{{}}' AS dimension_json,
           CAST(AVG(secs) AS REAL) AS value,
           NULL AS numerator, NULL AS denominator
      FROM paired
     WHERE secs IS NOT NULL
     GROUP BY day
    """,
)

B4 = MetricDefinition(
    key="auth_lockout_rate",
    question="Are we locking real users out?",
    grain="day",
    owner="product",
    sql=f"""
    WITH attempts AS (
      SELECT date(occurred_at) AS day,
             COUNT(DISTINCT COALESCE(user_id, anon_id)) AS attempting
        FROM product_events
       WHERE name IN (
               'auth.code_requested', 'auth.code_failed',
               'auth.password_failed', 'auth.password_succeeded'
             )
         AND {_REAL}
       GROUP BY date(occurred_at)
    ),
    locks AS (
      SELECT date(occurred_at) AS day,
             COUNT(DISTINCT COALESCE(user_id, anon_id)) AS locked
        FROM product_events
       WHERE name = 'auth.locked_out' AND {_REAL}
       GROUP BY date(occurred_at)
    )
    SELECT a.day, '{{}}' AS dimension_json,
           CAST(COALESCE(l.locked, 0) AS REAL) / NULLIF(a.attempting, 0) AS value,
           CAST(COALESCE(l.locked, 0) AS REAL) AS numerator,
           CAST(a.attempting AS REAL) AS denominator
      FROM attempts a
      LEFT JOIN locks l ON l.day = a.day
    """,
)

B5 = MetricDefinition(
    key="new_users_weekly",
    question="Are we growing?",
    grain="week",
    owner="product",
    sql=f"""
    SELECT date(occurred_at, 'weekday 1', '-7 days') AS day, '{{}}' AS dimension_json,
           CAST(COUNT(DISTINCT user_id) AS REAL) AS value,
           CAST(COUNT(DISTINCT user_id) AS REAL) AS numerator,
           NULL AS denominator
      FROM product_events
     WHERE name = 'user.registered' AND {_REAL}
     GROUP BY date(occurred_at, 'weekday 1', '-7 days')
    """,
)

C1 = MetricDefinition(
    key="activation_rate_7d",
    question="Do new users reach a completed episode within 7 days?",
    grain="week",
    owner="product",
    caveat="Denominator is a cohort; only final 7 days after the cohort closes.",
    sql=f"""
    WITH regs AS (
      SELECT user_id, MIN(occurred_at) AS registered_at,
             date(MIN(occurred_at), 'weekday 1', '-7 days') AS week
        FROM product_events
       WHERE name = 'user.registered' AND {_REAL} AND user_id IS NOT NULL
       GROUP BY user_id
    ),
    activated AS (
      SELECT DISTINCT r.user_id, r.week
        FROM regs r
        JOIN product_events e
          ON e.user_id = r.user_id
         AND e.name = 'project.stage_entered'
         AND json_extract(e.properties_json, '$.stage') = 7
         AND e.is_synthetic = 0 AND e.environment = 'production'
         AND julianday(e.occurred_at) - julianday(r.registered_at) <= 7
    )
    SELECT r.week AS day, '{{}}' AS dimension_json,
           CAST(COUNT(DISTINCT a.user_id) AS REAL)
             / NULLIF(COUNT(DISTINCT r.user_id), 0) AS value,
           CAST(COUNT(DISTINCT a.user_id) AS REAL) AS numerator,
           CAST(COUNT(DISTINCT r.user_id) AS REAL) AS denominator
      FROM regs r
      LEFT JOIN activated a ON a.user_id = r.user_id AND a.week = r.week
     GROUP BY r.week
    """,
)

C2_P50 = MetricDefinition(
    key="time_to_first_episode_p50",
    question="How long does the first success take (p50)?",
    grain="week",
    owner="product",
    sql=f"""
    WITH regs AS (
      SELECT user_id, MIN(occurred_at) AS registered_at
        FROM product_events
       WHERE name = 'user.registered' AND {_REAL} AND user_id IS NOT NULL
       GROUP BY user_id
    ),
    first_ep AS (
      SELECT r.user_id,
             date(r.registered_at, 'weekday 1', '-7 days') AS week,
             MIN((julianday(e.occurred_at) - julianday(r.registered_at)) * 86400) AS secs
        FROM regs r
        JOIN product_events e
          ON e.user_id = r.user_id
         AND e.name = 'project.stage_entered'
         AND json_extract(e.properties_json, '$.stage') = 7
         AND e.is_synthetic = 0 AND e.environment = 'production'
       GROUP BY r.user_id
    )
    SELECT week AS day, '{{}}' AS dimension_json,
           CAST(secs AS REAL) AS value, NULL AS numerator, NULL AS denominator
      FROM first_ep
     GROUP BY week
     HAVING COUNT(*) >= 1
    """,
)

C2_P90 = MetricDefinition(
    key="time_to_first_episode_p90",
    question="How long does the first success take (p90)?",
    grain="week",
    owner="product",
    sql=C2_P50.sql,
)

C3 = MetricDefinition(
    key="first_project_rate",
    question="Do they even start?",
    grain="week",
    owner="product",
    sql=f"""
    WITH regs AS (
      SELECT user_id, date(MIN(occurred_at), 'weekday 1', '-7 days') AS week
        FROM product_events
       WHERE name = 'user.registered' AND {_REAL} AND user_id IS NOT NULL
       GROUP BY user_id
    ),
    creators AS (
      SELECT DISTINCT user_id
        FROM product_events
       WHERE name = 'project.created' AND {_REAL} AND user_id IS NOT NULL
    )
    SELECT r.week AS day, '{{}}' AS dimension_json,
           CAST(COUNT(DISTINCT c.user_id) AS REAL)
             / NULLIF(COUNT(DISTINCT r.user_id), 0) AS value,
           CAST(COUNT(DISTINCT c.user_id) AS REAL) AS numerator,
           CAST(COUNT(DISTINCT r.user_id) AS REAL) AS denominator
      FROM regs r
      LEFT JOIN creators c ON c.user_id = r.user_id
     GROUP BY r.week
    """,
)

C4 = MetricDefinition(
    key="first_session_depth",
    question="How far does the first project get?",
    grain="day",
    owner="product",
    sql=f"""
    WITH first_projects AS (
      SELECT user_id, project_id, MIN(occurred_at) AS created_at
        FROM product_events
       WHERE name = 'project.created' AND {_REAL}
         AND user_id IS NOT NULL AND project_id IS NOT NULL
       GROUP BY user_id
    ),
    max_stage AS (
      SELECT f.user_id, date(f.created_at) AS day,
             MAX(CAST(json_extract(e.properties_json, '$.stage') AS INTEGER)) AS stage
        FROM first_projects f
        JOIN product_events e
          ON e.project_id = f.project_id
         AND e.name = 'project.stage_entered'
         AND e.is_synthetic = 0 AND e.environment = 'production'
       GROUP BY f.user_id
    )
    SELECT day,
           json_object('stage', stage) AS dimension_json,
           CAST(COUNT(*) AS REAL) AS value,
           CAST(COUNT(*) AS REAL) AS numerator,
           NULL AS denominator
      FROM max_stage
     GROUP BY day, stage
    """,
)

D1 = MetricDefinition(
    key="stage_conversion",
    question="Where do projects die?",
    grain="day",
    owner="product",
    sql=f"""
    WITH reached AS (
      SELECT project_id,
             CAST(json_extract(properties_json, '$.stage') AS INTEGER) AS stage,
             date(MIN(occurred_at)) AS day
        FROM product_events
       WHERE name = 'project.stage_entered' AND {_REAL}
       GROUP BY project_id, CAST(json_extract(properties_json, '$.stage') AS INTEGER)
    ),
    by_stage AS (
      SELECT day, stage, COUNT(DISTINCT project_id) AS n
        FROM reached
       GROUP BY day, stage
    )
    SELECT a.day,
           json_object('from_stage', a.stage, 'to_stage', a.stage + 1) AS dimension_json,
           CAST(COALESCE(b.n, 0) AS REAL) / NULLIF(a.n, 0) AS value,
           CAST(COALESCE(b.n, 0) AS REAL) AS numerator,
           CAST(a.n AS REAL) AS denominator
      FROM by_stage a
      LEFT JOIN by_stage b ON b.day = a.day AND b.stage = a.stage + 1
     WHERE a.stage BETWEEN 1 AND 6
    """,
)

D2 = MetricDefinition(
    key="stage_dropoff_absolute",
    question="How many projects are stuck, and where?",
    grain="day",
    owner="product",
    sql=f"""
    WITH max_stage AS (
      SELECT project_id,
             MAX(CAST(json_extract(properties_json, '$.stage') AS INTEGER)) AS stage,
             MAX(occurred_at) AS last_at
        FROM product_events
       WHERE name = 'project.stage_entered' AND {_REAL}
       GROUP BY project_id
    )
    SELECT date('now') AS day,
           json_object('stage', stage) AS dimension_json,
           CAST(COUNT(*) AS REAL) AS value,
           CAST(COUNT(*) AS REAL) AS numerator,
           NULL AS denominator
      FROM max_stage
     WHERE julianday('now') - julianday(last_at) >= 14
       AND stage < 7
     GROUP BY stage
    """,
)

D3 = MetricDefinition(
    key="stage_median_duration",
    question="Which stage is slowest for the user?",
    grain="day",
    owner="product",
    caveat="Wall-clock including user idle time; not machine latency.",
    sql=f"""
    WITH entries AS (
      SELECT project_id,
             CAST(json_extract(properties_json, '$.stage') AS INTEGER) AS stage,
             MIN(occurred_at) AS entered_at
        FROM product_events
       WHERE name = 'project.stage_entered' AND {_REAL}
       GROUP BY project_id, CAST(json_extract(properties_json, '$.stage') AS INTEGER)
    ),
    durations AS (
      SELECT a.stage,
             date(a.entered_at) AS day,
             (julianday(b.entered_at) - julianday(a.entered_at)) * 86400 AS secs
        FROM entries a
        JOIN entries b ON b.project_id = a.project_id AND b.stage = a.stage + 1
    )
    SELECT day,
           json_object('stage', stage) AS dimension_json,
           CAST(AVG(secs) AS REAL) AS value,
           NULL AS numerator, NULL AS denominator
      FROM durations
     GROUP BY day, stage
    """,
)

D4 = MetricDefinition(
    key="end_to_end_completion_rate",
    question="What fraction of started projects finish?",
    grain="day",
    owner="product",
    sql=f"""
    WITH s1 AS (
      SELECT project_id, date(MIN(occurred_at)) AS day
        FROM product_events
       WHERE name = 'project.stage_entered'
         AND json_extract(properties_json, '$.stage') = 1
         AND {_REAL}
       GROUP BY project_id
    ),
    s7 AS (
      SELECT DISTINCT project_id
        FROM product_events
       WHERE name = 'project.stage_entered'
         AND json_extract(properties_json, '$.stage') = 7
         AND {_REAL}
    )
    SELECT s1.day, '{{}}' AS dimension_json,
           CAST(COUNT(DISTINCT s7.project_id) AS REAL)
             / NULLIF(COUNT(DISTINCT s1.project_id), 0) AS value,
           CAST(COUNT(DISTINCT s7.project_id) AS REAL) AS numerator,
           CAST(COUNT(DISTINCT s1.project_id) AS REAL) AS denominator
      FROM s1
      LEFT JOIN s7 ON s7.project_id = s1.project_id
     GROUP BY s1.day
    """,
)

D5_P50 = MetricDefinition(
    key="end_to_end_duration_p50",
    question="How long is the whole job (p50)?",
    grain="day",
    owner="product",
    sql=f"""
    WITH created AS (
      SELECT project_id, MIN(occurred_at) AS created_at
        FROM product_events
       WHERE name = 'project.created' AND {_REAL}
       GROUP BY project_id
    ),
    done AS (
      SELECT c.project_id, date(c.created_at) AS day,
             (julianday(MIN(e.occurred_at)) - julianday(c.created_at)) * 86400 AS secs
        FROM created c
        JOIN product_events e
          ON e.project_id = c.project_id
         AND e.name = 'project.stage_entered'
         AND json_extract(e.properties_json, '$.stage') = 7
         AND e.is_synthetic = 0 AND e.environment = 'production'
       GROUP BY c.project_id
    )
    SELECT day, '{{}}' AS dimension_json,
           CAST(AVG(secs) AS REAL) AS value,
           NULL AS numerator, NULL AS denominator
      FROM done
     GROUP BY day
    """,
)

D5_P90 = MetricDefinition(
    key="end_to_end_duration_p90",
    question="How long is the whole job (p90)?",
    grain="day",
    owner="product",
    sql=D5_P50.sql,
)

E1 = MetricDefinition(
    key="brief_confirm_rate",
    question="Do we get the brief right first time?",
    grain="day",
    owner="product",
    sql=f"""
    WITH confirms AS (
      SELECT project_id, date(occurred_at) AS day, occurred_at
        FROM product_events
       WHERE name = 'gate.brief_confirmed' AND {_REAL}
    ),
    edited AS (
      SELECT DISTINCT project_id
        FROM product_events
       WHERE name = 'gate.brief_edited' AND {_REAL}
    )
    SELECT c.day, '{{}}' AS dimension_json,
           CAST(SUM(CASE WHEN e.project_id IS NULL THEN 1 ELSE 0 END) AS REAL)
             / NULLIF(COUNT(*), 0) AS value,
           CAST(SUM(CASE WHEN e.project_id IS NULL THEN 1 ELSE 0 END) AS REAL) AS numerator,
           CAST(COUNT(*) AS REAL) AS denominator
      FROM confirms c
      LEFT JOIN edited e ON e.project_id = c.project_id
     GROUP BY c.day
    """,
)

E2 = MetricDefinition(
    key="corpus_edit_depth",
    question="How much do users fight source selection?",
    grain="day",
    owner="product",
    sql=f"""
    WITH edits AS (
      SELECT project_id, date(occurred_at) AS day
        FROM product_events
       WHERE name IN ('gate.source_toggled', 'gate.source_deleted') AND {_REAL}
    ),
    confirms AS (
      SELECT project_id, date(MIN(occurred_at)) AS day
        FROM product_events
       WHERE name = 'gate.corpus_confirmed' AND {_REAL}
       GROUP BY project_id
    )
    SELECT c.day, '{{}}' AS dimension_json,
           CAST(COUNT(e.project_id) AS REAL) / NULLIF(COUNT(DISTINCT c.project_id), 0) AS value,
           CAST(COUNT(e.project_id) AS REAL) AS numerator,
           CAST(COUNT(DISTINCT c.project_id) AS REAL) AS denominator
      FROM confirms c
      LEFT JOIN edits e ON e.project_id = c.project_id AND e.day <= c.day
     GROUP BY c.day
    """,
)

E3 = MetricDefinition(
    key="script_approval_rate",
    question="Is the first script good enough?",
    grain="day",
    owner="product",
    sql=f"""
    SELECT date(occurred_at) AS day, '{{}}' AS dimension_json,
           CAST(SUM(CASE WHEN name = 'gate.script_approved' THEN 1 ELSE 0 END) AS REAL)
             / NULLIF(SUM(CASE WHEN name IN (
                   'gate.script_approved', 'gate.script_review_requested'
                 ) THEN 1 ELSE 0 END), 0) AS value,
           CAST(SUM(CASE WHEN name = 'gate.script_approved' THEN 1 ELSE 0 END) AS REAL)
             AS numerator,
           CAST(SUM(CASE WHEN name IN (
                 'gate.script_approved', 'gate.script_review_requested'
               ) THEN 1 ELSE 0 END) AS REAL) AS denominator
      FROM product_events
     WHERE name IN ('gate.script_approved', 'gate.script_review_requested') AND {_REAL}
     GROUP BY date(occurred_at)
    """,
)

E4 = MetricDefinition(
    key="script_rework_loops",
    question="How many script rounds per episode?",
    grain="day",
    owner="product",
    sql=f"""
    SELECT date(occurred_at) AS day, '{{}}' AS dimension_json,
           CAST(COUNT(*) AS REAL) / NULLIF(COUNT(DISTINCT project_id), 0) AS value,
           CAST(COUNT(*) AS REAL) AS numerator,
           CAST(COUNT(DISTINCT project_id) AS REAL) AS denominator
      FROM product_events
     WHERE name = 'project.stage_entered'
       AND json_extract(properties_json, '$.from_state') = 'script_verifying'
       AND json_extract(properties_json, '$.state') = 'script_drafting'
       AND {_REAL}
     GROUP BY date(occurred_at)
    """,
)

E5 = MetricDefinition(
    key="gate_block_rate",
    question="How often does a blocking rule fire?",
    grain="day",
    owner="product",
    sql=f"""
    WITH active AS (
      SELECT date(occurred_at) AS day, COUNT(DISTINCT project_id) AS n
        FROM product_events
       WHERE project_id IS NOT NULL AND {_REAL}
       GROUP BY date(occurred_at)
    ),
    blocked AS (
      SELECT date(occurred_at) AS day,
             COALESCE(json_extract(properties_json, '$.gate_name'), 'unknown') AS gate_name,
             COUNT(DISTINCT project_id) AS n
        FROM product_events
       WHERE name = 'gate.blocked' AND {_REAL}
       GROUP BY date(occurred_at), COALESCE(json_extract(properties_json, '$.gate_name'), 'unknown')
    )
    SELECT b.day,
           json_object('gate_name', b.gate_name) AS dimension_json,
           CAST(b.n AS REAL) / NULLIF(a.n, 0) AS value,
           CAST(b.n AS REAL) AS numerator,
           CAST(a.n AS REAL) AS denominator
      FROM blocked b
      JOIN active a ON a.day = b.day
    """,
)

E6 = MetricDefinition(
    key="gate_resolution_rate",
    question="Do users recover from a block?",
    grain="day",
    owner="product",
    caveat="The product promise metric: when we block, do they recover?",
    sql=f"""
    WITH blocked AS (
      SELECT date(occurred_at) AS day,
             COALESCE(json_extract(properties_json, '$.gate_name'), 'unknown') AS gate_name,
             COUNT(*) AS n
        FROM product_events
       WHERE name = 'gate.blocked' AND {_REAL}
       GROUP BY 1, 2
    ),
    resolved AS (
      SELECT date(occurred_at) AS day,
             COALESCE(json_extract(properties_json, '$.gate_name'), 'unknown') AS gate_name,
             COUNT(*) AS n
        FROM product_events
       WHERE name = 'gate.resolved' AND {_REAL}
       GROUP BY 1, 2
    )
    SELECT b.day,
           json_object('gate_name', b.gate_name) AS dimension_json,
           CAST(COALESCE(r.n, 0) AS REAL) / NULLIF(b.n, 0) AS value,
           CAST(COALESCE(r.n, 0) AS REAL) AS numerator,
           CAST(b.n AS REAL) AS denominator
      FROM blocked b
      LEFT JOIN resolved r ON r.day = b.day AND r.gate_name = b.gate_name
    """,
)

E7 = MetricDefinition(
    key="gate_median_blocked_seconds",
    question="How long are people stuck?",
    grain="day",
    owner="product",
    sql=f"""
    SELECT date(occurred_at) AS day,
           json_object(
             'gate_name',
             COALESCE(json_extract(properties_json, '$.gate_name'), 'unknown')
           ) AS dimension_json,
           CAST(AVG(json_extract(properties_json, '$.blocked_seconds')) AS REAL) AS value,
           NULL AS numerator, NULL AS denominator
      FROM product_events
     WHERE name = 'gate.resolved' AND {_REAL}
     GROUP BY date(occurred_at),
              COALESCE(json_extract(properties_json, '$.gate_name'), 'unknown')
    """,
)

E8 = MetricDefinition(
    key="rewind_rate",
    question="How often do users go backwards?",
    grain="day",
    owner="product",
    sql=f"""
    WITH active AS (
      SELECT date(occurred_at) AS day, COUNT(DISTINCT project_id) AS n
        FROM product_events
       WHERE project_id IS NOT NULL AND {_REAL}
       GROUP BY date(occurred_at)
    ),
    rewinds AS (
      SELECT date(occurred_at) AS day,
             COALESCE(json_extract(properties_json, '$.from_stage'), 0) AS from_stage,
             COUNT(DISTINCT project_id) AS n
        FROM product_events
       WHERE name = 'workflow.rewound' AND {_REAL}
       GROUP BY 1, 2
    )
    SELECT r.day,
           json_object('from_stage', r.from_stage) AS dimension_json,
           CAST(r.n AS REAL) / NULLIF(a.n, 0) AS value,
           CAST(r.n AS REAL) AS numerator,
           CAST(a.n AS REAL) AS denominator
      FROM rewinds r
      JOIN active a ON a.day = r.day
    """,
)

E9 = MetricDefinition(
    key="plan_review_depth_rate",
    question="Does anyone open the omitted / must-not-be-lost list?",
    grain="day",
    owner="product",
    sql=f"""
    WITH reviewed AS (
      SELECT date(occurred_at) AS day, COUNT(*) AS n
        FROM product_events
       WHERE name = 'plan.reviewed' AND {_REAL}
       GROUP BY date(occurred_at)
    ),
    opened AS (
      SELECT date(occurred_at) AS day,
             COALESCE(json_extract(properties_json, '$.origin'), 'unknown') AS origin,
             COUNT(*) AS n
        FROM product_events
       WHERE name = 'plan.omitted_list_opened' AND {_REAL}
       GROUP BY 1, 2
    )
    SELECT o.day,
           json_object('origin', o.origin) AS dimension_json,
           CAST(o.n AS REAL) / NULLIF(r.n, 0) AS value,
           CAST(o.n AS REAL) AS numerator,
           CAST(r.n AS REAL) AS denominator
      FROM opened o
      JOIN reviewed r ON r.day = o.day
    """,
)

E10 = MetricDefinition(
    key="plan_duration_adjust_rate",
    question="What share of planned projects change duration after seeing the plan?",
    grain="day",
    owner="product",
    sql=f"""
    WITH planned AS (
      SELECT project_id, date(MIN(occurred_at)) AS day
        FROM product_events
       WHERE name = 'project.stage_entered'
         AND json_extract(properties_json, '$.state') = 'episode_planned'
         AND {_REAL}
       GROUP BY project_id
    ),
    adjusted AS (
      SELECT DISTINCT project_id
        FROM product_events
       WHERE name = 'plan.duration_changed' AND {_REAL}
    )
    SELECT p.day, '{{}}' AS dimension_json,
           CAST(COUNT(DISTINCT CASE WHEN a.project_id IS NOT NULL THEN p.project_id END) AS REAL)
             / NULLIF(COUNT(DISTINCT p.project_id), 0) AS value,
           CAST(COUNT(DISTINCT CASE WHEN a.project_id IS NOT NULL THEN p.project_id END) AS REAL)
             AS numerator,
           CAST(COUNT(DISTINCT p.project_id) AS REAL) AS denominator
      FROM planned p
      LEFT JOIN adjusted a ON a.project_id = p.project_id
     GROUP BY p.day
    """,
)

E11 = MetricDefinition(
    key="plan_duration_increase_share",
    question="Are duration changes mostly increases or decreases?",
    grain="day",
    owner="product",
    sql=f"""
    SELECT date(occurred_at) AS day, '{{}}' AS dimension_json,
           CAST(SUM(CASE WHEN json_extract(properties_json, '$.direction') = 'up'
                         THEN 1 ELSE 0 END) AS REAL)
             / NULLIF(COUNT(*), 0) AS value,
           CAST(SUM(CASE WHEN json_extract(properties_json, '$.direction') = 'up'
                         THEN 1 ELSE 0 END) AS REAL) AS numerator,
           CAST(COUNT(*) AS REAL) AS denominator
      FROM product_events
     WHERE name = 'plan.duration_changed' AND {_REAL}
     GROUP BY date(occurred_at)
    """,
)

E12 = MetricDefinition(
    key="plan_gate_abandon_rate",
    question="How many projects die at the plan gate?",
    grain="day",
    owner="product",
    caveat="Max stage = 5 and idle 14d / projects that reached stage 5.",
    sql=f"""
    WITH max_stage AS (
      SELECT project_id,
             MAX(CAST(json_extract(properties_json, '$.stage') AS INTEGER)) AS stage,
             MAX(occurred_at) AS last_at,
             date(MIN(CASE WHEN CAST(json_extract(properties_json, '$.stage') AS INTEGER) = 5
                           THEN occurred_at END)) AS day
        FROM product_events
       WHERE name = 'project.stage_entered' AND {_REAL}
       GROUP BY project_id
    ),
    reached AS (
      SELECT project_id, day
        FROM max_stage
       WHERE day IS NOT NULL
    ),
    abandoned AS (
      SELECT project_id, day
        FROM max_stage
       WHERE stage = 5
         AND day IS NOT NULL
         AND julianday('now') - julianday(last_at) >= 14
    )
    SELECT r.day, '{{}}' AS dimension_json,
           CAST(COUNT(DISTINCT a.project_id) AS REAL)
             / NULLIF(COUNT(DISTINCT r.project_id), 0) AS value,
           CAST(COUNT(DISTINCT a.project_id) AS REAL) AS numerator,
           CAST(COUNT(DISTINCT r.project_id) AS REAL) AS denominator
      FROM reached r
      LEFT JOIN abandoned a ON a.project_id = r.project_id
     GROUP BY r.day
    """,
)

E13 = MetricDefinition(
    key="plan_replan_before_approval",
    question="Median replans of the episode plan before script approval?",
    grain="day",
    owner="product",
    caveat="Counts episode_planned → episode_planning stage transitions; AVG used as SQLite median proxy.",
    sql=f"""
    WITH replans AS (
      SELECT project_id, COUNT(*) AS n
        FROM product_events
       WHERE name = 'project.stage_entered'
         AND json_extract(properties_json, '$.from_state') = 'episode_planned'
         AND json_extract(properties_json, '$.state') = 'episode_planning'
         AND {_REAL}
       GROUP BY project_id
    ),
    planned AS (
      SELECT project_id, date(MIN(occurred_at)) AS day
        FROM product_events
       WHERE name = 'project.stage_entered'
         AND json_extract(properties_json, '$.state') = 'episode_planned'
         AND {_REAL}
       GROUP BY project_id
    )
    SELECT p.day, '{{}}' AS dimension_json,
           CAST(AVG(COALESCE(r.n, 0)) AS REAL) AS value,
           NULL AS numerator, NULL AS denominator
      FROM planned p
      LEFT JOIN replans r ON r.project_id = p.project_id
     GROUP BY p.day
    """,
)

F1 = MetricDefinition(
    key="source_trace_open_rate",
    question="Is the traceability promise used?",
    grain="day",
    owner="product",
    sql=f"""
    WITH completed AS (
      SELECT date(occurred_at) AS day, COUNT(DISTINCT project_id) AS n
        FROM product_events
       WHERE name = 'project.stage_entered'
         AND json_extract(properties_json, '$.stage') = 7
         AND {_REAL}
       GROUP BY date(occurred_at)
    ),
    opened AS (
      SELECT date(occurred_at) AS day, COUNT(DISTINCT project_id) AS n
        FROM product_events
       WHERE name = 'episode.source_trace_opened' AND {_REAL}
       GROUP BY date(occurred_at)
    )
    SELECT c.day, '{{}}' AS dimension_json,
           CAST(COALESCE(o.n, 0) AS REAL) / NULLIF(c.n, 0) AS value,
           CAST(COALESCE(o.n, 0) AS REAL) AS numerator,
           CAST(c.n AS REAL) AS denominator
      FROM completed c
      LEFT JOIN opened o ON o.day = c.day
    """,
)

F2 = MetricDefinition(
    key="coverage_block_rate",
    question="How often is the corpus genuinely insufficient?",
    grain="day",
    owner="product",
    sql=f"""
    SELECT date(occurred_at) AS day, '{{}}' AS dimension_json,
           CAST(COUNT(DISTINCT project_id) AS REAL) AS value,
           CAST(COUNT(DISTINCT project_id) AS REAL) AS numerator,
           NULL AS denominator
      FROM product_events
     WHERE name = 'gate.blocked'
       AND json_extract(properties_json, '$.gate_name') = 'coverage'
       AND {_REAL}
     GROUP BY date(occurred_at)
    """,
)

F3 = MetricDefinition(
    key="claim_retention_rate",
    question="What share of claims survive verification?",
    grain="day",
    owner="product",
    caveat="Drawn from existing corpus.evidence_attempts ledger events.",
    sql="""
    SELECT date(occurred_at) AS day, '{}' AS dimension_json,
           CAST(SUM(json_extract(attributes_json, '$.kept_claim_count')) AS REAL)
             / NULLIF(
                 SUM(json_extract(attributes_json, '$.kept_claim_count'))
               + SUM(json_extract(attributes_json, '$.dropped_claim_count')),
               0
             ) AS value,
           CAST(SUM(json_extract(attributes_json, '$.kept_claim_count')) AS REAL) AS numerator,
           CAST(
             SUM(json_extract(attributes_json, '$.kept_claim_count'))
           + SUM(json_extract(attributes_json, '$.dropped_claim_count'))
           AS REAL) AS denominator
      FROM pipeline_events
     WHERE name = 'corpus.evidence_attempts'
     GROUP BY date(occurred_at)
    """,
)

F4 = MetricDefinition(
    key="episodes_per_source_count",
    question="Does corpus size predict success?",
    grain="day",
    owner="product",
    sql=f"""
    WITH confirms AS (
      SELECT project_id,
             CAST(json_extract(properties_json, '$.source_count') AS INTEGER) AS source_count,
             date(occurred_at) AS day
        FROM product_events
       WHERE name = 'gate.corpus_confirmed' AND {_REAL}
    ),
    completed AS (
      SELECT DISTINCT project_id
        FROM product_events
       WHERE name = 'project.stage_entered'
         AND json_extract(properties_json, '$.stage') = 7
         AND {_REAL}
    )
    SELECT c.day,
           json_object('source_count', c.source_count) AS dimension_json,
           CAST(COUNT(DISTINCT done.project_id) AS REAL)
             / NULLIF(COUNT(DISTINCT c.project_id), 0) AS value,
           CAST(COUNT(DISTINCT done.project_id) AS REAL) AS numerator,
           CAST(COUNT(DISTINCT c.project_id) AS REAL) AS denominator
      FROM confirms c
      LEFT JOIN completed done ON done.project_id = c.project_id
     GROUP BY c.day, c.source_count
    """,
)

G1 = MetricDefinition(
    key="stage_failure_rate",
    question="Which stage breaks most?",
    grain="day",
    owner="product",
    sql=f"""
    WITH entered AS (
      SELECT date(occurred_at) AS day,
             CAST(json_extract(properties_json, '$.stage') AS INTEGER) AS stage,
             COUNT(*) AS n
        FROM product_events
       WHERE name = 'project.stage_entered' AND {_REAL}
       GROUP BY 1, 2
    ),
    failed AS (
      SELECT date(occurred_at) AS day,
             CAST(json_extract(properties_json, '$.stage') AS INTEGER) AS stage,
             COUNT(*) AS n
        FROM product_events
       WHERE name = 'project.stage_failed' AND {_REAL}
       GROUP BY 1, 2
    )
    SELECT e.day,
           json_object('stage', e.stage) AS dimension_json,
           CAST(COALESCE(f.n, 0) AS REAL) / NULLIF(e.n, 0) AS value,
           CAST(COALESCE(f.n, 0) AS REAL) AS numerator,
           CAST(e.n AS REAL) AS denominator
      FROM entered e
      LEFT JOIN failed f ON f.day = e.day AND f.stage = e.stage
    """,
)

G2 = MetricDefinition(
    key="recovery_rate",
    question="Do failures self-heal?",
    grain="day",
    owner="product",
    sql=f"""
    WITH failed AS (
      SELECT date(occurred_at) AS day, COUNT(*) AS n
        FROM product_events
       WHERE name = 'project.stage_failed' AND {_REAL}
       GROUP BY date(occurred_at)
    ),
    recovered AS (
      SELECT date(occurred_at) AS day, COUNT(*) AS n
        FROM product_events
       WHERE name = 'project.recovered' AND {_REAL}
       GROUP BY date(occurred_at)
    )
    SELECT f.day, '{{}}' AS dimension_json,
           CAST(COALESCE(r.n, 0) AS REAL) / NULLIF(f.n, 0) AS value,
           CAST(COALESCE(r.n, 0) AS REAL) AS numerator,
           CAST(f.n AS REAL) AS denominator
      FROM failed f
      LEFT JOIN recovered r ON r.day = f.day
    """,
)

G3 = MetricDefinition(
    key="permanent_failure_rate",
    question="How often do we lose a project entirely?",
    grain="day",
    owner="product",
    sql=f"""
    WITH created AS (
      SELECT date(occurred_at) AS day, COUNT(DISTINCT project_id) AS n
        FROM product_events
       WHERE name = 'project.created' AND {_REAL}
       GROUP BY date(occurred_at)
    ),
    permanent AS (
      SELECT date(occurred_at) AS day, COUNT(DISTINCT project_id) AS n
        FROM product_events
       WHERE name = 'project.stage_failed'
         AND json_extract(properties_json, '$.permanent') = 1
         AND {_REAL}
       GROUP BY date(occurred_at)
    )
    SELECT c.day, '{{}}' AS dimension_json,
           CAST(COALESCE(p.n, 0) AS REAL) / NULLIF(c.n, 0) AS value,
           CAST(COALESCE(p.n, 0) AS REAL) AS numerator,
           CAST(c.n AS REAL) AS denominator
      FROM created c
      LEFT JOIN permanent p ON p.day = c.day
    """,
)

G4 = MetricDefinition(
    key="user_visible_failure_rate",
    question="What fraction of users hit any failure?",
    grain="day",
    owner="product",
    sql=f"""
    WITH active AS (
      SELECT date(occurred_at) AS day, COUNT(DISTINCT user_id) AS n
        FROM product_events
       WHERE user_id IS NOT NULL AND {_REAL}
       GROUP BY date(occurred_at)
    ),
    failed AS (
      SELECT date(occurred_at) AS day, COUNT(DISTINCT user_id) AS n
        FROM product_events
       WHERE name = 'project.stage_failed' AND user_id IS NOT NULL AND {_REAL}
       GROUP BY date(occurred_at)
    )
    SELECT a.day, '{{}}' AS dimension_json,
           CAST(COALESCE(f.n, 0) AS REAL) / NULLIF(a.n, 0) AS value,
           CAST(COALESCE(f.n, 0) AS REAL) AS numerator,
           CAST(a.n AS REAL) AS denominator
      FROM active a
      LEFT JOIN failed f ON f.day = a.day
    """,
)

H1_WAU = MetricDefinition(
    key="wau",
    question="Are people coming back at all (7d)?",
    grain="day",
    owner="product",
    sql=f"""
    SELECT date('now') AS day, '{{}}' AS dimension_json,
           CAST(COUNT(DISTINCT user_id) AS REAL) AS value,
           CAST(COUNT(DISTINCT user_id) AS REAL) AS numerator,
           NULL AS denominator
      FROM product_events
     WHERE user_id IS NOT NULL AND {_REAL}
       AND julianday('now') - julianday(occurred_at) <= 7
    """,
)

H1_MAU = MetricDefinition(
    key="mau",
    question="Are people coming back at all (30d)?",
    grain="day",
    owner="product",
    sql=f"""
    SELECT date('now') AS day, '{{}}' AS dimension_json,
           CAST(COUNT(DISTINCT user_id) AS REAL) AS value,
           CAST(COUNT(DISTINCT user_id) AS REAL) AS numerator,
           NULL AS denominator
      FROM product_events
     WHERE user_id IS NOT NULL AND {_REAL}
       AND julianday('now') - julianday(occurred_at) <= 30
    """,
)

H2 = MetricDefinition(
    key="w1_w4_retention",
    question="Do they come back in later weeks?",
    grain="week",
    owner="product",
    sql=f"""
    WITH cohorts AS (
      SELECT user_id, date(MIN(occurred_at), 'weekday 1', '-7 days') AS cohort_week
        FROM product_events
       WHERE name = 'user.registered' AND {_REAL} AND user_id IS NOT NULL
       GROUP BY user_id
    ),
    activity AS (
      SELECT user_id, date(occurred_at, 'weekday 1', '-7 days') AS week
        FROM product_events
       WHERE user_id IS NOT NULL AND {_REAL}
       GROUP BY user_id, date(occurred_at, 'weekday 1', '-7 days')
    )
    SELECT c.cohort_week AS day,
           json_object(
             'week_n',
             CAST((julianday(a.week) - julianday(c.cohort_week)) / 7 AS INTEGER)
           ) AS dimension_json,
           CAST(COUNT(DISTINCT a.user_id) AS REAL) AS value,
           CAST(COUNT(DISTINCT a.user_id) AS REAL) AS numerator,
           CAST((SELECT COUNT(*) FROM cohorts c2 WHERE c2.cohort_week = c.cohort_week) AS REAL)
             AS denominator
      FROM cohorts c
      JOIN activity a ON a.user_id = c.user_id
     WHERE CAST((julianday(a.week) - julianday(c.cohort_week)) / 7 AS INTEGER) BETWEEN 1 AND 4
     GROUP BY c.cohort_week,
              CAST((julianday(a.week) - julianday(c.cohort_week)) / 7 AS INTEGER)
    """,
)

H3 = MetricDefinition(
    key="projects_per_user_p50",
    question="Is this a one-off or a habit?",
    grain="day",
    owner="product",
    sql=f"""
    WITH per_user AS (
      SELECT user_id, COUNT(DISTINCT project_id) AS n
        FROM product_events
       WHERE name = 'project.created' AND {_REAL}
         AND user_id IS NOT NULL
         AND julianday('now') - julianday(occurred_at) <= 30
       GROUP BY user_id
    )
    SELECT date('now') AS day, '{{}}' AS dimension_json,
           CAST(AVG(n) AS REAL) AS value,
           NULL AS numerator, NULL AS denominator
      FROM per_user
    """,
)

H4 = MetricDefinition(
    key="resumption_rate",
    question="Is continue-later real?",
    grain="day",
    owner="product",
    sql=f"""
    WITH ordered AS (
      SELECT project_id, occurred_at,
             LAG(occurred_at) OVER (PARTITION BY project_id ORDER BY occurred_at) AS prev_at
        FROM product_events
       WHERE project_id IS NOT NULL AND {_REAL}
    ),
    gapped AS (
      SELECT DISTINCT project_id
        FROM ordered
       WHERE prev_at IS NOT NULL
         AND (julianday(occurred_at) - julianday(prev_at)) * 24 >= 24
    ),
    completed AS (
      SELECT DISTINCT project_id
        FROM product_events
       WHERE name = 'project.stage_entered'
         AND json_extract(properties_json, '$.stage') = 7
         AND {_REAL}
    ),
    created AS (
      SELECT date(MIN(occurred_at)) AS day, project_id
        FROM product_events
       WHERE name = 'project.created' AND {_REAL}
       GROUP BY project_id
    )
    SELECT c.day, '{{}}' AS dimension_json,
           CAST(COUNT(DISTINCT CASE WHEN g.project_id IS NOT NULL AND done.project_id IS NOT NULL
                                    THEN c.project_id END) AS REAL)
             / NULLIF(COUNT(DISTINCT c.project_id), 0) AS value,
           CAST(COUNT(DISTINCT CASE WHEN g.project_id IS NOT NULL AND done.project_id IS NOT NULL
                                    THEN c.project_id END) AS REAL) AS numerator,
           CAST(COUNT(DISTINCT c.project_id) AS REAL) AS denominator
      FROM created c
      LEFT JOIN gapped g ON g.project_id = c.project_id
      LEFT JOIN completed done ON done.project_id = c.project_id
     GROUP BY c.day
    """,
)

H5 = MetricDefinition(
    key="cost_per_completed_episode",
    question="What does one delivered episode cost?",
    grain="day",
    owner="product",
    caveat="Joins model_calls.cost_micros on project_id.",
    sql=f"""
    WITH completed AS (
      SELECT project_id, date(MIN(occurred_at)) AS day
        FROM product_events
       WHERE name = 'project.stage_entered'
         AND json_extract(properties_json, '$.stage') = 7
         AND {_REAL}
       GROUP BY project_id
    ),
    costs AS (
      SELECT project_id, SUM(cost_micros) AS cost
        FROM model_calls
       WHERE status = 'succeeded' AND cost_micros IS NOT NULL
       GROUP BY project_id
    )
    SELECT c.day, '{{}}' AS dimension_json,
           CAST(SUM(COALESCE(k.cost, 0)) AS REAL)
             / NULLIF(COUNT(DISTINCT c.project_id), 0) AS value,
           CAST(SUM(COALESCE(k.cost, 0)) AS REAL) AS numerator,
           CAST(COUNT(DISTINCT c.project_id) AS REAL) AS denominator
      FROM completed c
      LEFT JOIN costs k ON k.project_id = c.project_id
     GROUP BY c.day
    """,
)

H6 = MetricDefinition(
    key="cost_per_abandoned_project",
    question="What do we spend on projects that die?",
    grain="day",
    owner="product",
    caveat="Max stage < 7 and idle 14d; joins model_calls.",
    sql=f"""
    WITH max_stage AS (
      SELECT project_id,
             MAX(CAST(json_extract(properties_json, '$.stage') AS INTEGER)) AS stage,
             MAX(occurred_at) AS last_at,
             date(MIN(occurred_at)) AS day
        FROM product_events
       WHERE name = 'project.stage_entered' AND {_REAL}
       GROUP BY project_id
    ),
    abandoned AS (
      SELECT project_id, day
        FROM max_stage
       WHERE stage < 7
         AND julianday('now') - julianday(last_at) >= 14
    ),
    costs AS (
      SELECT project_id, SUM(cost_micros) AS cost
        FROM model_calls
       WHERE cost_micros IS NOT NULL
       GROUP BY project_id
    )
    SELECT a.day, '{{}}' AS dimension_json,
           CAST(SUM(COALESCE(k.cost, 0)) AS REAL)
             / NULLIF(COUNT(DISTINCT a.project_id), 0) AS value,
           CAST(SUM(COALESCE(k.cost, 0)) AS REAL) AS numerator,
           CAST(COUNT(DISTINCT a.project_id) AS REAL) AS denominator
      FROM abandoned a
      LEFT JOIN costs k ON k.project_id = a.project_id
     GROUP BY a.day
    """,
)

CATALOGUE: tuple[MetricDefinition, ...] = (
    A1,
    B1,
    B2,
    B3,
    B4,
    B5,
    C1,
    C2_P50,
    C2_P90,
    C3,
    C4,
    D1,
    D2,
    D3,
    D4,
    D5_P50,
    D5_P90,
    E1,
    E2,
    E3,
    E4,
    E5,
    E6,
    E7,
    E8,
    E9,
    E10,
    E11,
    E12,
    E13,
    F1,
    F2,
    F3,
    F4,
    G1,
    G2,
    G3,
    G4,
    H1_WAU,
    H1_MAU,
    H2,
    H3,
    H4,
    H5,
    H6,
)
