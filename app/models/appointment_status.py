from enum import StrEnum


class AppointmentStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


APPOINTMENT_STATUS_VALUES = tuple(status.value for status in AppointmentStatus)

