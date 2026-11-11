"""Content-addressed storage for uploaded invoices in a local directory (a volume in Docker)."""

import os
import tempfile
from pathlib import Path, PurePosixPath


class FileStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, sha256: str, extension: str, content: bytes) -> str:
        """Store the content under its hash and return the path relative to the root.

        Saving the same content twice is harmless: the second write replaces identical bytes.
        """
        relative = PurePosixPath(sha256[:2]) / f"{sha256}.{extension}"
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temporary file and rename, so a crash never leaves a half-written invoice.
        fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".upload-")
        try:
            with os.fdopen(fd, "wb") as tmp:
                tmp.write(content)
            os.replace(tmp_name, target)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return str(relative)
