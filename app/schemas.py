from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date, time
from app.models import (
    ElderlyGender, OrderStatus, ServiceType, RiskLevel, ProgressType,
    MergeStatus, SupervisionStatus, VisitStatus, VisitResult,
    EvaluationTaskStatus, EvaluationSource, FeedbackSubmitterType,
    AbnormalType, AbnormalStatus, RectificationStatus, ReviewResult
)


class ElderlyProfileBase(BaseModel):
    name: str = Field(..., max_length=100, description="老人姓名")
    id_card: Optional[str] = Field(None, max_length=18, description="身份证号")
    gender: Optional[ElderlyGender] = Field(None, description="性别")
    age: Optional[int] = Field(None, ge=0, le=150, description="年龄")
    phone: Optional[str] = Field(None, max_length=20, description="联系电话")
    address: Optional[str] = Field(None, max_length=500, description="住址")
    community: Optional[str] = Field(None, max_length=100, description="所属社区")
    health_condition: Optional[str] = Field(None, description="健康状况")
    living_situation: Optional[str] = Field(None, max_length=200, description="居住情况")
    risk_level: Optional[RiskLevel] = Field(None, description="风险等级")
    special_needs: Optional[str] = Field(None, description="特殊需求")
    emergency_contact_name: Optional[str] = Field(None, max_length=100, description="紧急联系人姓名")
    emergency_contact_phone: Optional[str] = Field(None, max_length=20, description="紧急联系人电话")
    emergency_contact_relation: Optional[str] = Field(None, max_length=50, description="紧急联系人关系")
    remark: Optional[str] = Field(None, description="备注")


class ElderlyProfileCreate(ElderlyProfileBase):
    pass


class ElderlyProfileUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    id_card: Optional[str] = Field(None, max_length=18)
    gender: Optional[ElderlyGender] = None
    age: Optional[int] = Field(None, ge=0, le=150)
    phone: Optional[str] = Field(None, max_length=20)
    address: Optional[str] = Field(None, max_length=500)
    community: Optional[str] = Field(None, max_length=100)
    health_condition: Optional[str] = None
    living_situation: Optional[str] = Field(None, max_length=200)
    risk_level: Optional[RiskLevel] = None
    special_needs: Optional[str] = None
    emergency_contact_name: Optional[str] = Field(None, max_length=100)
    emergency_contact_phone: Optional[str] = Field(None, max_length=20)
    emergency_contact_relation: Optional[str] = Field(None, max_length=50)
    remark: Optional[str] = None


class ElderlyProfileResponse(ElderlyProfileBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ElderlyProfileListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[ElderlyProfileResponse]


class WorkOrderBase(BaseModel):
    service_type: ServiceType = Field(..., description="服务类型")
    appointment_start: datetime = Field(..., description="预约开始时间")
    appointment_end: datetime = Field(..., description="预约结束时间")
    risk_remark: Optional[str] = Field(None, description="风险备注")
    contact_name: Optional[str] = Field(None, max_length=100, description="联系人姓名")
    contact_phone: Optional[str] = Field(None, max_length=20, description="联系人电话")
    contact_relation: Optional[str] = Field(None, max_length=50, description="联系人关系")


class WorkOrderCreate(WorkOrderBase):
    elderly_id: int = Field(..., description="老人档案ID")


class WorkOrderAssign(BaseModel):
    assignee_name: str = Field(..., max_length=100, description="接单人员姓名")
    assignee_phone: Optional[str] = Field(None, max_length=20, description="接单人员电话")


class WorkOrderArrive(BaseModel):
    arrival_time: datetime = Field(..., description="到达时间")


class WorkOrderComplete(BaseModel):
    handle_summary: str = Field(..., description="处理摘要")
    completion_time: Optional[datetime] = Field(None, description="完成时间")


class WorkOrderIncomplete(BaseModel):
    incomplete_reason: str = Field(..., description="未完成原因")
    handle_summary: Optional[str] = Field(None, description="处理摘要")
    completion_time: Optional[datetime] = Field(None, description="处理结束时间")


class WorkOrderUpdate(BaseModel):
    service_type: Optional[ServiceType] = None
    appointment_start: Optional[datetime] = None
    appointment_end: Optional[datetime] = None
    risk_remark: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_relation: Optional[str] = None
    status: Optional[OrderStatus] = None


class WorkOrderResponse(BaseModel):
    id: int
    order_no: str
    elderly_id: int
    elderly_name: Optional[str] = None
    service_type: ServiceType
    appointment_start: datetime
    appointment_end: datetime
    risk_remark: Optional[str]
    contact_name: Optional[str]
    contact_phone: Optional[str]
    contact_relation: Optional[str]
    assignee_name: Optional[str]
    assignee_phone: Optional[str]
    arrival_time: Optional[datetime]
    completion_time: Optional[datetime]
    handle_summary: Optional[str]
    incomplete_reason: Optional[str]
    status: OrderStatus
    is_timeout: int
    timeout_hours: float
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime]
    follow_up_suggestion: Optional[str]
    sla_deadline: Optional[datetime]
    sla_achieved: Optional[bool]
    supervision_priority_score: Optional[float]
    supervision_risk_level: Optional[RiskLevel]
    historical_incomplete_count: Optional[int]
    is_master_order: Optional[bool]
    master_order_id: Optional[int]
    manually_escalated: Optional[bool]
    escalation_reason: Optional[str]

    class Config:
        from_attributes = True


class WorkOrderListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[WorkOrderResponse]


class ProgressRecordBase(BaseModel):
    progress_type: ProgressType
    operator_name: Optional[str] = Field(None, max_length=100)
    operator_role: Optional[str] = Field(None, max_length=50)
    remark: Optional[str] = None


class ProgressRecordCreate(ProgressRecordBase):
    work_order_id: int


class ProgressRecordResponse(ProgressRecordBase):
    id: int
    work_order_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class ElderlyServiceAggregation(BaseModel):
    elderly_id: int
    elderly_name: str
    total_orders: int
    completed_orders: int
    pending_orders: int
    recent_orders: List[WorkOrderResponse]
    duplicate_requests: List[dict]
    follow_up_suggestion: str
    risk_level: Optional[RiskLevel]


class TimeoutOrderItem(BaseModel):
    id: int
    order_no: str
    elderly_id: int
    elderly_name: str
    service_type: ServiceType
    appointment_end: datetime
    status: OrderStatus
    timeout_hours: float
    assignee_name: Optional[str]


class TimeoutOrderListResponse(BaseModel):
    total: int
    items: List[TimeoutOrderItem]


class ServiceTypeStats(BaseModel):
    service_type: ServiceType
    total_orders: int
    completed_orders: int
    avg_completion_hours: float
    completion_rate: float


class StatisticsResponse(BaseModel):
    total_orders: int
    completed_orders: int
    pending_orders: int
    timeout_orders: int
    completion_rate: float
    service_type_stats: List[ServiceTypeStats]
    duplicate_request_rate: float
    timeout_distribution: List[dict]
    high_frequency_elderly: List[dict]


class SLAConfigBase(BaseModel):
    service_type: ServiceType
    response_hours: float = Field(2.0, gt=0, description="响应时限(小时)")
    resolution_hours: float = Field(24.0, gt=0, description="解决时限(小时)")
    first_response_hours: Optional[float] = Field(1.0, gt=0, description="首次响应时限(小时)")
    description: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = True


class SLAConfigCreate(SLAConfigBase):
    pass


