"""Shared Modal application resources without workflow-registration side effects."""

import modal

app = modal.App("extrapcap")
state_volume = modal.Volume.from_name("extrapcap-state", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("httpx>=0.27.0", "pandas>=2.2.0", "numpy>=1.26.0", "pydantic>=2.7.0", "requests>=2.31.0", "pytz>=2024.1")
    .add_local_dir("src/extrapcap", remote_path="/root/src/extrapcap", copy=True)
    .add_local_dir("modal_app", remote_path="/root/modal_app", copy=True)
    .add_local_file("pyproject.toml", remote_path="/root/pyproject.toml", copy=True)
    .run_commands("pip install -e /root")
    .env({"PYTHONPATH": "/root:/root/src", "ALPACA_PAPER": "true", "EXTRACAP_STATE_DIR": "/data"})
)
secrets = [modal.Secret.from_name(name) for name in ("alpaca-paper", "nebius", "cloudflare-api", "resend")]
state_mount = {"/data": state_volume}
