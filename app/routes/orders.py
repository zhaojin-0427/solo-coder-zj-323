from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timedelta, date, time
import uuid

from app.database import get_db
from app.models import (
    WorkOrder, ElderlyProfile, ProgressRecord,
    OrderStatus, ProgressType, ServiceType, RiskLevel,
    SLAConfig, CommunityCalendar, HolidayRecord
)
from app.schemas import (
    WorkOrderCreate, WorkOrderUpdate, WorkOrderResponse,
    WorkOrderListResponse, WorkOrderAssign, WorkOrderArrive,
    WorkOrderComplete, WorkOrderIncomplete, ProgressRecordResponse
)
from app.utils import success_response, error_response, ApiResponse, orm_to_dict

router = APIRouter(prefix="/orders", tags=["工单管理"])


def generate_order_no() -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    suffix = uuid.uuid4().hex[:6].upper()
    return f"WO{timestamp}{suffix}"


def add_progress_record(db: Session, work_order_id: int, progress_type: ProgressType,
                        operator_name: str = None, operator_role: str = None, remark: str = None):
    record = ProgressRecord(
        work_order_id=work_order_id,
        progress_type=progress_type,
        operator_name=operator_name,
        operator_role=operator_role,
        remark=remark
    )
    db.add(record)


def check_timeout(db: Session, order: WorkOrder):
    now = datetime.now()
    if order.status in [OrderStatus.PENDING, OrderStatus.ASSIGNED, OrderStatus.IN_PROGRESS]:
        if now > order.appointment_end:
            timeout_delta = now - order.appointment_end
            timeout_hours = round(timeout_delta.total_seconds() / 3600, 2)
            order.is_timeout = 1
            order.timeout_hours = timeout_hours
        else:
            order.is_timeout = 0
            order.timeout_hours = 0


def calculate_working_hours(db: Session, community: str, start: datetime, end: datetime) -> float:
    calendar = db.query(CommunityCalendar).filter(
        CommunityCalendar.community == community
    ).first()
    if not calendar:
        total_seconds = (end - start).total_seconds()
        return round(total_seconds / 3600, 2)

    work_days = [int(d) for d in calendar.work_days.split(",") if d.strip()]
    work_start = calendar.work_start_time or time(8, 0, 0)
    work_end = calendar.work_end_time or time(18, 0, 0)
    exclude_holidays = calendar.exclude_holidays

    total_hours = 0.0
    current = start
    while current < end:
        day_start = datetime.combine(current.date(), work_start)
        day_end = datetime.combine(current.date(), work_end)

        actual_start = max(current, day_start)
        actual_end = min(end, day_end)

        is_workday = current.isoweekday() in work_days

        if exclude_holidays:
            holiday = db.query(HolidayRecord).filter(
                HolidayRecord.community.in_([community, ""]),
                HolidayRecord.holiday_date == current.date()
            ).first()
            if holiday and not holiday.is_workday:
                is_workday = False
            elif holiday and holiday.is_workday:
                is_workday = True

        if is_workday and actual_end > actual_start:
            total_hours += (actual_end - actual_start).total_seconds() / 3600

        current = datetime.combine(current.date() + timedelta(days=1), work_start)

    return round(total_hours, 2)


def calculate_sla_deadline(db: Session, order: WorkOrder) -> datetime:
    config = db.query(SLAConfig).filter(
        SLAConfig.service_type == order.service_type,
        SLAConfig.is_active == True
    ).first()
    if not config:
        resolution_hours = 24.0
    else:
        resolution_hours = config.resolution_hours

    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()
    community = elderly.community if elderly else ""

    deadline = order.appointment_end
    hours_added = 0.0
    current = order.appointment_end

    while hours_added < resolution_hours:
        next_hour = current + timedelta(hours=1)
        working = calculate_working_hours(db, community, current, next_hour)
        if working > 0:
            hours_added += working
        current = next_hour

    return current


