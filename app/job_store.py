from enum import Enum
from typing import Any, Dict


class JobStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    CONVERTING = "converting"
    SEPARATING = "separating"
    ENCODING = "encoding"
    DONE = "done"
    FAILED = "failed"


# In-memory job registry — adequate for single-user local tool.
# Keys: job_id (str UUID)
# Values: dict with keys: status, progress (0-100), message, output_path, error
jobs: Dict[str, Any] = {}
