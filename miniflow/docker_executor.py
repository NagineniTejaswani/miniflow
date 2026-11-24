from dataclasses import dataclass
import threading
import docker
from docker.errors import APIError, ImageNotFound
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import ReadTimeout
from docker.errors import DockerException

from .executor import FailureKind, JobResult
from .models import Job

APPROVED_IMAGES = {"alpine:3.20", "python:3.12-slim"}


class ImageNotApproved(Exception):
    """Raised when a job asks for an image that is not on the allowlist."""


@dataclass
class ContainerResult:
    exit_code: int
    stdout: str
    stderr: str
    oom_killed: bool
    timed_out: bool
    container_id: str

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    @property
    def reason(self) -> str:
        if self.timed_out:
            return "timed out"
        if self.oom_killed:
            return "out of memory"
        if self.exit_code != 0:
            return f"exit code {self.exit_code}"
        return "ok"


class DockerExecutor:
    def __init__(self, approved_images: set[str] | None = None) -> None:
        self.approved_images = approved_images or APPROVED_IMAGES
        self._client = None
        self._client_lock = threading.Lock()
        self._image_lock = threading.Lock()

    @property
    def client(self):
        with self._client_lock:
            if self._client is None:
                self._client = docker.from_env()
        return self._client

    def _ensure_image(self, image: str) -> None:
        with self._image_lock:        # avoid pulling the same image twice at once
            try:
                self.client.images.get(image)
            except ImageNotFound:
                self.client.images.pull(image)

    def run(
        self,
        image: str,
        command: list[str],
        timeout: int = 60,
        mem_limit: str = "128m",
    ) -> ContainerResult:
        if image not in self.approved_images:
            raise ImageNotApproved(f"Image '{image}' is not approved")

        self._ensure_image(image)

        container = self.client.containers.create(
            image,
            command,
            mem_limit=mem_limit,
            memswap_limit=mem_limit,      # same value = no swap
            nano_cpus=1_000_000_000,      # 1 CPU
            pids_limit=128,
            network_mode="none",
        )
        try:
            timed_out = False
            try:
                container.start()
                container.wait(timeout=timeout)
            except (ReadTimeout, RequestsConnectionError):
                timed_out = True
                container.kill()
                container.wait()
            except APIError as e:
                # e.g. executable not found: container never ran properly
                return ContainerResult(127, "", str(e), False, False, container.id)

            container.reload()            # refresh State info from Docker
            state = container.attrs["State"]
            stdout = container.logs(stdout=True, stderr=False).decode(errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode(errors="replace")

            return ContainerResult(
                exit_code=state["ExitCode"],
                stdout=stdout,
                stderr=stderr,
                oom_killed=state.get("OOMKilled", False),
                timed_out=timed_out,
                container_id=container.id,
            )
        finally:
            container.remove(force=True)   # ALWAYS clean up
class DockerJobExecutor:
    """Adapter: lets the scheduler run jobs through DockerExecutor."""

    def __init__(self, docker_executor: DockerExecutor | None = None,
                 mem_limit: str = "128m") -> None:
        self.docker = docker_executor or DockerExecutor()
        self.mem_limit = mem_limit

    def run(self, job_id: str, job: Job) -> JobResult:
        try:
            r = self.docker.run(
                job.image, job.command,
                timeout=job.timeout, mem_limit=self.mem_limit,
            )
        except ImageNotApproved as e:
            return JobResult(False, stderr=str(e),
                             kind=FailureKind.STARTUP_ERROR, message=str(e))
        except (DockerException, RequestsConnectionError) as e:
            msg = f"Docker error: {e}"
            return JobResult(False, stderr=msg,
                             kind=FailureKind.STARTUP_ERROR, message=msg)

        # Order matters: a timeout kill also gives exit code 137
        if r.timed_out:
            kind = FailureKind.TIMEOUT
        elif r.oom_killed:
            kind = FailureKind.OOM
        elif r.exit_code != 0:
            kind = FailureKind.EXIT_CODE
        else:
            kind = FailureKind.NONE

        return JobResult(
            success=r.success,
            exit_code=r.exit_code,
            stdout=r.stdout,
            stderr=r.stderr,
            kind=kind,
            message=r.reason,
        )

if __name__ == "__main__":
    ex = DockerExecutor()
    r = ex.run("alpine:3.20", ["echo", "Hello from container"])
    print(r)