import argparse
import csv
import json
import math
import platform
import random
import statistics
from pathlib import Path
from time import perf_counter_ns

from bson import json_util

from seed import make_session, seed_both
from storage import (
    GET_RECENT, GET_SESSION, RECENT_INDEX, connect_mongo, connect_postgres,
    mongo_recent, reset_mongo, reset_postgres, sql_get, sql_insert, sql_recent,
)


def measure(operation):
    started = perf_counter_ns()
    operation()
    return (perf_counter_ns() - started) / 1_000_000


def check_equal(expected, actual, label):
    if expected != actual:
        raise RuntimeError(f"SQL and MongoDB differ: {label}")


def save_plans(connection, collection, size, output):
    plans = {"postgresql": {}, "mongodb": {}}
    for name, sql, parameter, find in (
        ("by_id", GET_SESSION, size // 2, {"filter": {"_id": size // 2}}),
        ("recent_10", GET_RECENT, 1, {
            "filter": {"student_id": 1}, "sort": dict(RECENT_INDEX[1:]), "limit": 10,
        }),
    ):
        plans["postgresql"][name] = connection.execute(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, (parameter,)
        ).fetchone()[0]
        plans["mongodb"][name] = collection.database.command({
            "explain": {"find": collection.name, **find},
            "verbosity": "executionStats",
        })
    (output / f"plans-{size}.json").write_text(json_util.dumps(plans, indent=2) + "\n")


def run_scale(connection, collection, size, args, output, writer):
    student_count = size // 20
    reset_postgres(connection)
    reset_mongo(collection)
    seed_both(connection, collection, size, student_count, args.seed)
    rng = random.Random(args.seed + size)
    sql_count = connection.execute("SELECT count(*) FROM nosql_lab.sessions").fetchone()[0]
    check_equal(size, sql_count, "SQL count")
    check_equal(size, collection.count_documents({}), "MongoDB count")

    for _ in range(30):
        session_id = rng.randint(1, size)
        student_id = rng.randint(1, student_count)
        check_equal(sql_get(connection, session_id), collection.find_one({"_id": session_id}), session_id)
        history = sql_recent(connection, student_id)
        check_equal(10, len(history), "recent history size")
        check_equal(history, mongo_recent(collection, student_id), student_id)
    save_plans(connection, collection, size, output)
    print(f"{size:,} sessions seeded and checked. Measuring...", flush=True)

    samples = {}

    def time_pair(operation, round_no, number, sql_call, mongo_call):
        pair = [("PostgreSQL", sql_call), ("MongoDB", mongo_call)]
        if (number + round_no) % 2:
            pair.reverse()
        for engine, call in pair:
            latency_ms = measure(call)
            writer.writerow([size, round_no, operation, number, engine, f"{latency_ms:.6f}"])
            samples.setdefault((operation, engine), []).append(latency_ms)

    def remove_inserted():
        connection.execute("DELETE FROM nosql_lab.sessions WHERE id > %s", (size,))
        collection.delete_many({"_id": {"$gt": size}})

    for number in range(1, 11):
        document = make_session(size + number, student_count, rng)
        sql_insert(connection, document)
        collection.insert_one(document)
    remove_inserted()

    # Keep reads on the original dataset before the timed write series.
    for round_no in range(1, args.rounds + 1):
        for number in range(1, args.reads + 1):
            session_id = rng.randint(1, size)
            time_pair("by_id", round_no, number, lambda: sql_get(connection, session_id),
                      lambda: collection.find_one({"_id": session_id}))
            student_id = rng.randint(1, student_count)
            time_pair("recent_10", round_no, number, lambda: sql_recent(connection, student_id),
                      lambda: mongo_recent(collection, student_id))

    for round_no in range(1, args.rounds + 1):
        for number in range(1, args.writes + 1):
            document = make_session(size + number, student_count, rng)
            time_pair("insert", round_no, number, lambda: sql_insert(connection, document),
                      lambda: collection.insert_one(document))
        check_equal(document, sql_get(connection, document["_id"]), "SQL insert payload")
        check_equal(document, collection.find_one({"_id": document["_id"]}), "MongoDB insert payload")
        check_equal(args.writes, connection.execute(
            "SELECT count(*) FROM nosql_lab.sessions WHERE id > %s", (size,)
        ).fetchone()[0], "SQL inserted rows")
        check_equal(args.writes, collection.count_documents({"_id": {"$gt": size}}), "MongoDB inserts")
        remove_inserted()

    summary = []
    for (operation, engine), latencies in sorted(samples.items()):
        ordered = sorted(latencies)
        summary.append([size, operation, engine, len(ordered),
                        f"{statistics.median(ordered):.6f}",
                        f"{ordered[math.ceil(0.95 * len(ordered)) - 1]:.6f}"])
    return summary


def main():
    parser = argparse.ArgumentParser(description="Compare nested MongoDB documents with normalized PostgreSQL.")
    parser.add_argument("--sizes", type=int, nargs="+", default=[2000, 20000, 100000])
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--reads", type=int, default=250, help="Requests per read scenario per round.")
    parser.add_argument("--writes", type=int, default=100, help="Writes per round.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("results-local"))
    args = parser.parse_args()
    if min(args.sizes) < 20 or min(args.rounds, args.reads, args.writes) < 1:
        parser.error("Sizes must be at least 20 and counts must be positive.")
    args.output.mkdir(parents=True, exist_ok=True)

    mongo, collection = connect_mongo()
    with mongo, connect_postgres() as connection:
        metadata = {
            "postgresql": connection.execute("SHOW server_version").fetchone()[0],
            "postgresql_fsync": connection.execute("SHOW fsync").fetchone()[0],
            "postgresql_shared_buffers": connection.execute("SHOW shared_buffers").fetchone()[0],
            "postgresql_full_page_writes": connection.execute("SHOW full_page_writes").fetchone()[0],
            "mongodb_cache_limit_bytes": mongo.admin.command("serverStatus")["wiredTiger"]["cache"]["maximum bytes configured"],
            "postgresql_synchronous_commit": connection.execute("SHOW synchronous_commit").fetchone()[0],
            "mongodb": mongo.server_info()["version"],
            "mongodb_write_concern": collection.write_concern.document,
            "platform": f"{platform.system()} {platform.machine()}",
            "python": platform.python_version(),
            "sizes": args.sizes, "rounds": args.rounds,
            "reads_per_round_per_scenario": args.reads, "writes_per_round": args.writes,
            "seed": args.seed,
        }
        if metadata["postgresql_fsync"] != "on":
            raise RuntimeError("Enable PostgreSQL fsync for this comparison.")
        (args.output / "environment.json").write_text(json.dumps(metadata, indent=2) + "\n")
        summary = []
        with (args.output / "samples.csv").open("w", newline="") as samples:
            writer = csv.writer(samples)
            writer.writerow(["sessions", "round", "scenario", "sample", "engine", "ms"])
            for size in args.sizes:
                summary.extend(run_scale(connection, collection, size, args, args.output, writer))
        with (args.output / "summary.csv").open("w", newline="") as destination:
            writer = csv.writer(destination)
            writer.writerow(["sessions", "scenario", "engine", "samples", "p50_ms", "p95_ms"])
            writer.writerows(summary)
    print(f"Finished. Results: {args.output.resolve()}", flush=True)


if __name__ == "__main__":
    main()
