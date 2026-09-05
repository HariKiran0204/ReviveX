from unittest.mock import MagicMock, patch
from uuid import uuid4

from pydantic import ValidationError

from recoverai_api.config import Settings
from recoverai_worker.config import WorkerSettings
from recoverai_worker.jobs import process_provider_event, will_retry


def test_retry_settings_are_bounded() -> None:
    assert Settings().worker_max_retries == 3
    assert WorkerSettings().worker_max_retries == 3
    try:
        Settings(worker_max_retries=11)
        raise AssertionError("expected validation error")
    except ValidationError:
        pass
    try:
        WorkerSettings(worker_max_retries=11)
        raise AssertionError("expected validation error")
    except ValidationError:
        pass


def test_will_retry_is_false_without_rq_job() -> None:
    assert will_retry() is False


def test_will_retry_uses_retries_left() -> None:
    job = MagicMock()
    job.retries_left = 2
    with patch("rq.job.get_current_job", return_value=job):
        assert will_retry() is True
    job.retries_left = 0
    with patch("rq.job.get_current_job", return_value=job):
        assert will_retry() is False


def test_will_retry_calls_should_retry_method() -> None:
    job = MagicMock()
    job.retries_left = None
    job.should_retry = MagicMock(return_value=True)
    with patch("rq.job.get_current_job", return_value=job):
        assert will_retry() is True
    job.should_retry.assert_called_once()


def test_process_provider_event_dead_letters_when_retries_exhausted() -> None:
    event_id = uuid4()
    session = MagicMock()
    dead_session = MagicMock()
    sessions = iter([session, dead_session])

    def session_factory(_url: str) -> MagicMock:
        return next(sessions)

    with (
        patch("recoverai_worker.jobs.get_worker_settings") as settings,
        patch("recoverai_worker.jobs.SessionLocal", side_effect=session_factory),
        patch(
            "recoverai_worker.jobs.process_webhook_event",
            side_effect=RuntimeError("transient"),
        ),
        patch("recoverai_worker.jobs.will_retry", return_value=False),
        patch("recoverai_worker.jobs.mark_dead_letter") as dead_letter,
    ):
        settings.return_value.database_url = "postgresql+psycopg://example/recoverai"
        try:
            process_provider_event(str(event_id))
        except RuntimeError:
            pass
    dead_letter.assert_called_once()
    assert dead_letter.call_args[0][1] == event_id
    session.rollback.assert_called()
    session.commit.assert_not_called()
    dead_session.commit.assert_called_once()


def test_process_provider_event_does_not_dead_letter_when_retrying() -> None:
    event_id = uuid4()
    session = MagicMock()
    with (
        patch("recoverai_worker.jobs.get_worker_settings") as settings,
        patch("recoverai_worker.jobs.SessionLocal", return_value=session),
        patch(
            "recoverai_worker.jobs.process_webhook_event",
            side_effect=RuntimeError("transient"),
        ),
        patch("recoverai_worker.jobs.will_retry", return_value=True),
        patch("recoverai_worker.jobs.mark_dead_letter") as dead_letter,
    ):
        settings.return_value.database_url = "postgresql+psycopg://example/recoverai"
        try:
            process_provider_event(str(event_id))
        except RuntimeError:
            pass
    dead_letter.assert_not_called()
    session.rollback.assert_called()
    session.commit.assert_not_called()
