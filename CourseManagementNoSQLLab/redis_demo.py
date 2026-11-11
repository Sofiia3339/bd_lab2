import os

from redis import Redis


def main():
    with Redis.from_url(
        os.getenv("LAB_REDIS_URL", "redis://127.0.0.1:56379/0"),
        decode_responses=True, socket_connect_timeout=5,
    ) as redis:
        progress_key = "course_nosql_lab:demo:progress:2"
        token_key = "course_nosql_lab:demo:active:2"
        leaderboard_key = "course_nosql_lab:demo:leaderboard:1"

        redis.set(token_key, "active", ex=60)
        print("SET / GET / TTL:", redis.get(token_key), redis.ttl(token_key))

        redis.hset(progress_key, mapping={"completed": 2, "total": 4})
        completed = redis.hincrby(progress_key, "completed", 1)
        redis.expire(progress_key, 300)
        if completed != 3:
            raise RuntimeError("Unexpected progress count.")
        print("HSET / HINCRBY / HGETALL:", redis.hgetall(progress_key))

        redis.zadd(leaderboard_key, {"student:1": 65, "student:2": 75, "student:3": 90})
        redis.zincrby(leaderboard_key, 20, "student:2")
        redis.expire(leaderboard_key, 300)
        ranking = redis.zrevrange(leaderboard_key, 0, 2, withscores=True)
        if ranking != [("student:2", 95.0), ("student:3", 90.0), ("student:1", 65.0)]:
            raise RuntimeError("Unexpected leaderboard.")
        print("ZADD / ZINCRBY / ZREVRANGE:", ranking)
        print("Redis:", redis.info("server")["redis_version"])


if __name__ == "__main__":
    main()
