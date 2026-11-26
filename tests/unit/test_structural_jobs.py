"""Background structural worker lifecycle tests."""
import unittest
from unittest.mock import Mock

from simuo.structural.jobs import BackgroundJob


class BackgroundJobTests(unittest.TestCase):
    @staticmethod
    def job(connection):
        job = BackgroundJob()
        job.connection = connection
        job.process = Mock(pid=None)
        job.job_revision = job.revision
        return job

    def test_broken_pipe_finishes_job_and_reports_worker_exit(self):
        connection = Mock()
        connection.poll.side_effect = BrokenPipeError(109, "The pipe has been ended")
        job = self.job(connection)

        self.assertEqual(job.poll(), [("error", "Analysis worker exited unexpectedly")])
        self.assertFalse(job.running)
        connection.close.assert_called_once_with()

    def test_pipe_closure_after_result_does_not_replace_result_with_error(self):
        connection = Mock()
        connection.poll.side_effect = [True, BrokenPipeError(109, "The pipe has been ended")]
        connection.recv.return_value = ("result", "finished")
        job = self.job(connection)

        self.assertEqual(job.poll(), [("result", "finished")])
        self.assertFalse(job.running)
        connection.close.assert_called_once_with()

    def test_broken_pipe_from_stale_job_is_silently_discarded(self):
        connection = Mock()
        connection.poll.side_effect = BrokenPipeError(109, "The pipe has been ended")
        job = self.job(connection)
        job.revision += 1

        self.assertEqual(job.poll(), [])
        self.assertFalse(job.running)


if __name__ == "__main__":
    unittest.main()
