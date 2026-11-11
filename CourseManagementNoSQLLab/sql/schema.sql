CREATE SCHEMA IF NOT EXISTS nosql_lab;

CREATE TABLE IF NOT EXISTS nosql_lab.sessions (
    id integer PRIMARY KEY,
    student_id integer NOT NULL,
    course_id integer NOT NULL,
    started_at bigint NOT NULL
);

CREATE TABLE IF NOT EXISTS nosql_lab.attempts (
    session_id integer REFERENCES nosql_lab.sessions(id) ON DELETE CASCADE,
    position integer NOT NULL CHECK (position > 0),
    lesson_id integer NOT NULL,
    duration_seconds integer NOT NULL CHECK (duration_seconds >= 0),
    score integer NOT NULL CHECK (score BETWEEN 0 AND 100),
    PRIMARY KEY (session_id, position)
);

CREATE TABLE IF NOT EXISTS nosql_lab.answers (
    session_id integer,
    attempt_position integer,
    question_no integer CHECK (question_no > 0),
    choice integer NOT NULL CHECK (choice BETWEEN 1 AND 4),
    correct boolean NOT NULL,
    PRIMARY KEY (session_id, attempt_position, question_no),
    FOREIGN KEY (session_id, attempt_position)
        REFERENCES nosql_lab.attempts(session_id, position) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS sessions_student_recent_idx
    ON nosql_lab.sessions(student_id, started_at DESC, id DESC);
