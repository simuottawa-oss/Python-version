"""Spawned, cancellable workers with revision-based stale-result rejection."""
import multiprocessing as mp


def _worker(connection, operation, arguments):
    try:
        def progress(message):
            connection.send(("progress", message))
        if operation == "prepare":
            from .geometry import load_geometry
            from .meshing import classify_patches
            geometry = load_geometry(arguments[0], arguments[1])
            progress("Reconstructing selectable surface patches")
            value = (geometry, classify_patches(geometry, arguments[2]))
        elif operation == "mesh":
            from .meshing import generate_mesh
            value = generate_mesh(*arguments, progress=progress)
        elif operation == "solve":
            from .solver import solve_analysis
            value = solve_analysis(*arguments, progress=progress)
        else:
            raise ValueError("Unknown analysis operation")
        connection.send(("result", value))
    except BaseException as error:
        connection.send(("error", f"{type(error).__name__}: {error}"))
    finally:
        connection.close()


class BackgroundJob:
    def __init__(self):
        self.process = None
        self.connection = None
        self.revision = 0
        self.job_revision = None
        self.operation = None

    def invalidate(self):
        self.revision += 1
        self.cancel()

    @property
    def running(self):
        return self.process is not None

    def start(self, operation, *arguments):
        self.cancel()
        context = mp.get_context("spawn")
        parent, child = context.Pipe(duplex=False)
        self.operation = operation
        self.job_revision = self.revision
        self.connection = parent
        self.process = context.Process(target=_worker, args=(child, operation, arguments), daemon=True)
        try:
            self.process.start()
        except BaseException:
            self.cancel()
            raise
        finally:
            child.close()

    def poll(self):
        if self.process is None:
            return []
        messages = []
        complete = False
        while self.connection.poll():
            try:
                kind, value = self.connection.recv()
            except EOFError:
                break
            if self.job_revision == self.revision:
                messages.append((kind, value))
            complete |= kind in ("result", "error")
        if complete:
            self.cancel()
        elif not self.process.is_alive():
            self.cancel()
            messages.append(("error", "Analysis worker exited unexpectedly"))
        return messages

    def cancel(self):
        process, connection = self.process, self.connection
        self.process = self.connection = None
        if process is not None and process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=1.)
            if process.is_alive():
                process.kill()
                process.join(timeout=1.)
            process.close()
        if connection is not None:
            connection.close()
