from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum, Float, Boolean, Date, Time
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
    SUPERVISION = "supervision"
    ESCALATION = "escalation"
    MERGE_SUGGESTED = "merge_suggested"
    MERGE_CONFIRMED = "merge_confirmed"
    VISIT_SCHEDULED = "visit_scheduled"
    VISIT_COMPLETED = "visit_completed"
    VISIT_SKIPPED = "visit_skipped"
    DISPATCH_REASSIGNED = "dispatch_reassigned"
    DISPATCH_CANCELLED = "dispatch_cancelled"
    DISPATCH_RELEASED = "dispatch_released"
    DISPATCH_CONFIRMED = "dispatch_confirmed"


class MergeStatus(str, enum.Enum):
    SUGGESTED = "suggested"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class SupervisionStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class VisitStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class VisitResult(str, enum.Enum):
    SATISFIED = "satisfied"
    PARTIALLY_SATISFIED = "partially_satisfied"
    DISSATISFIED = "dissatisfied"
    NO_ANSWER = "no_answer"
    INACCESSIBLE = "inaccessible"


class StaffStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ON_LEAVE = "on_leave"


class DispatchStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REASSIGNED = "reassigned"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    RELEASED = "released"


class DispatchType(str, enum.Enum):
    AUTO = "auto"
    MANUAL = "manual"
    REASSIGN = "reassign"


class EvaluationTaskStatus(str, enum.Enum):
    PENDING = "pending"
    ELDERLY_SUBMITTED = "elderly_submitted"
    STAFF_SUBMITTED = "staff_submitted"
    REVIEWED = "reviewed"
    CLOSED = "closed"


class EvaluationSource(str, enum.Enum):
    ORDER_COMPLETION = "order_completion"
    VISIT_ARCHIVE = "visit_archive"
    MANUAL = "manual"


class FeedbackSubmitterType(str, enum.Enum):
    ELDERLY = "elderly"
    CONTACT = "contact"


class AbnormalType(str, enum.Enum):
    LOW_SATISFACTION = "low_satisfaction"
    NO_VISIT = "no_visit"
    REPEAT_LOW_SCORE = "repeat_low_score"
    STAFF_CONTINUOUS_ABNORMAL = "staff_continuous_abnormal"
    MULTIPLE_COMPLAINTS = "multiple_complaints"


class AbnormalStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    RESOLVED = "resolved"
    CLOSED = "closed"


class RectificationStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REVIEW_PASSED = "review_passed"
    REVIEW_REJECTED = "review_rejected"
    ARCHIVED = "archived"


class ReviewResult(str, enum.Enum):
    PASSED = "passed"
    REJECTED = "rejected"
    NEED_RECTIFICATION = "need_rectification"


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
    sla_deadline = Column(DateTime)
    sla_achieved = Column(Boolean, default=None)
    supervision_priority_score = Column(Float, default=0)
    supervision_risk_level = Column(Enum(RiskLevel))
    historical_incomplete_count = Column(Integer, default=0)
    is_master_order = Column(Boolean, default=False)
    master_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True)
    manually_escalated = Column(Boolean, default=False)
    escalation_reason = Column(Text)

    elderly = relationship("ElderlyProfile", back_populates="work_orders")
    progress_records = relationship("ProgressRecord", back_populates="work_order", cascade="all, delete-orphan", foreign_keys="ProgressRecord.work_order_id")
    supervision_records = relationship("SupervisionRecord", back_populates="work_order", cascade="all, delete-orphan")
    follow_up_plans = relationship("FollowUpPlan", back_populates="work_order", cascade="all, delete-orphan")
    visit_records = relationship("VisitRecord", back_populates="work_order", cascade="all, delete-orphan")
    merged_orders = relationship("WorkOrder", backref="master_order", remote_side=[id])


