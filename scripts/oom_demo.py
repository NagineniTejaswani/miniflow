from miniflow.docker_executor import DockerExecutor

ex = DockerExecutor()
r = ex.run(
    "python:3.12-slim",
    ["python", "-c", "x = b'x' * (300 * 1024 * 1024); print('allocated')"],
    mem_limit="64m",
)
print("exit code :", r.exit_code)
print("oom_killed:", r.oom_killed)
print("stdout    :", repr(r.stdout))
print("stderr    :", repr(r.stderr))
print("reason    :", r.reason)