"""Manage unsaved OBJ imports without modifying their source files."""

from pathlib import Path
import os
import tempfile


def atomic_write(path, contents):
    """Write bytes to a sibling staging file, flush them, and atomically replace the
    destination. Clean up staging on failure; the parent directory must exist.

    Args:
        path (str or Path): Source or destination file path used by this operation.
        contents (bytes): Complete payload to write before replacing the destination.

    Returns:
        None. Replaces one file; filesystem errors propagate.
    """
    path = Path(path)
    staging = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
            staging = Path(stream.name)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, path)
    finally:
        # Windows cannot delete an open staging file. Leave the context before
        # cleanup on both write failures and replacement failures.
        if staging is not None:
            staging.unlink(missing_ok=True)


class TemporaryParts:
    def __init__(self):
        """Initialize an empty temporary-part registry without allocating a directory yet.

        Returns:
            None.
        """
        self._directory = None
        self.sources = {}

    @property
    def directory(self):
        """Expose the allocated temporary directory, if any.

        Returns:
            pathlib.Path or None: Directory path, or None before allocation or after
            cleanup.
        """
        # Match the resolved keys used by contains() and release(), even when
        # the system temp path uses an alias or a Windows short name.
        return Path(self._directory.name).resolve() if self._directory else None

    def create(self, source):
        """Copy source bytes into a uniquely named temporary .simuOPart and register its
        origin. Does not validate or convert the copied geometry.

        Args:
            source (str or Path): Original OBJ file whose bytes are copied without
                conversion or validation.

        Returns:
            pathlib.Path: Temporary copy; filesystem errors propagate.
        """
        source = Path(source).resolve()
        # Snapshot the OBJ so moving/deleting the original cannot break the
        # imported part. The caller validates it before adding it to the scene.
        contents = source.read_bytes()
        if self._directory is None:
            self._directory = tempfile.TemporaryDirectory(prefix="simuo-parts-")
        name, number = source.stem, 1
        destination = self.directory / f"{name}.simuOPart"
        while destination.exists():
            number += 1
            destination = self.directory / f"{name}-{number}.simuOPart"
        destination.write_bytes(contents)
        self.sources[destination] = source
        return destination

    def contains(self, path):
        """Check whether a resolved path is registered as a temporary part.

        Args:
            path (str or Path, optional): Candidate temporary copy; None returns False.

        Returns:
            bool: True for a managed copy; False for None or an unregistered path.
        """
        return path is not None and Path(path).resolve() in self.sources

    def release(self, path):
        """Delete and unregister a managed copy, leaving its source untouched.

        Args:
            path (str or Path): Managed temporary copy to delete and unregister.

        Returns:
            None. Unregistered paths are ignored; filesystem errors propagate.
        """
        path = Path(path).resolve()
        if path in self.sources:
            path.unlink(missing_ok=True)
            del self.sources[path]

    def cleanup(self):
        """Remove the temporary directory and clear all registered copies.

        Returns:
            None. Resets directory ownership and the source mapping.
        """
        if self._directory:
            self._directory.cleanup()
        self._directory = None
        self.sources.clear()