class ProgressRecord(Base):
    __tablename__ = "progress_records"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False, index=True)
    progress_type = Column(Enum(ProgressType), nullable=False)
    operator_name = Column(String(100))
    operator_role = Column(String(50))
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.now, index=True)

    work_order = relationship("WorkOrder", back_populates="progress_records", foreign_keys=[work_order_id])


class SLAConfig(Base):
    __tablename__ = "sla_configs"

    id = Column(Integer, primary_key=True, index=True)
    service_type = Column(Enum(ServiceType), unique=True, nullable=False, index=True)
    response_hours = Column(Float, nullable=False, default=2.0, comment="响应时限(小时)")
    resolution_hours = Column(Float, nullable=False, default=24.0, comment="解决时限(小时)")
    first_response_hours = Column(Float, default=1.0, comment="首次响应时限(小时)")
    description = Column(String(500))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class CommunityCalendar(Base):
    __tablename__ = "community_calendars"

    id = Column(Integer, primary_key=True, index=True)
    community = Column(String(100), unique=True, nullable=False, index=True)
    work_start_time = Column(Time, default="08:00:00")
    work_end_time = Column(Time, default="18:00:00")
    work_days = Column(String(20), default="1,2,3,4,5", comment="工作日(1-7对应周一到周日)")
    exclude_holidays = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class HolidayRecord(Base):
    __tablename__ = "holiday_records"

    id = Column(Integer, primary_key=True, index=True)
    community = Column(String(100), index=True)
    holiday_date = Column(Date, nullable=False, index=True)
    holiday_name = Column(String(100))
    is_workday = Column(Boolean, default=False, comment="是否为调休工作日")
    created_at = Column(DateTime, default=datetime.now)


class DuplicateSuggestion(Base):
    __tablename__ = "duplicate_suggestions"

    id = Column(Integer, primary_key=True, index=True)
    master_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False, index=True)
    slave_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False, index=True)
    elderly_id = Column(Integer, ForeignKey("elderly_profiles.id"), nullable=False, index=True)
    service_type = Column(Enum(ServiceType), nullable=False, index=True)
    time_window_days = Column(Integer, nullable=False, default=7)
    similarity_score = Column(Float, default=0.0)
    status = Column(Enum(MergeStatus), default=MergeStatus.SUGGESTED, index=True)
    suggested_by = Column(String(100), default="system")
    confirmed_by = Column(String(100))
    confirmed_at = Column(DateTime)
    reject_reason = Column(Text)
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    master_order = relationship("WorkOrder", foreign_keys=[master_order_id])
    slave_order = relationship("WorkOrder", foreign_keys=[slave_order_id])


class SupervisionRecord(Base):
    __tablename__ = "supervision_records"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False, index=True)
    supervisor_name = Column(String(100))
    supervisor_role = Column(String(50))
    assignee_name = Column(String(100))
    assignee_phone = Column(String(20))
    supervision_remark = Column(Text, nullable=False)
    next_follow_up_time = Column(DateTime, index=True)
    is_visited = Column(Boolean, default=False)
    no_follow_up_needed = Column(Boolean, default=False)
    no_follow_up_reason = Column(Text)
    risk_level_before = Column(Enum(RiskLevel))
    risk_level_after = Column(Enum(RiskLevel))
    status = Column(Enum(SupervisionStatus), default=SupervisionStatus.PENDING, index=True)
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    work_order = relationship("WorkOrder", back_populates="supervision_records")


class FollowUpPlan(Base):
    __tablename__ = "follow_up_plans"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False, index=True)
    plan_content = Column(Text, nullable=False)
    planned_time = Column(DateTime, nullable=False, index=True)
    responsible_person = Column(String(100))
    responsible_phone = Column(String(20))
    priority = Column(Integer, default=1, comment="优先级1-5，5最高")
    is_completed = Column(Boolean, default=False)
    completed_time = Column(DateTime)
    completed_remark = Column(Text)
    created_by = Column(String(100))
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    work_order = relationship("WorkOrder", back_populates="follow_up_plans")


