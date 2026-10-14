import unittest
from datetime import datetime
from unittest.mock import patch

from app.services import schedule_service


class Scrum226ScheduleServiceTests(unittest.TestCase):
    def setUp(self):
        self.session = {
            "id": "demo226-edit-1",
            "topic": "Python basics",
            "starts_at": datetime(2099, 4, 1, 9),
            "ends_at": datetime(2099, 4, 1, 10),
            "classroom_id": "demo226-room-1",
            "status": "scheduled",
        }
        self.notification = {"id": 7, "recipient_email": "student@scrum226-demo.invalid"}
        self.result = {
            "session": self.session,
            "change_id": 4,
            "notifications": [self.notification],
            "duplicate": False,
        }
        self.apply_patch = patch.object(schedule_service.schedule_repository, "apply_change", return_value=self.result)
        self.apply_patch.start()
        self.addCleanup(self.apply_patch.stop)
        self.status_patch = patch.object(
            schedule_service.schedule_repository,
            "get_notification_status",
            return_value=[{"status": "sent", "recipient_email": self.notification["recipient_email"]}],
        )
        self.status_patch.start()
        self.addCleanup(self.status_patch.stop)
        self.update_patch = patch.object(schedule_service.schedule_repository, "update_notification")
        self.mock_update = self.update_patch.start()
        self.addCleanup(self.update_patch.stop)

    @patch.object(schedule_service, "send_email")
    def test_edit_session_sends_notification_and_returns_saved_session(self, send_email):
        result = schedule_service.edit_session(
            "demo226-edit-1", "manager-1", {"topic": "Updated topic"}, "edit-1"
        )
        self.assertEqual(result["session"]["id"], "demo226-edit-1")
        schedule_service.schedule_repository.apply_change.assert_called_once()
        send_email.assert_called_once()
        self.mock_update.assert_called_once_with(7, "sent")

    @patch.object(schedule_service, "send_email")
    def test_reschedule_validates_and_applies_new_time(self, send_email):
        schedule_service.reschedule_session(
            "demo226-reschedule-1", "manager-1",
            {"starts_at": "2099-04-05T09:00:00", "ends_at": "2099-04-05T10:00:00"},
        )
        args = schedule_service.schedule_repository.apply_change.call_args.args
        self.assertEqual(args[2], "rescheduled")
        self.assertEqual(args[3]["starts_at"], datetime(2099, 4, 5, 9))
        send_email.assert_called_once()

    def test_reschedule_rejects_invalid_time_range_before_database_write(self):
        with self.assertRaises(schedule_service.ScheduleError) as caught:
            schedule_service.reschedule_session(
                "demo226-reschedule-1", "manager-1",
                {"starts_at": "2099-04-05T10:00:00", "ends_at": "2099-04-05T09:00:00"},
            )
        self.assertEqual(caught.exception.code, "INVALID_TIME_RANGE")
        schedule_service.schedule_repository.apply_change.assert_not_called()

    @patch.object(schedule_service, "send_email")
    def test_repository_collision_is_returned_as_conflict(self, send_email):
        schedule_service.schedule_repository.apply_change.return_value = {"conflict": "SCHEDULE_CONFLICT"}
        with self.assertRaises(schedule_service.ScheduleError) as caught:
            schedule_service.reschedule_session(
                "demo226-collision-target", "manager-1",
                {"starts_at": "2099-04-03T11:00:00", "ends_at": "2099-04-03T12:00:00"},
            )
        self.assertEqual(caught.exception.status_code, 409)
        send_email.assert_not_called()

    @patch.object(schedule_service, "send_email")
    def test_cancel_marks_one_session_and_stores_notification_failure(self, send_email):
        send_email.side_effect = RuntimeError("synthetic SMTP failure")
        self.result["session"]["id"] = "demo226-cancel-1"
        result = schedule_service.cancel_session(
            "demo226-cancel-1", "manager-1", {"reason": "Synthetic reason"}
        )
        args = schedule_service.schedule_repository.apply_change.call_args.args
        self.assertEqual(args[2], "cancelled")
        self.assertEqual(args[3]["cancellation_reason"], "Synthetic reason")
        self.mock_update.assert_called_once_with(7, "failed", "RuntimeError")
        self.assertEqual(result["session"]["id"], "demo226-cancel-1")

    def test_invalid_topic_and_idempotency_key_are_rejected(self):
        with self.assertRaises(schedule_service.ScheduleError):
            schedule_service.edit_session("x", "actor", {"topic": " "})
        with self.assertRaises(schedule_service.ScheduleError):
            schedule_service.cancel_session("x", "actor", {}, " " )
        schedule_service.schedule_repository.apply_change.assert_not_called()

    @patch.object(schedule_service, "send_email")
    def test_idempotent_replay_does_not_send_notification_again(self, send_email):
        self.result["duplicate"] = True
        self.result["notifications"] = []
        schedule_service.edit_session("demo226-edit-1", "manager-1", {"topic": "Updated"}, "edit-1")
        send_email.assert_not_called()
        self.mock_update.assert_not_called()

    @patch.object(schedule_service, "send_email")
    def test_idempotent_replay_retries_only_pending_notification(self, send_email):
        self.result["duplicate"] = True
        schedule_service.edit_session("demo226-edit-1", "manager-1", {"topic": "Updated"}, "edit-1")
        send_email.assert_called_once()
