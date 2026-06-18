from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum
from datetime import datetime

Base = declarative_base()


class ElderlyGender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    CLOSED = "closed"


class ServiceType(str, enum.Enum):
    HOME_CARE = "home_care"
    MEAL_DELIVERY = "meal_delivery"
    MEDICAL_ASSIST = "medical_assist"
    CLEANING = "cleaning"
    SHOPPING = "shopping"
    COMPANIONSHIP = "companionship"
    REHABILITATION = "rehabilitation"
    PSYCHOLOGICAL = "psychological"
    OTHER = "other"


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ProgressType(str, enum.Enum):
    CREATED = "created"
    ASSIGNED = "assigned"
    ARRIVED = "arrived"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    FOLLOW_UP = "follow_up"
    CLOSED = "closed"


class ElderlyProfile(Base):
    __tablename__ = "elderly_profiles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    id_card = Column(String(18), unique=True, index=True)
    gender = Column(Enum(ElderlyGender), default=ElderlyGender.OTHER)
    age = Column(Integer)
    phone = Column(String(20))
    address = Column(String(500))
    community = Column(String(100), index=True)
    health_condition = Column(Text)
    living_situation = Column(String(200))
    risk_level = Column(Enum(RiskLevel), default=RiskLevel.LOW)
    special_needs = Column(Text)
    emergency_contact_name = Column(String(100))
    emergency_contact_phone = Column(String(20))
    emergency_contact_relation = Column(String(50))
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    remark = Column(Text)

    work_orders = relationship("WorkOrder", back_populates="elderly", cascade="all, delete-orphan")


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id = Column(Integer, primary_key=True, index=True)
    order_no = Column(String(50), unique=True, index=True, nullable=False)
    elderly_id = Column(Integer, ForeignKey("elderly_profiles.id"), nullable=False, index=True)
    service_type = Column(Enum(ServiceType), nullable=False, index=True)
    appointment_start = Column(DateTime, nullable=False)
    appointment_end = Column(DateTime, nullable=False)
    risk_remark = Column(Text)
    contact_name = Column(String(100))
    contact_phone = Column(String(20))
    contact_relation = Column(String(50))
    assignee_name = Column(String(100))
    assignee_phone = Column(String(20))
    arrival_time = Column(DateTime)
    completion_time = Column(DateTime)
    handle_summary = Column(Text)
    incomplete_reason = Column(Text)
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING, index=True)
    is_timeout = Column(Integer, default=0, index=True)
    timeout_hours = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    closed_at = Column(DateTime)
    follow_up_suggestion = Column(Text)

    elderly = relationship("ElderlyProfile", back_populates="work_orders")
    progress_records = relationship("ProgressRecord", back_populates="work_order", cascade="all, delete-orphan")


class ProgressRecord(Base):
    __tablename__ = "progress_records"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False, index=True)
    progress_type = Column(Enum(ProgressType), nullable=False)
    operator_name = Column(String(100))
    operator_role = Column(String(50))
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.now, index=True)

    work_order = relationship("WorkOrder", back_populates="progress_records")