class VisitRecord(Base):
    __tablename__ = "visit_records"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False, index=True)
    visit_time = Column(DateTime, nullable=False, index=True)
    visitor_name = Column(String(100))
    visitor_role = Column(String(50))
    visit_status = Column(Enum(VisitStatus), default=VisitStatus.SCHEDULED)
    visit_result = Column(Enum(VisitResult))
    elderly_present = Column(Boolean, default=True)
    visit_content = Column(Text)
    satisfaction_score = Column(Integer, comment="满意度1-5分")
    feedback = Column(Text)
    next_visit_suggestion = Column(Text)
    archived = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    work_order = relationship("WorkOrder", back_populates="visit_records")


class ServiceStaff(Base):
    __tablename__ = "service_staff"

    id = Column(Integer, primary_key=True, index=True)
    staff_no = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False, index=True)
    id_card = Column(String(18), unique=True, index=True)
    gender = Column(Enum(ElderlyGender), default=ElderlyGender.OTHER)
    age = Column(Integer)
    phone = Column(String(20))
    email = Column(String(100))
    address = Column(String(500))
    status = Column(Enum(StaffStatus), default=StaffStatus.ACTIVE, index=True)
    position = Column(String(100), comment="职位")
    department = Column(String(100), comment="所属部门")
    daily_capacity = Column(Integer, default=8, comment="日服务容量（单/天）")
    weekly_capacity = Column(Integer, default=40, comment="周服务容量（单/周）")
    monthly_capacity = Column(Integer, default=160, comment="月服务容量（单/月）")
    hire_date = Column(Date)
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    skills = relationship("StaffSkill", back_populates="staff", cascade="all, delete-orphan")
    communities = relationship("StaffCommunity", back_populates="staff", cascade="all, delete-orphan")
    schedules = relationship("StaffSchedule", back_populates="staff", cascade="all, delete-orphan")
    dispatch_records = relationship("DispatchRecord", back_populates="staff", foreign_keys="DispatchRecord.staff_id")


class StaffSkill(Base):
    __tablename__ = "staff_skills"

    id = Column(Integer, primary_key=True, index=True)
    staff_id = Column(Integer, ForeignKey("service_staff.id"), nullable=False, index=True)
    skill_tag = Column(String(100), nullable=False, index=True, comment="技能标签，对应服务类型")
    proficiency = Column(Integer, default=3, comment="熟练度 1-5")
    is_certified = Column(Boolean, default=False, comment="是否持证")
    cert_no = Column(String(100), comment="证书编号")
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    staff = relationship("ServiceStaff", back_populates="skills")


class StaffCommunity(Base):
    __tablename__ = "staff_communities"

    id = Column(Integer, primary_key=True, index=True)
    staff_id = Column(Integer, ForeignKey("service_staff.id"), nullable=False, index=True)
    community = Column(String(100), nullable=False, index=True, comment="可服务社区")
    is_primary = Column(Boolean, default=False, comment="是否主负责社区")
    priority = Column(Integer, default=1, comment="优先级 1-5，1最高")
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    staff = relationship("ServiceStaff", back_populates="communities")


class StaffSchedule(Base):
    __tablename__ = "staff_schedules"

    id = Column(Integer, primary_key=True, index=True)
    staff_id = Column(Integer, ForeignKey("service_staff.id"), nullable=False, index=True)
    schedule_date = Column(Date, nullable=False, index=True, comment="排班日期")
    shift_type = Column(String(50), default="day", comment="班次类型：早班/中班/晚班/全天")
    start_time = Column(Time, nullable=False, comment="开始时间")
    end_time = Column(Time, nullable=False, comment="结束时间")
    is_available = Column(Boolean, default=True, comment="是否可派单")
    capacity = Column(Integer, default=8, comment="当日可接单数")
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    staff = relationship("ServiceStaff", back_populates="schedules")

    __table_args__ = (
        {'sqlite_autoincrement': True},
    )