def calculate_supervision_priority(db: Session, order: WorkOrder) -> tuple:
    score = 0.0
    now = datetime.now()

    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()
    if elderly:
        if elderly.risk_level == RiskLevel.CRITICAL:
            score += 40
        elif elderly.risk_level == RiskLevel.HIGH:
            score += 30
        elif elderly.risk_level == RiskLevel.MEDIUM:
            score += 15

    if order.is_timeout == 1:
        if order.timeout_hours >= 72:
            score += 50
        elif order.timeout_hours >= 48:
            score += 40
        elif order.timeout_hours >= 24:
            score += 30
        elif order.timeout_hours >= 12:
            score += 20
        elif order.timeout_hours >= 6:
            score += 10
        else:
            score += 5

    historical = db.query(WorkOrder).filter(
        WorkOrder.elderly_id == order.elderly_id,
        WorkOrder.status == OrderStatus.INCOMPLETE
    ).count()
    order.historical_incomplete_count = historical
    score += historical * 10

    if order.manually_escalated:
        score += 25

    if score >= 80:
        risk_level = RiskLevel.CRITICAL
    elif score >= 60:
        risk_level = RiskLevel.HIGH
    elif score >= 30:
        risk_level = RiskLevel.MEDIUM
    else:
        risk_level = RiskLevel.LOW

    return round(score, 2), risk_level


@router.post("", response_model=ApiResponse[WorkOrderResponse])
def create_order(order_data: WorkOrderCreate, db: Session = Depends(get_db)):
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order_data.elderly_id).first()
    if not elderly:
        return error_response(code=404, message="老人档案不存在")

    order_no = generate_order_no()
    db_order = WorkOrder(
        order_no=order_no,
        **order_data.model_dump()
    )
    db.add(db_order)
    db.flush()

    db_order.sla_deadline = calculate_sla_deadline(db, db_order)
    score, risk_level = calculate_supervision_priority(db, db_order)
    db_order.supervision_priority_score = score
    db_order.supervision_risk_level = risk_level

    add_progress_record(
        db, db_order.id, ProgressType.CREATED,
        operator_name="系统", operator_role="system",
        remark=f"工单创建成功，工单号：{order_no}；SLA截止时间：{db_order.sla_deadline.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    db.commit()
    db.refresh(db_order)

    result = orm_to_dict(db_order)
    result["elderly_name"] = elderly.name
    return success_response(data=result, message="工单创建成功")


@router.get("", response_model=ApiResponse[WorkOrderListResponse])
def list_orders(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    elderly_id: Optional[int] = Query(None, description="老人ID"),
    status: Optional[str] = Query(None, description="工单状态"),
    service_type: Optional[str] = Query(None, description="服务类型"),
    is_timeout: Optional[int] = Query(None, description="是否超时"),
    start_date: Optional[str] = Query(None, description="开始日期"),
    end_date: Optional[str] = Query(None, description="结束日期"),
    community: Optional[str] = Query(None, description="社区筛选"),
    risk_level: Optional[str] = Query(None, description="督办风险等级筛选"),
    manually_escalated: Optional[bool] = Query(None, description="是否人工升级"),
    sla_achieved: Optional[bool] = Query(None, description="SLA是否达成"),
    db: Session = Depends(get_db)
):
    now = datetime.now()
    pending_orders = db.query(WorkOrder).filter(
        WorkOrder.status.in_([OrderStatus.PENDING, OrderStatus.ASSIGNED, OrderStatus.IN_PROGRESS])
    ).all()
    for order in pending_orders:
        if now > order.appointment_end:
            timeout_delta = now - order.appointment_end
            timeout_hours = round(timeout_delta.total_seconds() / 3600, 2)
            order.is_timeout = 1
            order.timeout_hours = timeout_hours
        else:
            order.is_timeout = 0
            order.timeout_hours = 0
    db.commit()
    
    query = db.query(WorkOrder)

    if elderly_id:
        query = query.filter(WorkOrder.elderly_id == elderly_id)
    if status:
        query = query.filter(WorkOrder.status == status)
    if service_type:
        query = query.filter(WorkOrder.service_type == service_type)
    if is_timeout is not None:
        query = query.filter(WorkOrder.is_timeout == is_timeout)
    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        query = query.filter(WorkOrder.created_at >= start_dt)
    if end_date:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        query = query.filter(WorkOrder.created_at < end_dt)
    if community:
        query = query.join(ElderlyProfile).filter(ElderlyProfile.community == community)
    if risk_level:
        query = query.filter(WorkOrder.supervision_risk_level == risk_level)
    if manually_escalated is not None:
        query = query.filter(WorkOrder.manually_escalated == manually_escalated)
    if sla_achieved is not None:
        query = query.filter(WorkOrder.sla_achieved == sla_achieved)
    
    total = query.count()
    orders = query.order_by(WorkOrder.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    items = []
    for order in orders:
        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()
        order_dict = orm_to_dict(order)
        order_dict["elderly_name"] = elderly.name if elderly else ""
        items.append(order_dict)
    
    return success_response(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    })


@router.get("/{order_id}", response_model=ApiResponse)
def get_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
    if not order:
        return error_response(code=404, message="工单不存在")

    check_timeout(db, order)

    if not order.sla_deadline:
        order.sla_deadline = calculate_sla_deadline(db, order)
    if order.completion_time and order.sla_deadline and order.sla_achieved is None:
        order.sla_achieved = order.completion_time <= order.sla_deadline

    score, risk_level = calculate_supervision_priority(db, order)
    order.supervision_priority_score = score
    order.supervision_risk_level = risk_level

    db.commit()
    db.refresh(order)

    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()
    progress_records = db.query(ProgressRecord).filter(
        ProgressRecord.work_order_id == order_id
    ).order_by(ProgressRecord.id.asc()).all()

    from app.models import (
        DuplicateSuggestion, SupervisionRecord, FollowUpPlan, VisitRecord
    )
    merge_suggestions = db.query(DuplicateSuggestion).filter(
        (DuplicateSuggestion.master_order_id == order_id) |
        (DuplicateSuggestion.slave_order_id == order_id)
    ).order_by(DuplicateSuggestion.created_at.desc()).all()

    supervision_records = db.query(SupervisionRecord).filter(
        SupervisionRecord.work_order_id == order_id
    ).order_by(SupervisionRecord.created_at.desc()).all()

    follow_up_plans = db.query(FollowUpPlan).filter(
        FollowUpPlan.work_order_id == order_id
    ).order_by(FollowUpPlan.planned_time.asc()).all()

    visit_records = db.query(VisitRecord).filter(
        VisitRecord.work_order_id == order_id
    ).order_by(VisitRecord.visit_time.desc()).all()

    merged_orders = []
    if order.is_master_order:
        slaves = db.query(WorkOrder).filter(WorkOrder.master_order_id == order_id).all()
        for s in slaves:
            s_elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == s.elderly_id).first()
            merged_orders.append({
                "id": s.id,
                "order_no": s.order_no,
                "elderly_name": s_elderly.name if s_elderly else "",
                "service_type": s.service_type,
                "status": s.status,
                "created_at": s.created_at
            })

    master_info = None
    if order.master_order_id:
        master = db.query(WorkOrder).filter(WorkOrder.id == order.master_order_id).first()
        if master:
            m_elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == master.elderly_id).first()
            master_info = {
                "id": master.id,
                "order_no": master.order_no,
                "elderly_name": m_elderly.name if m_elderly else "",
                "service_type": master.service_type,
                "status": master.status,
                "created_at": master.created_at
            }

    order_dict = orm_to_dict(order)
    order_dict["elderly_name"] = elderly.name if elderly else ""
    order_dict["community"] = elderly.community if elderly else ""
    order_dict["progress_records"] = orm_to_dict(progress_records)
    order_dict["merge_suggestions"] = orm_to_dict(merge_suggestions)
    order_dict["supervision_records"] = orm_to_dict(supervision_records)
    order_dict["follow_up_plans"] = orm_to_dict(follow_up_plans)
    order_dict["visit_records"] = orm_to_dict(visit_records)
    order_dict["merged_orders"] = merged_orders
    order_dict["master_order_info"] = master_info

    return success_response(data=order_dict)


