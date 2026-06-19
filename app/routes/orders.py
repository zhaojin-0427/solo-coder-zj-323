from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timedelta
import uuid

from app.database import get_db
from app.models import (
    WorkOrder, ElderlyProfile, ProgressRecord,
    OrderStatus, ProgressType, ServiceType
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
    
    add_progress_record(
        db, db_order.id, ProgressType.CREATED,
        operator_name="系统", operator_role="system",
        remark=f"工单创建成功，工单号：{order_no}"
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
    db.commit()
    db.refresh(order)
    
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()
    progress_records = db.query(ProgressRecord).filter(
        ProgressRecord.work_order_id == order_id
    ).order_by(ProgressRecord.id.asc()).all()
    
    order_dict = orm_to_dict(order)
    order_dict["elderly_name"] = elderly.name if elderly else ""
    order_dict["progress_records"] = orm_to_dict(progress_records)
    
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
    
    add_progress_record(
        db, order.id, ProgressType.COMPLETED,
        operator_name=order.assignee_name, operator_role="assignee",
        remark=f"服务已完成，处理摘要：{complete_data.handle_summary[:50]}..."
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