class DispatchRecord(Base):
    __tablename__ = "dispatch_records"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False, index=True)
    staff_id = Column(Integer, ForeignKey("service_staff.id"), nullable=False, index=True)
    dispatch_type = Column(Enum(DispatchType), default=DispatchType.MANUAL, comment="派单类型")
    dispatch_status = Column(Enum(DispatchStatus), default=DispatchStatus.PENDING, index=True)
    match_score = Column(Float, default=0, comment="匹配度分数")
    original_staff_id = Column(Integer, ForeignKey("service_staff.id"), nullable=True, comment="原接单人员ID（改派时）")
    reassign_reason = Column(Text, comment="改派原因")
    reassign_operator = Column(String(100), comment="改派操作人")
    reassign_time = Column(DateTime, comment="改派时间")
    cancel_reason = Column(Text, comment="取消原因")
    cancel_operator = Column(String(100), comment="取消操作人")
    cancel_time = Column(DateTime, comment="取消时间")
    release_reason = Column(Text, comment="释放原因")
    release_operator = Column(String(100), comment="释放操作人")
    release_time = Column(DateTime, comment="释放时间")
    confirm_operator = Column(String(100), comment="确认操作人")
    confirm_time = Column(DateTime, comment="确认时间")
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    staff = relationship("ServiceStaff", back_populates="dispatch_records", foreign_keys=[staff_id])
    original_staff = relationship("ServiceStaff", foreign_keys=[original_staff_id])
    work_order = relationship("WorkOrder", foreign_keys=[work_order_id])


class LowScoreReason(Base):
    __tablename__ = "low_score_reasons"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True, nullable=False, comment="原因编码")
    name = Column(String(200), nullable=False, comment="原因名称")
    category = Column(String(100), index=True, comment="分类")
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class AbnormalTag(Base):
    __tablename__ = "abnormal_tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True, nullable=False, comment="标签名称")
    code = Column(String(50), unique=True, index=True, nullable=False, comment="标签编码")
    abnormal_type = Column(Enum(AbnormalType), index=True, comment="异常类型")
    risk_level = Column(Enum(RiskLevel), default=RiskLevel.MEDIUM, comment="风险等级")
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class EvaluationTemplate(Base):
    __tablename__ = "evaluation_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, comment="模板名称")
    service_type = Column(Enum(ServiceType), nullable=False, index=True, comment="适用服务类型")
    description = Column(Text)
    is_active = Column(Boolean, default=True, index=True)
    is_default = Column(Boolean, default=False, comment="是否默认模板")
    created_by = Column(String(100))
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    indicators = relationship("EvaluationIndicator", back_populates="template", cascade="all, delete-orphan")
    evaluation_tasks = relationship("EvaluationTask", back_populates="template")


