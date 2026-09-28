import ipaddress
import json
import sqlite3
import time
import threading
from config import STATS_DB_FILE


ACTIVE_WINDOW_SECONDS = 5 * 60
WARNING_NETWORKS = 8
CRITICAL_NETWORKS = 10
ACTIVITY_RETENTION_DAYS = 90
SECURITY_RETENTION_DAYS = 180

_INIT_LOCK = threading.Lock()
_INITIALIZED = False


def _connect() -> sqlite3.Connection:
    STATS_DB_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(
        STATS_DB_FILE,
        timeout=5,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def init_stats_db() -> None:
    global _INITIALIZED

    if _INITIALIZED:
        return

    with _INIT_LOCK:
        if _INITIALIZED:
            return

        with _connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
            CREATE TABLE IF NOT EXISTS activity_ips (
                username TEXT NOT NULL,
                node TEXT NOT NULL,
                network_key TEXT NOT NULL,
                sample_ip TEXT NOT NULL,
                protocol TEXT NOT NULL,
                first_seen INTEGER NOT NULL,
                last_seen INTEGER NOT NULL,
                connections INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (
                    username,
                    node,
                    network_key,
                    protocol
                )
            );

            CREATE INDEX IF NOT EXISTS idx_activity_user_seen
            ON activity_ips(username, last_seen DESC);

            CREATE INDEX IF NOT EXISTS idx_activity_seen
            ON activity_ips(last_seen DESC);

            CREATE TABLE IF NOT EXISTS usage_hourly (
                username TEXT NOT NULL,
                node TEXT NOT NULL,
                protocol TEXT NOT NULL,
                hour_start INTEGER NOT NULL,
                connections INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (
                    username,
                    node,
                    protocol,
                    hour_start
                )
            );

            CREATE INDEX IF NOT EXISTS idx_usage_hour
            ON usage_hourly(hour_start DESC);

            CREATE INDEX IF NOT EXISTS idx_usage_user_hour
            ON usage_hourly(username, hour_start DESC);

            CREATE TABLE IF NOT EXISTS abuse_state (
                username TEXT PRIMARY KEY,
                level TEXT NOT NULL,
                active_networks INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS security_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                value INTEGER,
                details TEXT,
                created_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_security_user_created
            ON security_events(username, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_security_created
            ON security_events(created_at DESC);
                """
            )

        _INITIALIZED = True


def normalize_source_ip(source_ip: str) -> tuple[str, str]:
    value = source_ip.strip().strip("[]")

    if "%" in value:
        value = value.split("%", 1)[0]

    address = ipaddress.ip_address(value)

    if isinstance(address, ipaddress.IPv6Address):
        mapped = address.ipv4_mapped
        if mapped is not None:
            normalized = str(mapped)
            return normalized, normalized

        network = ipaddress.ip_network(
            f"{address}/64",
            strict=False,
        )
        return str(address), str(network)

    normalized = str(address)
    return normalized, normalized


def _risk_level(active_networks: int) -> str:
    if active_networks >= CRITICAL_NETWORKS:
        return "critical"
    if active_networks >= WARNING_NETWORKS:
        return "warning"
    return "normal"


def record_activity(
    username: str,
    node: str,
    protocol: str,
    source_ip: str,
    seen_at: int | None = None,
) -> dict:
    init_stats_db()

    timestamp = int(seen_at or time.time())
    sample_ip, network_key = normalize_source_ip(source_ip)
    hour_start = timestamp - (timestamp % 3600)

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO activity_ips (
                username,
                node,
                network_key,
                sample_ip,
                protocol,
                first_seen,
                last_seen,
                connections
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT (
                username,
                node,
                network_key,
                protocol
            )
            DO UPDATE SET
                sample_ip = excluded.sample_ip,
                first_seen = MIN(
                    activity_ips.first_seen,
                    excluded.first_seen
                ),
                last_seen = MAX(
                    activity_ips.last_seen,
                    excluded.last_seen
                ),
                connections = activity_ips.connections + 1
            """,
            (
                username,
                node,
                network_key,
                sample_ip,
                protocol,
                timestamp,
                timestamp,
            ),
        )

        connection.execute(
            """
            INSERT INTO usage_hourly (
                username,
                node,
                protocol,
                hour_start,
                connections
            )
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT (
                username,
                node,
                protocol,
                hour_start
            )
            DO UPDATE SET
                connections = usage_hourly.connections + 1
            """,
            (
                username,
                node,
                protocol,
                hour_start,
            ),
        )

        active_networks = connection.execute(
            """
            SELECT COUNT(DISTINCT network_key)
            FROM activity_ips
            WHERE username = ?
              AND last_seen >= ?
            """,
            (
                username,
                timestamp - ACTIVE_WINDOW_SECONDS,
            ),
        ).fetchone()[0]

        new_level = _risk_level(active_networks)
        previous = connection.execute(
            """
            SELECT level
            FROM abuse_state
            WHERE username = ?
            """,
            (username,),
        ).fetchone()
        previous_level = previous["level"] if previous else "normal"

        connection.execute(
            """
            INSERT INTO abuse_state (
                username,
                level,
                active_networks,
                updated_at
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(username)
            DO UPDATE SET
                level = excluded.level,
                active_networks = excluded.active_networks,
                updated_at = excluded.updated_at
            """,
            (
                username,
                new_level,
                active_networks,
                timestamp,
            ),
        )

        if (
            new_level != previous_level
            and new_level in {"warning", "critical"}
        ):
            details = json.dumps(
                {
                    "active_window_seconds": ACTIVE_WINDOW_SECONDS,
                    "active_networks": active_networks,
                    "node": node,
                    "protocol": protocol,
                    "network_key": network_key,
                    "sample_ip": sample_ip,
                },
                ensure_ascii=False,
            )

            connection.execute(
                """
                INSERT INTO security_events (
                    username,
                    event_type,
                    severity,
                    value,
                    details,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    username,
                    "network_spike",
                    new_level,
                    active_networks,
                    details,
                    timestamp,
                ),
            )

    return {
        "username": username,
        "node": node,
        "protocol": protocol,
        "sample_ip": sample_ip,
        "network_key": network_key,
        "active_networks": active_networks,
        "risk": new_level,
    }


def _summary_for_user(
    connection: sqlite3.Connection,
    username: str,
    now: int,
) -> dict:
    cutoff_5m = now - ACTIVE_WINDOW_SECONDS
    cutoff_24h = now - 24 * 60 * 60
    current_hour = now - (now % 3600)
    hourly_cutoff = current_hour - 23 * 3600

    base = connection.execute(
        """
        SELECT
            MAX(last_seen) AS last_seen,
            COUNT(DISTINCT CASE
                WHEN last_seen >= ? THEN network_key
            END) AS active_networks_5m,
            COUNT(DISTINCT CASE
                WHEN last_seen >= ? THEN network_key
            END) AS networks_24h
        FROM activity_ips
        WHERE username = ?
        """,
        (
            cutoff_5m,
            cutoff_24h,
            username,
        ),
    ).fetchone()

    connections_24h = connection.execute(
        """
        SELECT COALESCE(SUM(connections), 0)
        FROM usage_hourly
        WHERE username = ?
          AND hour_start >= ?
        """,
        (
            username,
            hourly_cutoff,
        ),
    ).fetchone()[0]

    nodes = [
        row[0]
        for row in connection.execute(
            """
            SELECT DISTINCT node
            FROM activity_ips
            WHERE username = ?
              AND last_seen >= ?
            ORDER BY node
            """,
            (username, cutoff_24h),
        )
    ]

    protocols = [
        row[0]
        for row in connection.execute(
            """
            SELECT DISTINCT protocol
            FROM activity_ips
            WHERE username = ?
              AND last_seen >= ?
            ORDER BY protocol
            """,
            (username, cutoff_24h),
        )
    ]

    active_networks = int(base["active_networks_5m"] or 0)

    return {
        "last_seen": base["last_seen"],
        "active": bool(
            base["last_seen"]
            and base["last_seen"] >= cutoff_5m
        ),
        "active_networks_5m": active_networks,
        "networks_24h": int(base["networks_24h"] or 0),
        "connections_24h": int(connections_24h or 0),
        "nodes_24h": nodes,
        "protocols_24h": protocols,
        "risk": _risk_level(active_networks),
    }


def get_user_summaries(
    usernames: list[str] | tuple[str, ...] | set[str],
) -> dict[str, dict]:
    init_stats_db()
    now = int(time.time())

    with _connect() as connection:
        return {
            username: _summary_for_user(
                connection,
                username,
                now,
            )
            for username in usernames
        }


def get_overview() -> dict:
    init_stats_db()
    now = int(time.time())
    cutoff_5m = now - ACTIVE_WINDOW_SECONDS
    cutoff_24h = now - 24 * 60 * 60
    current_hour = now - (now % 3600)
    hourly_cutoff = current_hour - 23 * 3600

    with _connect() as connection:
        active_users_5m = connection.execute(
            """
            SELECT COUNT(DISTINCT username)
            FROM activity_ips
            WHERE last_seen >= ?
            """,
            (cutoff_5m,),
        ).fetchone()[0]

        active_users_24h = connection.execute(
            """
            SELECT COUNT(DISTINCT username)
            FROM activity_ips
            WHERE last_seen >= ?
            """,
            (cutoff_24h,),
        ).fetchone()[0]

        networks_24h = connection.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT DISTINCT username, network_key
                FROM activity_ips
                WHERE last_seen >= ?
            )
            """,
            (cutoff_24h,),
        ).fetchone()[0]

        connections_24h = connection.execute(
            """
            SELECT COALESCE(SUM(connections), 0)
            FROM usage_hourly
            WHERE hour_start >= ?
            """,
            (hourly_cutoff,),
        ).fetchone()[0]

        alerts_24h = connection.execute(
            """
            SELECT COUNT(*)
            FROM security_events
            WHERE created_at >= ?
              AND severity IN ('warning', 'critical')
            """,
            (cutoff_24h,),
        ).fetchone()[0]

    return {
        "active_users_5m": int(active_users_5m or 0),
        "active_users_24h": int(active_users_24h or 0),
        "networks_24h": int(networks_24h or 0),
        "connections_24h": int(connections_24h or 0),
        "alerts_24h": int(alerts_24h or 0),
        "warning_networks": WARNING_NETWORKS,
        "critical_networks": CRITICAL_NETWORKS,
        "active_window_seconds": ACTIVE_WINDOW_SECONDS,
    }


def get_user_details(
    username: str,
    limit: int = 30,
) -> dict:
    init_stats_db()
    now = int(time.time())
    cutoff_24h = now - 24 * 60 * 60
    current_hour = now - (now % 3600)
    hourly_cutoff = current_hour - 23 * 3600

    with _connect() as connection:
        summary = _summary_for_user(
            connection,
            username,
            now,
        )

        recent_networks = [
            dict(row)
            for row in connection.execute(
                """
                SELECT
                    network_key,
                    sample_ip,
                    node,
                    protocol,
                    first_seen,
                    last_seen,
                    connections
                FROM activity_ips
                WHERE username = ?
                ORDER BY last_seen DESC
                LIMIT ?
                """,
                (username, limit),
            )
        ]

        recent_alerts = []
        for row in connection.execute(
            """
            SELECT
                id,
                event_type,
                severity,
                value,
                details,
                created_at
            FROM security_events
            WHERE username = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (username, limit),
        ):
            item = dict(row)
            try:
                item["details"] = json.loads(
                    item["details"] or "{}"
                )
            except json.JSONDecodeError:
                item["details"] = {}
            recent_alerts.append(item)

        usage_by_node = [
            dict(row)
            for row in connection.execute(
                """
                SELECT
                    node,
                    protocol,
                    SUM(connections) AS connections
                FROM usage_hourly
                WHERE username = ?
                  AND hour_start >= ?
                GROUP BY node, protocol
                ORDER BY connections DESC
                """,
                (username, hourly_cutoff),
            )
        ]

        recent_24h_networks = connection.execute(
            """
            SELECT COUNT(DISTINCT network_key)
            FROM activity_ips
            WHERE username = ?
              AND last_seen >= ?
            """,
            (username, cutoff_24h),
        ).fetchone()[0]

    return {
        "username": username,
        "summary": summary,
        "recent_networks": recent_networks,
        "recent_alerts": recent_alerts,
        "usage_by_node_24h": usage_by_node,
        "networks_24h": int(recent_24h_networks or 0),
    }


def delete_user_stats(username: str) -> None:
    init_stats_db()

    with _connect() as connection:
        connection.execute(
            "DELETE FROM activity_ips WHERE username = ?",
            (username,),
        )
        connection.execute(
            "DELETE FROM usage_hourly WHERE username = ?",
            (username,),
        )
        connection.execute(
            "DELETE FROM abuse_state WHERE username = ?",
            (username,),
        )
        connection.execute(
            "DELETE FROM security_events WHERE username = ?",
            (username,),
        )


def cleanup_stats(now: int | None = None) -> None:
    init_stats_db()
    timestamp = int(now or time.time())
    activity_cutoff = (
        timestamp - ACTIVITY_RETENTION_DAYS * 24 * 60 * 60
    )
    security_cutoff = (
        timestamp - SECURITY_RETENTION_DAYS * 24 * 60 * 60
    )

    with _connect() as connection:
        connection.execute(
            "DELETE FROM activity_ips WHERE last_seen < ?",
            (activity_cutoff,),
        )
        connection.execute(
            "DELETE FROM usage_hourly WHERE hour_start < ?",
            (activity_cutoff,),
        )
        connection.execute(
            "DELETE FROM security_events WHERE created_at < ?",
            (security_cutoff,),
        )