@router.put("/{order_id}/assign", response_model=ApiResponse[WorkOrderResponse])
def assign_order(order_id: int, assign_data: WorkOrderAssign, db: Session = Depends(get_db)):
    order = db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
    if not order:
        return error_response(code=404, message="工单不存在")
    if order.status not in [OrderStatus.PENDING]:
        return error_response(code=400, message="当前状态不可接单")
    
    order.assignee_name = assign_data.assignee_name
    order.assignee_phone = assign_data.assignee_phone
    order.status = OrderStatus.ASSIGNED
    
    add_progress_record(
        db, order.id, ProgressType.ASSIGNED,
        operator_name=assign_data.assignee_name, operator_role="assignee",
        remark=f"接单成功，接单人员：{assign_data.assignee_name}"
    )
    
    db.commit()
    db.refresh(order)
    
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()
    result = orm_to_dict(order)
    result["elderly_name"] = elderly.name if elderly else ""
    return success_response(data=result, message="接单成功")


@router.put("/{order_id}/arrive", response_model=ApiResponse[WorkOrderResponse])
def arrive_order(order_id: int, arrive_data: WorkOrderArrive, db: Session = Depends(get_db)):
    order = db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
    if not order:
        return error_response(code=404, message="工单不存在")
    if order.status not in [OrderStatus.ASSIGNED, OrderStatus.IN_PROGRESS]:
        return error_response(code=400, message="当前状态不可上报到达")
    
    order.arrival_time = arrive_data.arrival_time
    order.status = OrderStatus.IN_PROGRESS
    
    add_progress_record(
        db, order.id, ProgressType.ARRIVED,
        operator_name=order.assignee_name, operator_role="assignee",
        remark=f"已到达服务地点，到达时间：{arrive_data.arrival_time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    db.commit()
    db.refresh(order)
    
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()
    result = orm_to_dict(order)
    result["elderly_name"] = elderly.name if elderly else ""
    return success_response(data=result, message="到达时间已记录")


@router.put("/{order_id}/complete", response_model=ApiResponse[WorkOrderResponse])
def complete_order(order_id: int, complete_data: WorkOrderComplete, db: Session = Depends(get_db)):
    order = db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
    if not order:
        return error_response(code=404, message="工单不存在")
    if order.status not in [OrderStatus.IN_PROGRESS]:
        return error_response(code=400, message="当前状态不可完成")

    completion_time = complete_data.completion_time or datetime.now()
    order.completion_time = completion_time
    order.handle_summary = complete_data.handle_summary
    order.status = OrderStatus.COMPLETED
    order.closed_at = completion_time

    if not order.sla_deadline:
        order.sla_deadline = calculate_sla_deadline(db, order)
    order.sla_achieved = completion_time <= order.sla_deadline if order.sla_deadline else None

    sla_remark = ""
    if order.sla_achieved is not None:
        sla_remark = "；SLA达标" if order.sla_achieved else "；SLA未达标"

    add_progress_record(
        db, order.id, ProgressType.COMPLETED,
        operator_name=order.assignee_name, operator_role="assignee",
        remark=f"服务已完成，处理摘要：{complete_data.handle_summary[:50]}...{sla_remark}"
    )

    check_timeout(db, order)
    db.commit()
    db.refresh(order)

    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()
    result = orm_to_dict(order)
    result["elderly_name"] = elderly.name if elderly else ""
    return success_response(data=result, message="工单已完成")


@router.put("/{order_id}/incomplete", response_model=ApiResponse[WorkOrderResponse])
def incomplete_order(order_id: int, incomplete_data: WorkOrderIncomplete, db: Session = Depends(get_db)):
    order = db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
    if not order:
        return error_response(code=404, message="工单不存在")
    if order.status not in [OrderStatus.IN_PROGRESS]:
        return error_response(code=400, message="当前状态不可标记未完成")
    
    completion_time = incomplete_data.completion_time or datetime.now()
    order.completion_time = completion_time
    order.incomplete_reason = incomplete_data.incomplete_reason
    order.handle_summary = incomplete_data.handle_summary
    order.status = OrderStatus.INCOMPLETE
    
    add_progress_record(
        db, order.id, ProgressType.INCOMPLETE,
        operator_name=order.assignee_name, operator_role="assignee",
        remark=f"服务未完成，原因：{incomplete_data.incomplete_reason}"
    )
    
    check_timeout(db, order)
    db.commit()
    db.refresh(order)
    
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()
    result = orm_to_dict(order)
    result["elderly_name"] = elderly.name if elderly else ""
    return success_response(data=result, message="已标记为未完成")


@router.put("/{order_id}/close", response_model=ApiResponse[WorkOrderResponse])
def close_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
    if not order:
        return error_response(code=404, message="工单不存在")
    if order.status not in [OrderStatus.COMPLETED, OrderStatus.INCOMPLETE]:
        return error_response(code=400, message="当前状态不可关闭")
    
    order.status = OrderStatus.CLOSED
    order.closed_at = datetime.now()
    
    add_progress_record(
        db, order.id, ProgressType.CLOSED,
        operator_name="系统", operator_role="system",
        remark="工单已关闭归档"
    )
    
    db.commit()
    db.refresh(order)
    
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()
    result = orm_to_dict(order)
    result["elderly_name"] = elderly.name if elderly else ""
    return success_response(data=result, message="工单已关闭归档")


@router.get("/{order_id}/progress", response_model=ApiResponse)
def get_order_progress(order_id: int, db: Session = Depends(get_db)):
    order = db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
    if not order:
        return error_response(code=404, message="工单不存在")
    
    progress_records = db.query(ProgressRecord).filter(
        ProgressRecord.work_order_id == order_id
    ).order_by(ProgressRecord.id.asc()).all()
    
    return success_response(data={
        "order_id": order_id,
        "order_no": order.order_no,
        "current_status": order.status,
        "progress_records": orm_to_dict(progress_records)
    })