class EvaluationIndicator(Base):
    __tablename__ = "evaluation_indicators"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("evaluation_templates.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False, comment="指标名称")
    code = Column(String(50), index=True, comment="指标编码")
    description = Column(Text)
    weight = Column(Float, default=1.0, comment="权重")
    sort_order = Column(Integer, default=0, comment="排序")
    max_score = Column(Float, default=5.0, comment="满分")
    is_required = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    template = relationship("EvaluationTemplate", back_populates="indicators")


class EvaluationTask(Base):
    __tablename__ = "evaluation_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_no = Column(String(50), unique=True, index=True, nullable=False, comment="任务编号")
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False, index=True)
    elderly_id = Column(Integer, ForeignKey("elderly_profiles.id"), nullable=False, index=True)
    template_id = Column(Integer, ForeignKey("evaluation_templates.id"), nullable=False)
    supervision_record_id = Column(Integer, ForeignKey("supervision_records.id"), index=True)
    source = Column(Enum(EvaluationSource), default=EvaluationSource.ORDER_COMPLETION, index=True)
    status = Column(Enum(EvaluationTaskStatus), default=EvaluationTaskStatus.PENDING, index=True)
    assignee_name = Column(String(100), index=True)
    assignee_phone = Column(String(20))
    expire_time = Column(DateTime, index=True)
    overall_score = Column(Float, comment="综合评分")
    staff_self_score = Column(Float, comment="服务人员自评分")
    reviewer_name = Column(String(100))
    review_time = Column(DateTime)
    review_remark = Column(Text)
    is_abnormal = Column(Boolean, default=False, index=True)
    abnormal_reason = Column(Text)
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    template = relationship("EvaluationTemplate", back_populates="evaluation_tasks")
    work_order = relationship("WorkOrder")
    elderly = relationship("ElderlyProfile")
    supervision_record = relationship("SupervisionRecord")
    feedbacks = relationship("SatisfactionFeedback", back_populates="evaluation_task", cascade="all, delete-orphan")
    indicator_scores = relationship("IndicatorScore", back_populates="evaluation_task", cascade="all, delete-orphan")
    self_evaluation = relationship("StaffSelfEvaluation", back_populates="evaluation_task", uselist=False, cascade="all, delete-orphan")
    reviews = relationship("StaffReview", back_populates="evaluation_task", cascade="all, delete-orphan")
    abnormal_warnings = relationship("AbnormalWarning", back_populates="evaluation_task", cascade="all, delete-orphan")
    rectification_tasks = relationship("RectificationTask", back_populates="evaluation_task", cascade="all, delete-orphan")


class IndicatorScore(Base):
    __tablename__ = "indicator_scores"

    id = Column(Integer, primary_key=True, index=True)
    evaluation_task_id = Column(Integer, ForeignKey("evaluation_tasks.id"), nullable=False, index=True)
    indicator_id = Column(Integer, ForeignKey("evaluation_indicators.id"), nullable=False, index=True)
    indicator_name = Column(String(200), nullable=False)
    score = Column(Float, nullable=False, comment="得分")
    max_score = Column(Float, default=5.0)
    weight = Column(Float, default=1.0)
    weighted_score = Column(Float, comment="加权得分")
    created_at = Column(DateTime, default=datetime.now)

    evaluation_task = relationship("EvaluationTask", back_populates="indicator_scores")


class SatisfactionFeedback(Base):
    __tablename__ = "satisfaction_feedbacks"

    id = Column(Integer, primary_key=True, index=True)
    evaluation_task_id = Column(Integer, ForeignKey("evaluation_tasks.id"), nullable=False, index=True)
    submitter_type = Column(Enum(FeedbackSubmitterType), nullable=False, comment="提交人类型")
    submitter_name = Column(String(100), comment="提交人姓名")
    submitter_phone = Column(String(20), comment="提交人电话")
    submitter_relation = Column(String(50), comment="与老人关系")
    overall_score = Column(Float, nullable=False, comment="总体满意度评分")
    feedback_text = Column(Text, comment="文字反馈")
    complaint_content = Column(Text, comment="投诉内容")
    is_complaint = Column(Boolean, default=False, index=True)
    low_score_reason_id = Column(Integer, ForeignKey("low_score_reasons.id"), index=True)
    low_score_reason_detail = Column(String(500), comment="低分原因详情")
    submit_time = Column(DateTime, default=datetime.now, index=True)
    created_at = Column(DateTime, default=datetime.now)

    evaluation_task = relationship("EvaluationTask", back_populates="feedbacks")
    low_score_reason = relationship("LowScoreReason")


class StaffSelfEvaluation(Base):
    __tablename__ = "staff_self_evaluations"

    id = Column(Integer, primary_key=True, index=True)
    evaluation_task_id = Column(Integer, ForeignKey("evaluation_tasks.id"), nullable=False, index=True, unique=True)
    staff_name = Column(String(100), nullable=False, index=True)
    staff_phone = Column(String(20))
    self_score = Column(Float, nullable=False, comment="自评分")
    service_description = Column(Text, comment="服务说明")
    difficulty_description = Column(Text, comment="服务难点说明")
    improvement_suggestion = Column(Text, comment="改进建议")
    submit_time = Column(DateTime, default=datetime.now, index=True)
    created_at = Column(DateTime, default=datetime.now)

    evaluation_task = relationship("EvaluationTask", back_populates="self_evaluation")


