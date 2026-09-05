from recoverai_worker.jobs import health_heartbeat


def test_health_heartbeat_job_payload() -> None:
    result = health_heartbeat("worker-test")
    assert result["worker"] == "worker-test"
    assert result["status"] == "ok"
    assert "timestamp" in result
