"""Tests for schedule configuration."""

from pathlib import Path

import pytest
import yaml

from app.models.schedule_config import ScheduleConfig, get_system_timezone, load_schedule_config


@pytest.fixture
def schedule_with_config(temp_vault: Path):
    """Create a vault with a .prime/schedule.yaml config file."""

    def _create_config(config: dict):
        prime_dir = temp_vault / ".prime"
        prime_dir.mkdir(parents=True, exist_ok=True)
        config_file = prime_dir / "schedule.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config, f)
        return temp_vault

    return _create_config


class TestScheduleConfig:
    """Tests for ScheduleConfig model."""

    def test_default_config(self):
        """Default config uses UTC timezone and no jobs."""
        config = ScheduleConfig()
        assert config.timezone == get_system_timezone()
        assert config.jobs == []

    def test_load_missing_config(self, temp_vault: Path):
        """Missing .prime/schedule.yaml returns default config."""
        config = load_schedule_config(temp_vault)
        assert config.timezone == get_system_timezone()
        assert config.jobs == []

    def test_load_custom_config(self, schedule_with_config):
        """Load custom schedule config."""
        vault = schedule_with_config(
            {
                "timezone": "Europe/Berlin",
                "jobs": [
                    {
                        "id": "daily-brief",
                        "command": "dailyBrief",
                        "cron": "0 6 * * *",
                        "overlap": "queue",
                        "queue_max": 1,
                    }
                ],
            }
        )
        config = load_schedule_config(vault)
        assert config.timezone == "Europe/Berlin"
        assert len(config.jobs) == 1
        assert config.jobs[0].command == "dailyBrief"

    def test_invalid_cron_raises(self, schedule_with_config):
        """Invalid cron expressions raise validation error."""
        vault = schedule_with_config(
            {
                "jobs": [
                    {
                        "id": "bad-cron",
                        "command": "dailyBrief",
                        "cron": "not-a-cron",
                    }
                ]
            }
        )
        with pytest.raises(ValueError, match="Invalid cron expression"):
            load_schedule_config(vault)

    def test_duplicate_job_ids_raises(self, schedule_with_config):
        """Duplicate job ids raise validation error."""
        vault = schedule_with_config(
            {
                "jobs": [
                    {
                        "id": "dup",
                        "command": "dailyBrief",
                        "cron": "0 6 * * *",
                    },
                    {
                        "id": "dup",
                        "command": "dailyBrief",
                        "cron": "0 7 * * *",
                    },
                ]
            }
        )
        with pytest.raises(ValueError, match="Duplicate job ids"):
            load_schedule_config(vault)
