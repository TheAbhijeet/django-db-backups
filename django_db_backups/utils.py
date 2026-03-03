import hashlib
from pathlib import Path

def calculate_sha256(file_path: Path) -> str:
    """Calculates the SHA256 hash of a file, reading it in chunks."""
    sha256_hash = hashlib.sha256()
    with file_path.open("rb") as f:
        # Read and update hash in chunks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()