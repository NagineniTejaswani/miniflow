from pydantic import BaseModel, ConfigDict, Field

from enum import Enum


class JobState(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"

class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")  # reject unknown fields

    image: str = Field(min_length=1)
    command: list[str] = Field(min_length=1)
    needs: list[str] = Field(default_factory=list)


class Workflow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    jobs: dict[str, Job] = Field(min_length=1)