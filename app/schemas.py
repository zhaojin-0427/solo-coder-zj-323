from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from app.models import (
    ElderlyGender, OrderStatus, ServiceType, RiskLevel, ProgressType
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
