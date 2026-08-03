from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.appointment_status import AppointmentStatus


class BarberShopCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=255)


class BarberShopRead(BarberShopCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    access_status: str
    plan: str
    suspended_at: datetime | None
    suspension_reason: str | None


class BarberShopSuspend(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class BotSettingsUpdate(BaseModel):
    bot_enabled: bool = True
    reminders_enabled: bool = True
    reminder_hours_before: int = Field(default=24, ge=1, le=168)
    greeting_message: str = Field(min_length=1)
    reminder_template: str = Field(min_length=1)


class BotWebhookRequest(BaseModel):
    from_phone: str = Field(min_length=1, max_length=30)
    to_business_number: str = Field(min_length=1, max_length=30)
    message: str = Field(min_length=1, max_length=1000)


class BotWebhookMessage(BaseModel):
    sender: str
    text: str


class BotWebhookResponse(BaseModel):
    barber_shop_id: int
    messages: list[BotWebhookMessage]


class ServiceCreate(BaseModel):
    barber_shop_id: int
    name: str = Field(min_length=1, max_length=120)
    duration_minutes: int = Field(gt=0, le=480)
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)


class ServiceRead(ServiceCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool


class BarberCreate(BaseModel):
    barber_shop_id: int
    name: str = Field(min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=255)
    service_ids: list[int] = Field(default_factory=list)


class BarberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    barber_shop_id: int
    name: str
    phone: str | None
    email: str | None
    is_active: bool


class CustomerCreate(BaseModel):
    barber_shop_id: int
    full_name: str = Field(min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class CustomerRead(CustomerCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class WorkingScheduleCreate(BaseModel):
    barber_id: int
    day_of_week: int = Field(ge=0, le=6)
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def validate_time_range(self) -> "WorkingScheduleCreate":
        if self.start_time >= self.end_time:
            raise ValueError("La hora de inicio debe ser anterior a la hora de fin.")
        return self


class WorkingScheduleRead(WorkingScheduleCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool


class AvailabilityQuery(BaseModel):
    barber_id: int
    service_id: int
    target_date: date


class AvailabilitySlot(BaseModel):
    starts_at: datetime
    ends_at: datetime


class AppointmentCreate(BaseModel):
    barber_id: int
    customer_id: int
    service_id: int
    starts_at: datetime
    duration_minutes: int | None = Field(default=None, gt=0, le=480)
    notes: str | None = None


class AppointmentReschedule(BaseModel):
    starts_at: datetime


class AppointmentPaymentUpdate(BaseModel):
    payment_method: str | None = Field(default=None, max_length=50)


class AppointmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    barber_shop_id: int
    barber_id: int
    customer_id: int
    service_id: int
    starts_at: datetime
    ends_at: datetime
    status: AppointmentStatus
    is_paid: bool
    paid_at: datetime | None
    payment_method: str | None
    notes: str | None


class SupplySaleCreate(BaseModel):
    barber_shop_id: int
    appointment_id: int | None = None
    name: str = Field(min_length=1, max_length=120)
    quantity: int = Field(gt=0, le=999)
    unit_price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)


class SupplySaleRead(SupplySaleCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    total_price: Decimal