class SLAConfigUpdate(BaseModel):
    response_hours: Optional[float] = Field(None, gt=0)
    resolution_hours: Optional[float] = Field(None, gt=0)
    first_response_hours: Optional[float] = Field(None, gt=0)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class SLAConfigResponse(SLAConfigBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CommunityCalendarBase(BaseModel):
    community: str = Field(..., max_length=100)
    work_start_time: Optional[time] = "08:00:00"
    work_end_time: Optional[time] = "18:00:00"
    work_days: Optional[str] = Field("1,2,3,4,5", max_length=20)
    exclude_holidays: Optional[bool] = True


class CommunityCalendarCreate(CommunityCalendarBase):
    pass


class CommunityCalendarUpdate(BaseModel):
    work_start_time: Optional[time] = None
    work_end_time: Optional[time] = None
    work_days: Optional[str] = None
    exclude_holidays: Optional[bool] = None


class CommunityCalendarResponse(CommunityCalendarBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class HolidayRecordBase(BaseModel):
    community: Optional[str] = Field(None, max_length=100)
    holiday_date: date
    holiday_name: Optional[str] = Field(None, max_length=100)
    is_workday: Optional[bool] = False


class HolidayRecordCreate(HolidayRecordBase):
    pass


class HolidayRecordUpdate(BaseModel):
    holiday_name: Optional[str] = None
    is_workday: Optional[bool] = None


class HolidayRecordResponse(HolidayRecordBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class DuplicateSuggestionBase(BaseModel):
    master_order_id: int
    slave_order_id: int
    time_window_days: int = Field(7, ge=1, le=365)


class DuplicateSuggestionConfirm(BaseModel):
    confirmed_by: Optional[str] = Field(None, max_length=100)


class DuplicateSuggestionReject(BaseModel):
    reject_reason: str = Field(..., description="拒绝原因")


class DuplicateSuggestionResponse(BaseModel):
    id: int
    master_order_id: int
    slave_order_id: int
    elderly_id: int
    elderly_name: Optional[str] = None
    service_type: ServiceType
    time_window_days: int
    similarity_score: float
    status: MergeStatus
    suggested_by: Optional[str]
    confirmed_by: Optional[str]
    confirmed_at: Optional[datetime]
    reject_reason: Optional[str]
    created_at: datetime
    updated_at: datetime
    master_order_no: Optional[str] = None
    slave_order_no: Optional[str] = None

    class Config:
        from_attributes = True


class SupervisionRecordBase(BaseModel):
    work_order_id: int
    supervisor_name: Optional[str] = Field(None, max_length=100)
    supervisor_role: Optional[str] = Field(None, max_length=50)
    assignee_name: Optional[str] = Field(None, max_length=100)
    assignee_phone: Optional[str] = Field(None, max_length=20)
    supervision_remark: str = Field(..., description="督办备注")
    next_follow_up_time: Optional[datetime] = None
    is_visited: Optional[bool] = False
    no_follow_up_needed: Optional[bool] = False
    no_follow_up_reason: Optional[str] = None
    risk_level_before: Optional[RiskLevel] = None
    risk_level_after: Optional[RiskLevel] = None
    status: Optional[SupervisionStatus] = SupervisionStatus.PENDING


class SupervisionRecordCreate(SupervisionRecordBase):
    pass


class SupervisionRecordUpdate(BaseModel):
    supervisor_name: Optional[str] = None
    supervisor_role: Optional[str] = None
    assignee_name: Optional[str] = None
    assignee_phone: Optional[str] = None
    supervision_remark: Optional[str] = None
    next_follow_up_time: Optional[datetime] = None
    is_visited: Optional[bool] = None
    no_follow_up_needed: Optional[bool] = None
    no_follow_up_reason: Optional[str] = None
    risk_level_before: Optional[RiskLevel] = None
    risk_level_after: Optional[RiskLevel] = None
    status: Optional[SupervisionStatus] = None


class SupervisionRecordResponse(SupervisionRecordBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FollowUpPlanBase(BaseModel):
    work_order_id: int
    plan_content: str = Field(..., description="计划内容")
    planned_time: datetime
    responsible_person: Optional[str] = Field(None, max_length=100)
    responsible_phone: Optional[str] = Field(None, max_length=20)
    priority: Optional[int] = Field(1, ge=1, le=5)
    created_by: Optional[str] = Field(None, max_length=100)


class FollowUpPlanCreate(FollowUpPlanBase):
    pass


class FollowUpPlanUpdate(BaseModel):
    plan_content: Optional[str] = None
    planned_time: Optional[datetime] = None
    responsible_person: Optional[str] = None
    responsible_phone: Optional[str] = None
    priority: Optional[int] = Field(None, ge=1, le=5)
    is_completed: Optional[bool] = None
    completed_time: Optional[datetime] = None
    completed_remark: Optional[str] = None


class FollowUpPlanResponse(FollowUpPlanBase):
    id: int
    is_completed: bool
    completed_time: Optional[datetime]
    completed_remark: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VisitRecordBase(BaseModel):
    work_order_id: int
    visit_time: datetime
    visitor_name: Optional[str] = Field(None, max_length=100)
    visitor_role: Optional[str] = Field(None, max_length=50)
    visit_status: Optional[VisitStatus] = VisitStatus.SCHEDULED
    visit_result: Optional[VisitResult] = None
    elderly_present: Optional[bool] = True
    visit_content: Optional[str] = None
    satisfaction_score: Optional[int] = Field(None, ge=1, le=5)
    feedback: Optional[str] = None
    next_visit_suggestion: Optional[str] = None
    archived: Optional[bool] = False


class VisitRecordCreate(VisitRecordBase):
    pass


class VisitRecordUpdate(BaseModel):
    visit_time: Optional[datetime] = None
    visitor_name: Optional[str] = None
    visitor_role: Optional[str] = None
    visit_status: Optional[VisitStatus] = None
    visit_result: Optional[VisitResult] = None
    elderly_present: Optional[bool] = None
    visit_content: Optional[str] = None
    satisfaction_score: Optional[int] = Field(None, ge=1, le=5)
    feedback: Optional[str] = None
    next_visit_suggestion: Optional[str] = None
    archived: Optional[bool] = None


class VisitRecordResponse(VisitRecordBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class OrderEscalationRequest(BaseModel):
    escalation_reason: str = Field(..., description="升级原因")
    operator_name: Optional[str] = Field(None, max_length=100)


class AdvancedStatisticsRequest(BaseModel):
    start_date: Optional[str] = Field(None, description="开始日期 YYYY-MM-DD")
    end_date: Optional[str] = Field(None, description="结束日期 YYYY-MM-DD")
    community: Optional[str] = Field(None, description="社区")
    service_type: Optional[ServiceType] = Field(None, description="服务类型")
    risk_level: Optional[RiskLevel] = Field(None, description="风险等级")


class ServiceStaffBase(BaseModel):
    name: str = Field(..., max_length=100, description="服务人员姓名")
    id_card: Optional[str] = Field(None, max_length=18, description="身份证号")
    gender: Optional[ElderlyGender] = Field(None, description="性别")
    age: Optional[int] = Field(None, ge=16, le=100, description="年龄")
    phone: Optional[str] = Field(None, max_length=20, description="联系电话")
    email: Optional[str] = Field(None, max_length=100, description="邮箱")
    address: Optional[str] = Field(None, max_length=500, description="住址")
    status: Optional[str] = Field("active", description="状态：active/inactive/on_leave")
    position: Optional[str] = Field(None, max_length=100, description="职位")
    department: Optional[str] = Field(None, max_length=100, description="所属部门")
    daily_capacity: Optional[int] = Field(8, ge=1, le=100, description="日服务容量")
    weekly_capacity: Optional[int] = Field(40, ge=1, le=500, description="周服务容量")
    monthly_capacity: Optional[int] = Field(160, ge=1, le=2000, description="月服务容量")
    hire_date: Optional[date] = Field(None, description="入职日期")
    remark: Optional[str] = Field(None, description="备注")


class ServiceStaffCreate(ServiceStaffBase):
    pass


class ServiceStaffUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    id_card: Optional[str] = Field(None, max_length=18)
    gender: Optional[ElderlyGender] = None
    age: Optional[int] = Field(None, ge=16, le=100)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=100)
    address: Optional[str] = Field(None, max_length=500)
    status: Optional[str] = None
    position: Optional[str] = Field(None, max_length=100)
    department: Optional[str] = Field(None, max_length=100)
    daily_capacity: Optional[int] = Field(None, ge=1, le=100)
    weekly_capacity: Optional[int] = Field(None, ge=1, le=500)
    monthly_capacity: Optional[int] = Field(None, ge=1, le=2000)
    hire_date: Optional[date] = None
    remark: Optional[str] = None


class ServiceStaffResponse(ServiceStaffBase):
    id: int
    staff_no: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class StaffSkillBase(BaseModel):
    staff_id: int
    skill_tag: str = Field(..., max_length=100, description="技能标签")
    proficiency: Optional[int] = Field(3, ge=1, le=5, description="熟练度")
    is_certified: Optional[bool] = Field(False, description="是否持证")
    cert_no: Optional[str] = Field(None, max_length=100, description="证书编号")
    remark: Optional[str] = None


class StaffSkillCreate(StaffSkillBase):
    pass


class StaffSkillUpdate(BaseModel):
    skill_tag: Optional[str] = None
    proficiency: Optional[int] = Field(None, ge=1, le=5)
    is_certified: Optional[bool] = None
    cert_no: Optional[str] = None
    remark: Optional[str] = None


class StaffSkillResponse(StaffSkillBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class StaffCommunityBase(BaseModel):
    staff_id: int
    community: str = Field(..., max_length=100, description="社区名称")
    is_primary: Optional[bool] = Field(False, description="是否主负责社区")
    priority: Optional[int] = Field(1, ge=1, le=5, description="优先级")
    remark: Optional[str] = None


class StaffCommunityCreate(StaffCommunityBase):
    pass


class StaffCommunityUpdate(BaseModel):
    community: Optional[str] = None
    is_primary: Optional[bool] = None
    priority: Optional[int] = Field(None, ge=1, le=5)
    remark: Optional[str] = None


class StaffCommunityResponse(StaffCommunityBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class StaffScheduleBase(BaseModel):
    staff_id: int
    schedule_date: date = Field(..., description="排班日期")
    shift_type: Optional[str] = Field("day", max_length=50, description="班次类型")
    start_time: time = Field(..., description="开始时间")
    end_time: time = Field(..., description="结束时间")
    is_available: Optional[bool] = Field(True, description="是否可派单")
    capacity: Optional[int] = Field(8, ge=0, le=100, description="当日可接单数")
    remark: Optional[str] = None


class StaffScheduleCreate(StaffScheduleBase):
    pass


class StaffScheduleUpdate(BaseModel):
    shift_type: Optional[str] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    is_available: Optional[bool] = None
    capacity: Optional[int] = Field(None, ge=0, le=100)
    remark: Optional[str] = None


class StaffScheduleResponse(StaffScheduleBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DispatchRecordBase(BaseModel):
    work_order_id: int
    staff_id: int
    dispatch_type: Optional[str] = Field("manual", description="派单类型")
    match_score: Optional[float] = Field(0, description="匹配度分数")
    remark: Optional[str] = None


class DispatchRecordCreate(DispatchRecordBase):
    pass


class DispatchReassignRequest(BaseModel):
    new_staff_id: int = Field(..., description="新的接单人员ID")
    reassign_reason: str = Field(..., description="改派原因")
    operator: Optional[str] = Field(None, max_length=100, description="操作人")
    remark: Optional[str] = None


class DispatchCancelRequest(BaseModel):
    cancel_reason: str = Field(..., description="取消原因")
    operator: Optional[str] = Field(None, max_length=100, description="操作人")


class DispatchReleaseRequest(BaseModel):
    release_reason: str = Field(..., description="释放原因")
    operator: Optional[str] = Field(None, max_length=100, description="操作人")


class DispatchConfirmRequest(BaseModel):
    operator: Optional[str] = Field(None, max_length=100, description="操作人")


class DispatchRecordResponse(BaseModel):
    id: int
    work_order_id: int
    staff_id: int
    staff_name: Optional[str] = None
    dispatch_type: Optional[str] = None
    dispatch_status: Optional[str] = None
    match_score: Optional[float] = None
    original_staff_id: Optional[int] = None
    original_staff_name: Optional[str] = None
    reassign_reason: Optional[str] = None
    reassign_operator: Optional[str] = None
    reassign_time: Optional[datetime] = None
    cancel_reason: Optional[str] = None
    cancel_operator: Optional[str] = None
    cancel_time: Optional[datetime] = None
    release_reason: Optional[str] = None
    release_operator: Optional[str] = None
    release_time: Optional[datetime] = None
    confirm_operator: Optional[str] = None
    confirm_time: Optional[datetime] = None
    remark: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CandidateStaffItem(BaseModel):
    staff_id: int
    staff_no: str
    name: str
    phone: Optional[str] = None
    position: Optional[str] = None
    match_score: float
    skill_match: bool
    community_match: bool
    time_available: bool
    current_load: int
    capacity: int
    load_rate: float
    historical_services: int
    is_certified: bool
    primary_community: Optional[str] = None


class CandidateStaffListResponse(BaseModel):
    total: int
    order_id: int
    order_no: str
    items: List[CandidateStaffItem]


class ResourceSupplyGapItem(BaseModel):
    community: str
    total_demand: int
    total_supply: int
    gap: int
    gap_rate: float


class ServiceTypeCoverageItem(BaseModel):
    service_type: str
    total_staff: int
    coverage_rate: float


class StaffLoadRankingItem(BaseModel):
    staff_id: int
    staff_name: str
    community: Optional[str] = None
    completed_orders: int
    in_progress_orders: int
    total_load: int
    capacity: int
    load_rate: float


class CapacityWarningItem(BaseModel):
    date: str
    total_capacity: int
    allocated_count: int
    remaining_capacity: int
    utilization_rate: float
    warning_level: str


class ResourceDashboardResponse(BaseModel):
    summary: dict
    supply_gap_by_community: List[ResourceSupplyGapItem]
    service_type_coverage: List[ServiceTypeCoverageItem]
    staff_load_ranking: List[StaffLoadRankingItem]
    unmatched_orders: List[dict]
    conflict_dispatches: List[dict]
    capacity_warning_7days: List[CapacityWarningItem]
    filters: dict


class LowScoreReasonBase(BaseModel):
    code: str = Field(..., max_length=50, description="原因编码")
    name: str = Field(..., max_length=200, description="原因名称")
    category: Optional[str] = Field(None, max_length=100, description="分类")
    description: Optional[str] = None
    is_active: Optional[bool] = True


class LowScoreReasonCreate(LowScoreReasonBase):
    pass


class LowScoreReasonUpdate(BaseModel):
    code: Optional[str] = Field(None, max_length=50)
    name: Optional[str] = Field(None, max_length=200)
    category: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class LowScoreReasonResponse(LowScoreReasonBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AbnormalTagBase(BaseModel):
    name: str = Field(..., max_length=100, description="标签名称")
    code: str = Field(..., max_length=50, description="标签编码")
    abnormal_type: Optional[AbnormalType] = None
    risk_level: Optional[RiskLevel] = RiskLevel.MEDIUM
    description: Optional[str] = None
    is_active: Optional[bool] = True


class AbnormalTagCreate(AbnormalTagBase):
    pass


class AbnormalTagUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    code: Optional[str] = Field(None, max_length=50)
    abnormal_type: Optional[AbnormalType] = None
    risk_level: Optional[RiskLevel] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class AbnormalTagResponse(AbnormalTagBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EvaluationIndicatorBase(BaseModel):
    name: str = Field(..., max_length=200, description="指标名称")
    code: Optional[str] = Field(None, max_length=50, description="指标编码")
    description: Optional[str] = None
    weight: Optional[float] = Field(1.0, ge=0, description="权重")
    sort_order: Optional[int] = 0
    max_score: Optional[float] = Field(5.0, gt=0, description="满分")
    is_required: Optional[bool] = True


class EvaluationIndicatorCreate(EvaluationIndicatorBase):
    pass


class EvaluationIndicatorUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    code: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = None
    weight: Optional[float] = Field(None, ge=0)
    sort_order: Optional[int] = None
    max_score: Optional[float] = Field(None, gt=0)
    is_required: Optional[bool] = None


class EvaluationIndicatorResponse(EvaluationIndicatorBase):
    id: int
    template_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EvaluationTemplateBase(BaseModel):
    name: str = Field(..., max_length=200, description="模板名称")
    service_type: ServiceType = Field(..., description="适用服务类型")
    description: Optional[str] = None
    is_active: Optional[bool] = True
    is_default: Optional[bool] = False
    created_by: Optional[str] = Field(None, max_length=100)


class EvaluationTemplateCreate(EvaluationTemplateBase):
    indicators: List[EvaluationIndicatorCreate] = Field(default_factory=list, description="评价指标列表")


class EvaluationTemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    service_type: Optional[ServiceType] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None


class EvaluationTemplateResponse(EvaluationTemplateBase):
    id: int
    created_at: datetime
    updated_at: datetime
    indicators: List[EvaluationIndicatorResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True


class IndicatorScoreItem(BaseModel):
    indicator_id: int = Field(..., description="指标ID")
    score: float = Field(..., ge=0, description="得分")


class SatisfactionFeedbackSubmit(BaseModel):
    evaluation_task_id: int = Field(..., description="评价任务ID")
    submitter_type: FeedbackSubmitterType = Field(..., description="提交人类型")
    submitter_name: Optional[str] = Field(None, max_length=100, description="提交人姓名")
    submitter_phone: Optional[str] = Field(None, max_length=20, description="提交人电话")
    submitter_relation: Optional[str] = Field(None, max_length=50, description="与老人关系")
    overall_score: float = Field(..., ge=0, le=5, description="总体满意度评分")
    feedback_text: Optional[str] = Field(None, description="文字反馈")
    complaint_content: Optional[str] = Field(None, description="投诉内容")
    is_complaint: Optional[bool] = False
    low_score_reason_id: Optional[int] = None
    low_score_reason_detail: Optional[str] = Field(None, max_length=500)
    indicator_scores: List[IndicatorScoreItem] = Field(default_factory=list, description="各指标得分")


class SatisfactionFeedbackResponse(BaseModel):
    id: int
    evaluation_task_id: int
    submitter_type: FeedbackSubmitterType
    submitter_name: Optional[str]
    submitter_phone: Optional[str]
    submitter_relation: Optional[str]
    overall_score: float
    feedback_text: Optional[str]
    complaint_content: Optional[str]
    is_complaint: bool
    low_score_reason_id: Optional[int]
    low_score_reason_name: Optional[str] = None
    low_score_reason_detail: Optional[str]
    submit_time: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class StaffSelfEvaluationSubmit(BaseModel):
    evaluation_task_id: int = Field(..., description="评价任务ID")
    staff_name: str = Field(..., max_length=100, description="服务人员姓名")
    staff_phone: Optional[str] = Field(None, max_length=20)
    self_score: float = Field(..., ge=0, le=5, description="自评分")
    service_description: Optional[str] = Field(None, description="服务说明")
    difficulty_description: Optional[str] = Field(None, description="服务难点说明")
    improvement_suggestion: Optional[str] = Field(None, description="改进建议")


class StaffSelfEvaluationResponse(BaseModel):
    id: int
    evaluation_task_id: int
    staff_name: str
    staff_phone: Optional[str]
    self_score: float
    service_description: Optional[str]
    difficulty_description: Optional[str]
    improvement_suggestion: Optional[str]
    submit_time: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class StaffReviewSubmit(BaseModel):
    evaluation_task_id: int = Field(..., description="评价任务ID")
    reviewer_name: str = Field(..., max_length=100, description="复核人姓名")
    reviewer_role: Optional[str] = Field(None, max_length=50, description="复核人角色")
    review_result: ReviewResult = Field(..., description="复核结果")
    review_score: Optional[float] = Field(None, ge=0, le=5, description="复核评分")
    review_remark: Optional[str] = Field(None, description="复核意见")
    need_rectification: Optional[bool] = False
    rectification_requirement: Optional[str] = Field(None, description="整改要求")


class StaffReviewResponse(BaseModel):
    id: int
    evaluation_task_id: int
    reviewer_name: str
    reviewer_role: Optional[str]
    review_result: ReviewResult
    review_score: Optional[float]
    review_remark: Optional[str]
    need_rectification: bool
    rectification_requirement: Optional[str]
    review_time: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class EvaluationTaskCreate(BaseModel):
    work_order_id: int = Field(..., description="工单ID")
    template_id: Optional[int] = Field(None, description="评价模板ID")
    source: Optional[EvaluationSource] = EvaluationSource.ORDER_COMPLETION
    supervision_record_id: Optional[int] = None
    expire_days: Optional[int] = Field(7, ge=1, description="过期天数")


class EvaluationTaskGenerateRequest(BaseModel):
    work_order_id: int = Field(..., description="工单ID")
    source: EvaluationSource = Field(..., description="来源类型")
    supervision_record_id: Optional[int] = None


class EvaluationTaskUpdate(BaseModel):
    status: Optional[EvaluationTaskStatus] = None
    expire_time: Optional[datetime] = None


class EvaluationTaskResponse(BaseModel):
    id: int
    task_no: str
    work_order_id: int
    work_order_no: Optional[str] = None
    elderly_id: int
    elderly_name: Optional[str] = None
    template_id: int
    template_name: Optional[str] = None
    supervision_record_id: Optional[int]
    source: EvaluationSource
    status: EvaluationTaskStatus
    assignee_name: Optional[str]
    assignee_phone: Optional[str]
    expire_time: Optional[datetime]
    overall_score: Optional[float]
    staff_self_score: Optional[float]
    reviewer_name: Optional[str]
    review_time: Optional[datetime]
    review_remark: Optional[str]
    is_abnormal: bool
    abnormal_reason: Optional[str]
    created_at: datetime
    updated_at: datetime
    feedbacks: List[SatisfactionFeedbackResponse] = Field(default_factory=list)
    self_evaluation: Optional[StaffSelfEvaluationResponse] = None
    reviews: List[StaffReviewResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True


class EvaluationTaskListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[EvaluationTaskResponse]


class AbnormalWarningResponse(BaseModel):
    id: int
    warning_no: str
    abnormal_type: AbnormalType
    work_order_id: Optional[int]
    work_order_no: Optional[str] = None
    elderly_id: int
    elderly_name: Optional[str] = None
    evaluation_task_id: Optional[int]
    staff_name: Optional[str]
    tag_id: Optional[int]
    tag_name: Optional[str]
    risk_level: RiskLevel
    title: str
    description: Optional[str]
    status: AbnormalStatus
    triggered_by: str
    trigger_time: datetime
    handler_name: Optional[str]
    handle_time: Optional[datetime]
    handle_remark: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AbnormalWarningHandleRequest(BaseModel):
    handler_name: str = Field(..., max_length=100, description="处理人姓名")
    handle_remark: str = Field(..., description="处理说明")
    status: Optional[AbnormalStatus] = AbnormalStatus.PROCESSING


class RectificationTaskCreate(BaseModel):
    abnormal_warning_id: Optional[int] = None
    evaluation_task_id: Optional[int] = None
    title: str = Field(..., max_length=500, description="任务标题")
    description: Optional[str] = None
    responsible_person: str = Field(..., max_length=100, description="责任人")
    responsible_phone: Optional[str] = Field(None, max_length=20)
    deadline: datetime = Field(..., description="截止时间")
    created_by: Optional[str] = Field(None, max_length=100)


class RectificationTaskComplete(BaseModel):
    handle_description: str = Field(..., description="处理说明")
    handle_evidence: Optional[str] = Field(None, description="处理凭证")


class RectificationTaskReview(BaseModel):
    reviewer_name: str = Field(..., max_length=100, description="复核人姓名")
    review_remark: str = Field(..., description="复核意见")
    passed: bool = Field(..., description="是否通过")


class RectificationTaskResponse(BaseModel):
    id: int
    task_no: str
    abnormal_warning_id: Optional[int]
    evaluation_task_id: Optional[int]
    work_order_id: Optional[int]
    work_order_no: Optional[str] = None
    elderly_id: Optional[int]
    elderly_name: Optional[str] = None
    title: str
    description: Optional[str]
    responsible_person: str
    responsible_phone: Optional[str]
    deadline: datetime
    status: RectificationStatus
    handle_description: Optional[str]
    handle_evidence: Optional[str]
    completion_time: Optional[datetime]
    reviewer_name: Optional[str]
    review_remark: Optional[str]
    review_time: Optional[datetime]
    archive_time: Optional[datetime]
    is_overdue: bool
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RectificationTaskListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[RectificationTaskResponse]


class QualityStatisticsFilter(BaseModel):
    community: Optional[str] = None
    service_type: Optional[ServiceType] = None
    staff_name: Optional[str] = None
    risk_level: Optional[RiskLevel] = None
    min_score: Optional[float] = Field(None, ge=0, le=5)
    max_score: Optional[float] = Field(None, ge=0, le=5)
    abnormal_tag_id: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class ServiceTypeSatisfactionItem(BaseModel):
    service_type: ServiceType
    total_evaluations: int
    avg_satisfaction: float
    weighted_avg: float


class StaffQualityRankingItem(BaseModel):
    staff_name: str
    total_evaluations: int
    avg_score: float
    low_score_count: int
    complaint_count: int
    ranking: int


class CommunityAbnormalItem(BaseModel):
    community: str
    total_abnormal: int
    low_satisfaction_count: int
    no_visit_count: int
    repeat_low_score_count: int
    staff_abnormal_count: int
    multiple_complaints_count: int


class OverdueRectificationItem(BaseModel):
    task_id: int
    task_no: str
    title: str
    responsible_person: str
    deadline: datetime
    overdue_days: int
    work_order_no: Optional[str] = None
    elderly_name: Optional[str] = None


class RepeatComplaintElderlyItem(BaseModel):
    elderly_id: int
    elderly_name: str
    community: str
    complaint_count: int
    last_complaint_time: Optional[datetime]
    related_orders: List[dict] = Field(default_factory=list)


class QualityTrendItem(BaseModel):
    date: str
    total_evaluations: int
    avg_satisfaction: float
    low_score_count: int
    abnormal_count: int


class QualityStatisticsResponse(BaseModel):
    summary: dict
    service_type_satisfaction: List[ServiceTypeSatisfactionItem]
    staff_quality_ranking: List[StaffQualityRankingItem]
    community_abnormal_distribution: List[CommunityAbnormalItem]
    overdue_rectification_list: List[OverdueRectificationItem]
    repeat_complaint_elderly_list: List[RepeatComplaintElderlyItem]
    evaluation_completion_rate: float
    visit_coverage_rate: float
    quality_trend_30days: List[QualityTrendItem]
    filters: dict


class AbnormalDetectionRequest(BaseModel):
    days: Optional[int] = Field(30, ge=1, le=365, description="检测时间范围(天)")
    community: Optional[str] = None
    service_type: Optional[ServiceType] = None
