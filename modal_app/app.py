import modal

app = modal.App("extrapcap")

# Modal container image with extrapcap installed
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "httpx>=0.27.0",
        "pandas>=2.2.0",
        "numpy>=1.26.0",
        "pydantic>=2.7.0",
        "requests>=2.31.0",
        "pytz>=2024.1",
    )
    .add_local_dir("src/extrapcap", remote_path="/root/src/extrapcap")
    .add_local_file("pyproject.toml", remote_path="/root/pyproject.toml")
    .run_commands("pip install -e /root")
)

# Secrets required across Modal functions
secrets = [
    modal.Secret.from_name("alpaca-paper"),   # ALPACA_API_KEY, ALPACA_SECRET_KEY
    modal.Secret.from_name("nebius"),          # NEBIUS_API_KEY
    modal.Secret.from_name("cloudflare-api"),  # CF_APP_URL, CF_API_TOKEN
]

# Register functions
import modal_app.functions.data_refresh
import modal_app.functions.streak_screen
import modal_app.functions.opening_prep
import modal_app.functions.candidate_review
import modal_app.functions.position_management
import modal_app.functions.reconciliation
import modal_app.functions.daily_report
import modal_app.functions.improvement_loop
import modal_app.functions.live_cycle
