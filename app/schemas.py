from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date, time
from app.models import (
    ElderlyGender, OrderStatus, ServiceType, RiskLevel, ProgressType,
    MergeStatus, SupervisionStatus, VisitStatus, VisitResult
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
