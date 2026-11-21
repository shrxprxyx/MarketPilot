import subprocess
import sys


def test_celery_app_registers_all_models() -> None:
    """The worker only imports app.jobs.*; without the model registry the Document -> tenants
    foreign key cannot resolve and ingestion fails. Run in a fresh interpreter so other
    tests' imports cannot mask it."""
    code = (
        "import app.jobs.celery_app\n"
        "from app.db.base import Base\n"
        "assert 'tenants' in Base.metadata.tables\n"
        "Base.metadata.sorted_tables\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
