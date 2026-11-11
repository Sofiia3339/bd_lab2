import random


def make_session(session_id, student_count, rng):
    attempts = []
    for position in range(1, 5):
        answers = []
        for question_no in range(1, 4):
            choice = rng.randint(1, 4)
            answers.append({"question_no": question_no, "choice": choice, "correct": choice == 2})
        score = round(100 * sum(answer["correct"] for answer in answers) / len(answers))
        attempts.append({
            "position": position, "lesson_id": position,
            "duration_seconds": rng.randint(30, 600), "score": score, "answers": answers,
        })
    return {
        "_id": session_id,
        "student_id": (session_id - 1) % student_count + 1,
        "course_id": (session_id - 1) % 12 + 1,
        "started_at": 1700000000 + session_id * 60,
        "attempts": attempts,
    }


def seed_both(connection, collection, count, student_count, seed):
    rng = random.Random(seed)
    batch_size = 2000
    for start in range(1, count + 1, batch_size):
        batch = [
            make_session(session_id, student_count, rng)
            for session_id in range(start, min(start + batch_size, count + 1))
        ]
        with connection.transaction(), connection.cursor() as cursor:
            with cursor.copy("COPY nosql_lab.sessions FROM STDIN") as rows:
                for session in batch:
                    rows.write_row((
                        session["_id"], session["student_id"], session["course_id"], session["started_at"],
                    ))
            with cursor.copy("COPY nosql_lab.attempts FROM STDIN") as rows:
                for session in batch:
                    for attempt in session["attempts"]:
                        rows.write_row((
                            session["_id"], attempt["position"], attempt["lesson_id"],
                            attempt["duration_seconds"], attempt["score"],
                        ))
            with cursor.copy("COPY nosql_lab.answers FROM STDIN") as rows:
                for session in batch:
                    for attempt in session["attempts"]:
                        for answer in attempt["answers"]:
                            rows.write_row((
                                session["_id"], attempt["position"], answer["question_no"],
                                answer["choice"], answer["correct"],
                            ))
        collection.insert_many(batch)
    connection.execute("ANALYZE nosql_lab.sessions")
    connection.execute("ANALYZE nosql_lab.attempts")
    connection.execute("ANALYZE nosql_lab.answers")
