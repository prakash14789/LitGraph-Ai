"""Unit test for src.tasks.ingest_task — mocked pipeline/engine/driver, no
real I/O. Covers the live bug found running back-to-back real ingestions:
the async engine and Neo4j driver (both process-lifetime singletons) must
be disposed/closed at the end of every task, even on failure, or the next
task's fresh asyncio.run() event loop gets handed a stale pooled
connection from this one's now-closed loop."""

from unittest.mock import AsyncMock, patch

import pytest

from src.tasks.ingest_task import process_paper


@patch("src.tasks.ingest_task.close_driver", new_callable=AsyncMock)
@patch("src.tasks.ingest_task.engine")
@patch("src.tasks.ingest_task.run_pipeline", new_callable=AsyncMock)
def test_process_paper_disposes_engine_and_driver_after_success(
    mock_run_pipeline, mock_engine, mock_close_driver
):
    mock_engine.dispose = AsyncMock()

    process_paper("job-1")

    mock_run_pipeline.assert_awaited_once_with("job-1")
    mock_engine.dispose.assert_awaited_once()
    mock_close_driver.assert_awaited_once()


@patch("src.tasks.ingest_task.close_driver", new_callable=AsyncMock)
@patch("src.tasks.ingest_task.engine")
@patch("src.tasks.ingest_task.run_pipeline", new_callable=AsyncMock)
def test_process_paper_disposes_engine_and_driver_even_on_failure(
    mock_run_pipeline, mock_engine, mock_close_driver
):
    mock_engine.dispose = AsyncMock()
    mock_run_pipeline.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        process_paper("job-1")

    mock_engine.dispose.assert_awaited_once()
    mock_close_driver.assert_awaited_once()
