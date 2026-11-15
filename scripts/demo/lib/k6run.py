"""Run a k6 script from loadtest/ inside the helper with secrets injected."""
import os, subprocess
import fg


def k6(script, **env):
    repo = os.environ["DEMO_REPO"]
    e = {**os.environ, "OPERATOR_PASSWORD": fg.demo_user("operator"), "SIMULATOR_TOKEN": fg.secret("simulator_token"),
         "RESULT_DIR": f"{repo}/loadtest/results", **{k: str(v) for k, v in env.items()}}
    r = subprocess.run(["k6", "run", "--quiet", f"{repo}/loadtest/{script}"], env=e, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()[-500:]
