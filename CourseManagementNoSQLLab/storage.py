import os
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb
from pymongo import MongoClient
from pymongo.write_concern import WriteConcern

POSTGRES_DSN = "postgresql://lab:lab_local@127.0.0.1:55432/course_nosql_lab"
MONGO_URI = "mongodb://127.0.0.1:57017/?retryWrites=false"
MONGO_DATABASE = "course_nosql_lab"
MONGO_COLLECTION = "study_sessions"
RECENT_INDEX = [("student_id", 1), ("started_at", -1), ("_id", -1)]

# The same document shape is returned by both stores.
SESSION_JSON = """
SELECT jsonb_build_object(
    '_id', s.id, 'student_id', s.student_id, 'course_id', s.course_id,
    'started_at', s.started_at,
    'attempts', COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
            'position', a.position, 'lesson_id', a.lesson_id,
            'duration_seconds', a.duration_seconds, 'score', a.score,
            'answers', COALESCE((
                SELECT jsonb_agg(jsonb_build_object(
                    'question_no', q.question_no, 'choice', q.choice,
                    'correct', q.correct
                ) ORDER BY q.question_no)
                FROM nosql_lab.answers AS q
                WHERE q.session_id = a.session_id AND q.attempt_position = a.position
            ), '[]'::jsonb)
        ) ORDER BY a.position)
        FROM nosql_lab.attempts AS a WHERE a.session_id = s.id
    ), '[]'::jsonb)
)
"""
GET_SESSION = SESSION_JSON + " FROM nosql_lab.sessions AS s WHERE s.id = %s"
GET_RECENT = SESSION_JSON + """
FROM (
    SELECT id, student_id, course_id, started_at
    FROM nosql_lab.sessions
    WHERE student_id = %s
    ORDER BY started_at DESC, id DESC
    LIMIT 10
) AS s
ORDER BY s.started_at DESC, s.id DESC
"""

# One parameterized statement and one commit. JSONB is only an input parameter.
INSERT_SESSION = """
WITH input AS (
    SELECT %s::jsonb AS data
), inserted_session AS (
    INSERT INTO nosql_lab.sessions(id, student_id, course_id, started_at)
    SELECT (data->>'_id')::int, (data->>'student_id')::int,
           (data->>'course_id')::int, (data->>'started_at')::bigint
    FROM input RETURNING id
), attempts AS (
    SELECT s.id AS session_id, a.position, a.lesson_id,
           a.duration_seconds, a.score, a.answers
    FROM input
    CROSS JOIN inserted_session AS s
    CROSS JOIN LATERAL jsonb_to_recordset(data->'attempts') AS a(
        position int, lesson_id int, duration_seconds int, score int, answers jsonb
    )
), inserted_attempts AS (
    INSERT INTO nosql_lab.attempts(session_id, position, lesson_id, duration_seconds, score)
    SELECT session_id, position, lesson_id, duration_seconds, score FROM attempts
    RETURNING session_id, position
)
INSERT INTO nosql_lab.answers(session_id, attempt_position, question_no, choice, correct)
SELECT a.session_id, a.position, q.question_no, q.choice, q.correct
FROM attempts AS a
JOIN inserted_attempts AS i USING (session_id, position)
CROSS JOIN LATERAL jsonb_to_recordset(a.answers) AS q(question_no int, choice int, correct bool)
"""


def connect_postgres():
    connection = psycopg.connect(
        os.getenv("LAB_POSTGRES_DSN", POSTGRES_DSN),
        autocommit=True, connect_timeout=5,
    )
    connection.execute("SET synchronous_commit = on")
    return connection


def connect_mongo():
    client = MongoClient(os.getenv("LAB_MONGO_URI", MONGO_URI), serverSelectionTimeoutMS=5000)
    collection = client[MONGO_DATABASE].get_collection(
        MONGO_COLLECTION, write_concern=WriteConcern(w=1, j=True)
    )
    return client, collection


def reset_postgres(connection):
    connection.execute((Path(__file__).parent / "sql" / "schema.sql").read_text())
    connection.execute("TRUNCATE nosql_lab.answers, nosql_lab.attempts, nosql_lab.sessions")


def reset_mongo(collection):
    collection.drop()
    collection.create_index(RECENT_INDEX, name="student_recent_idx")


def sql_get(connection, session_id):
    row = connection.execute(GET_SESSION, (session_id,)).fetchone()
    return row[0] if row else None


def sql_recent(connection, student_id):
    return [row[0] for row in connection.execute(GET_RECENT, (student_id,))]


def sql_insert(connection, document):
    connection.execute(INSERT_SESSION, (Jsonb(document),))


def mongo_recent(collection, student_id):
    return list(collection.find({"student_id": student_id}).sort(RECENT_INDEX[1:]).limit(10))