class StaffReview(Base):
    __tablename__ = "staff_reviews"

    id = Column(Integer, primary_key=True, index=True)
    evaluation_task_id = Column(Integer, ForeignKey("evaluation_tasks.id"), nullable=False, index=True)
    reviewer_name = Column(String(100), nullable=False)
    reviewer_role = Column(String(50))
    review_result = Column(Enum(ReviewResult), nullable=False, index=True)
    review_score = Column(Float, comment="复核评分")
    review_remark = Column(Text)
    need_rectification = Column(Boolean, default=False, index=True)
    rectification_requirement = Column(Text, comment="整改要求")
    review_time = Column(DateTime, default=datetime.now, index=True)
    created_at = Column(DateTime, default=datetime.now)

    evaluation_task = relationship("EvaluationTask", back_populates="reviews")


class AbnormalWarning(Base):
    __tablename__ = "abnormal_warnings"

    id = Column(Integer, primary_key=True, index=True)
    warning_no = Column(String(50), unique=True, index=True, nullable=False)
    abnormal_type = Column(Enum(AbnormalType), nullable=False, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), index=True)
    elderly_id = Column(Integer, ForeignKey("elderly_profiles.id"), nullable=False, index=True)
    evaluation_task_id = Column(Integer, ForeignKey("evaluation_tasks.id"), index=True)
    staff_name = Column(String(100), index=True)
    tag_id = Column(Integer, ForeignKey("abnormal_tags.id"), index=True)
    tag_name = Column(String(100))
    risk_level = Column(Enum(RiskLevel), default=RiskLevel.MEDIUM, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    status = Column(Enum(AbnormalStatus), default=AbnormalStatus.PENDING, index=True)
    triggered_by = Column(String(100), default="system")
    trigger_time = Column(DateTime, default=datetime.now, index=True)
    handler_name = Column(String(100))
    handle_time = Column(DateTime)
    handle_remark = Column(Text)
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    work_order = relationship("WorkOrder")
    elderly = relationship("ElderlyProfile")
    evaluation_task = relationship("EvaluationTask", back_populates="abnormal_warnings")
    tag = relationship("AbnormalTag")
    rectification_tasks = relationship("RectificationTask", back_populates="abnormal_warning")


class RectificationTask(Base):
    __tablename__ = "rectification_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_no = Column(String(50), unique=True, index=True, nullable=False)
    abnormal_warning_id = Column(Integer, ForeignKey("abnormal_warnings.id"), index=True)
    evaluation_task_id = Column(Integer, ForeignKey("evaluation_tasks.id"), index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), index=True)
    elderly_id = Column(Integer, ForeignKey("elderly_profiles.id"), index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    responsible_person = Column(String(100), nullable=False, index=True)
    responsible_phone = Column(String(20))
    deadline = Column(DateTime, nullable=False, index=True)
    status = Column(Enum(RectificationStatus), default=RectificationStatus.PENDING, index=True)
    handle_description = Column(Text, comment="处理说明")
    handle_evidence = Column(Text, comment="处理凭证")
    completion_time = Column(DateTime)
    reviewer_name = Column(String(100))
    review_remark = Column(Text)
    review_time = Column(DateTime)
    archive_time = Column(DateTime)
    is_overdue = Column(Boolean, default=False, index=True)
    created_by = Column(String(100))
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    abnormal_warning = relationship("AbnormalWarning", back_populates="rectification_tasks")
    evaluation_task = relationship("EvaluationTask", back_populates="rectification_tasks")
    work_order = relationship("WorkOrder")
    elderly = relationship("ElderlyProfile")
