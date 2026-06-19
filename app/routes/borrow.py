from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from typing import Optional, List
from datetime import datetime, timedelta, date
import uuid

from app.database import get_db
from app.models import (
    BorrowApplication, BorrowItem, MaterialReturn, ReturnItem, MaterialScrap,
    BorrowStatus, ReturnCondition, ScrapReason,
    InventoryBatch, Material, MaterialWarehouse, ElderlyProfile, WorkOrder, ProgressRecord,
    InventoryStatus, MaterialStatus, ServiceTypeMaterial,
    OrderStatus, ProgressType, RiskLevel
)
from app.schemas import (
    BorrowApplicationCreate, BorrowApplicationUpdate, BorrowApplicationResponse, BorrowApplicationListResponse,
    BorrowApproveRequest, BorrowRejectRequest, BorrowPickupRequest, BorrowCancelRequest,
    BorrowItemResponse
)
from app.utils import success_response, error_response, ApiResponse, orm_to_dict

router = APIRouter(prefix="/material/borrow", tags=["物资借用管理"])


def generate_no(prefix: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    suffix = uuid.uuid4().hex[:6].upper()
    return f"{prefix}{timestamp}{suffix}"


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


def lock_inventory(db: Session, batch_id: int, quantity: int) -> tuple:
    batch = db.query(InventoryBatch).filter(InventoryBatch.id == batch_id).first()
    if not batch:
        return False, "批次不存在"
    if batch.available_quantity < quantity:
        return False, f"批次可用库存不足，当前可用：{batch.available_quantity}，需要：{quantity}"
    batch.available_quantity -= quantity
    batch.locked_quantity += quantity
    db.flush()
    return True, "锁定成功"


def release_inventory(db: Session, batch_id: int, quantity: int) -> tuple:
    batch = db.query(InventoryBatch).filter(InventoryBatch.id == batch_id).first()
    if not batch:
        return False, "批次不存在"
    release_qty = min(quantity, batch.locked_quantity)
    batch.available_quantity += release_qty
    batch.locked_quantity -= release_qty
    db.flush()
    return True, "释放成功"


def validate_borrow_eligibility(db: Session, elderly_id: int, material_id: int, community: str) -> tuple:
    active_borrows = db.query(BorrowApplication).join(BorrowItem).filter(
        BorrowApplication.elderly_id == elderly_id,
        BorrowItem.material_id == material_id,
        BorrowApplication.status.in_([BorrowStatus.PENDING, BorrowStatus.APPROVED, BorrowStatus.PICKED_UP, BorrowStatus.PARTIAL_RETURNED]),
        BorrowItem.picked_quantity > BorrowItem.returned_quantity
    ).count()
    if active_borrows > 0:
        return False, "该老人有此物资未归还记录，不可再次借用"
    return True, "资格校验通过"


def select_available_batch(db: Session, material_id: int, community: str, quantity: int, appointment_time: datetime = None) -> Optional[InventoryBatch]:
    warehouse = db.query(MaterialWarehouse).filter(
        MaterialWarehouse.community == community
    ).first()
    if not warehouse:
        return None

    query = db.query(InventoryBatch).filter(
        InventoryBatch.material_id == material_id,
        InventoryBatch.warehouse_id == warehouse.id,
        InventoryBatch.status.in_([InventoryStatus.NORMAL, InventoryStatus.LOW_STOCK]),
        InventoryBatch.available_quantity >= quantity
    )

    if appointment_time:
        query = query.filter(
            or_(
                InventoryBatch.expiry_date == None,
                InventoryBatch.expiry_date >= appointment_time.date()
            )
        )

    batch = query.order_by(
        InventoryBatch.expiry_date.asc().nullslast(),
        InventoryBatch.id.asc()
    ).first()

    return batch


def check_material_in_service_type(db, service_type, material_id: int) -> bool:
    config = db.query(ServiceTypeMaterial).filter(
        ServiceTypeMaterial.service_type == service_type,
        ServiceTypeMaterial.material_id == material_id
    ).first()
    return config is not None


def release_borrow_locks(db: Session, borrow_id: int):
    borrow_items = db.query(BorrowItem).filter(BorrowItem.borrow_id == borrow_id).all()
    for item in borrow_items:
        if item.locked_quantity > 0:
            release_inventory(db, item.batch_id, item.locked_quantity)
            item.locked_quantity = 0
            item.is_locked = False
    db.flush()


def release_inventory_by_order_status(db: Session, order_id: int, new_status):
    if new_status not in [OrderStatus.CANCELLED, OrderStatus.INCOMPLETE, OrderStatus.CLOSED]:
        return

    borrow_applications = db.query(BorrowApplication).filter(
        BorrowApplication.work_order_id == order_id,
        BorrowApplication.status.in_([BorrowStatus.PENDING, BorrowStatus.APPROVED])
    ).all()

    for app in borrow_applications:
        release_borrow_locks(db, app.id)
        app.status = BorrowStatus.CANCELLED
        app.cancel_reason = f"工单状态变更为{new_status.value}，自动取消借用"
        add_progress_record(
            db, order_id, ProgressType.CLOSED,
            operator_name="系统", operator_role="system",
            remark=f"工单状态变更，自动取消借用申请：{app.borrow_no}"
        )


@router.post("/applications", response_model=ApiResponse[BorrowApplicationResponse])
def create_application(app_data: BorrowApplicationCreate, db: Session = Depends(get_db)):
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == app_data.elderly_id).first()
    if not elderly:
        return error_response(code=404, message="老人档案不存在")
    community = elderly.community

    work_order = None
    if app_data.work_order_id:
        work_order = db.query(WorkOrder).filter(WorkOrder.id == app_data.work_order_id).first()
        if not work_order:
            return error_response(code=404, message="关联工单不存在")

    if not app_data.items or len(app_data.items) == 0:
        return error_response(code=400, message="借用物资清单不能为空")

    borrow_no = generate_no("BR")
    db_app = BorrowApplication(
        borrow_no=borrow_no,
        work_order_id=app_data.work_order_id,
        elderly_id=app_data.elderly_id,
        community=community,
        applicant_name=app_data.applicant_name,
        applicant_phone=app_data.applicant_phone,
        appointment_time=app_data.appointment_time,
        expected_return_time=app_data.expected_return_time,
        status=BorrowStatus.PENDING,
        remark=app_data.remark
    )
    db.add(db_app)
    db.flush()

    total_quantity = 0
    processed_items = []

    try:
        for idx, item_data in enumerate(app_data.items):
            material = db.query(Material).filter(Material.id == item_data.material_id).first()
            if not material:
                raise ValueError(f"第{idx + 1}条物资不存在")
            if material.status != MaterialStatus.ACTIVE:
                raise ValueError(f"第{idx + 1}条物资状态异常，不可借用")

            if work_order and work_order.service_type:
                if not check_material_in_service_type(db, work_order.service_type, item_data.material_id):
                    raise ValueError(f"第{idx + 1}条物资不在服务类型[{work_order.service_type.value}]可领用清单中")

            eligible, msg = validate_borrow_eligibility(db, app_data.elderly_id, item_data.material_id, community)
            if not eligible:
                raise ValueError(f"第{idx + 1}条：{msg}")

            batch_id = item_data.batch_id
            if not batch_id:
                batch = select_available_batch(db, item_data.material_id, community, item_data.requested_quantity, app_data.appointment_time)
                if not batch:
                    raise ValueError(f"第{idx + 1}条物资[{material.material_name}]在[{community}]社区仓库无可用库存")
                batch_id = batch.id
            else:
                batch = db.query(InventoryBatch).filter(InventoryBatch.id == batch_id).first()
                if not batch:
                    raise ValueError(f"第{idx + 1}条批次不存在")
                if batch.status not in [InventoryStatus.NORMAL, InventoryStatus.LOW_STOCK]:
                    raise ValueError(f"第{idx + 1}条批次状态异常，不可借用")
                if batch.warehouse:
                    if batch.warehouse.community != community:
                        raise ValueError(f"第{idx + 1}条批次所在仓库社区与老人社区不一致")
                if batch.available_quantity < item_data.requested_quantity:
                    raise ValueError(f"第{idx + 1}条批次可用库存不足")
                if batch.expiry_date and app_data.appointment_time:
                    if batch.expiry_date < app_data.appointment_time.date():
                        raise ValueError(f"第{idx + 1}条批次已过期或预约时段不在有效期内")

            locked, lock_msg = lock_inventory(db, batch_id, item_data.requested_quantity)
            if not locked:
                raise ValueError(f"第{idx + 1}条：{lock_msg}")

            db_item = BorrowItem(
                borrow_id=db_app.id,
                material_id=item_data.material_id,
                batch_id=batch_id,
                material_name=material.material_name,
                material_code=material.material_code,
                spec=material.spec,
                unit=material.unit,
                requested_quantity=item_data.requested_quantity,
                approved_quantity=item_data.requested_quantity,
                locked_quantity=item_data.requested_quantity,
                is_locked=True,
                unit_price=batch.unit_price if batch else 0,
                remark=item_data.remark
            )
            db.add(db_item)
            db.flush()
            processed_items.append(db_item)
            total_quantity += item_data.requested_quantity

        db_app.total_items = len(processed_items)
        db_app.total_quantity = total_quantity

        if work_order:
            add_progress_record(
                db, work_order.id, ProgressType.IN_PROGRESS,
                operator_name=app_data.applicant_name or "系统", operator_role="applicant",
                remark=f"创建借用申请：{borrow_no}，共{len(processed_items)}种物资，{total_quantity}件"
            )

        db.commit()
        db.refresh(db_app)

    except ValueError as e:
        db.rollback()
        return error_response(code=400, message=str(e))
    except Exception as e:
        db.rollback()
        return error_response(code=500, message=f"创建借用申请失败：{str(e)}")

    result = orm_to_dict(db_app)
    result["elderly_name"] = elderly.name
    result["order_no"] = work_order.order_no if work_order else None
    result["items"] = orm_to_dict(processed_items)

    return success_response(data=result, message="借用申请创建成功")


@router.get("/applications", response_model=ApiResponse[BorrowApplicationListResponse])
def list_applications(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    community: Optional[str] = Query(None, description="社区筛选"),
    elderly_id: Optional[int] = Query(None, description="老人ID筛选"),
    work_order_id: Optional[int] = Query(None, description="工单ID筛选"),
    status: Optional[str] = Query(None, description="状态筛选"),
    material_id: Optional[int] = Query(None, description="物资ID筛选"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    db: Session = Depends(get_db)
):
    query = db.query(BorrowApplication)

    if community:
        query = query.filter(BorrowApplication.community == community)
    if elderly_id:
        query = query.filter(BorrowApplication.elderly_id == elderly_id)
    if work_order_id:
        query = query.filter(BorrowApplication.work_order_id == work_order_id)
    if status:
        try:
            query = query.filter(BorrowApplication.status == BorrowStatus(status))
        except ValueError:
            return error_response(code=400, message=f"无效的状态值: {status}")
    if material_id:
        query = query.join(BorrowItem).filter(BorrowItem.material_id == material_id)
    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        query = query.filter(BorrowApplication.created_at >= start_dt)
    if end_date:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        query = query.filter(BorrowApplication.created_at < end_dt)

    total = query.count()
    apps = query.order_by(BorrowApplication.id.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for app in apps:
        app_dict = orm_to_dict(app)
        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == app.elderly_id).first()
        app_dict["elderly_name"] = elderly.name if elderly else None
        work_order = db.query(WorkOrder).filter(WorkOrder.id == app.work_order_id).first()
        app_dict["order_no"] = work_order.order_no if work_order else None
        app_dict["items"] = orm_to_dict(app.items)
        items.append(app_dict)

    return success_response(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    })


@router.get("/applications/{borrow_id}", response_model=ApiResponse[BorrowApplicationResponse])
def get_application(borrow_id: int, db: Session = Depends(get_db)):
    app = db.query(BorrowApplication).filter(BorrowApplication.id == borrow_id).first()
    if not app:
        return error_response(code=404, message="借用申请不存在")

    result = orm_to_dict(app)
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == app.elderly_id).first()
    result["elderly_name"] = elderly.name if elderly else None
    work_order = db.query(WorkOrder).filter(WorkOrder.id == app.work_order_id).first()
    result["order_no"] = work_order.order_no if work_order else None
    result["items"] = orm_to_dict(app.items)

    return success_response(data=result)


@router.put("/applications/{borrow_id}", response_model=ApiResponse[BorrowApplicationResponse])
def update_application(borrow_id: int, app_update: BorrowApplicationUpdate, db: Session = Depends(get_db)):
    app = db.query(BorrowApplication).filter(BorrowApplication.id == borrow_id).first()
    if not app:
        return error_response(code=404, message="借用申请不存在")
    if app.status != BorrowStatus.PENDING:
        return error_response(code=400, message=f"当前状态为{app.status.value}，仅PENDING状态可更新")

    for item in app.items:
        if item.locked_quantity > 0:
            release_inventory(db, item.batch_id, item.locked_quantity)
            item.locked_quantity = 0
            item.is_locked = False
    db.flush()

    update_data = app_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(app, key, value)

    try:
        for item in app.items:
            eligible, msg = validate_borrow_eligibility(db, app.elderly_id, item.material_id, app.community)
            if not eligible:
                raise ValueError(msg)

            batch = db.query(InventoryBatch).filter(InventoryBatch.id == item.batch_id).first()
            if not batch:
                raise ValueError(f"物资[{item.material_name}]批次不存在")
            if batch.status not in [InventoryStatus.NORMAL, InventoryStatus.LOW_STOCK]:
                raise ValueError(f"物资[{item.material_name}]批次状态异常，不可借用")
            if batch.available_quantity < item.requested_quantity:
                raise ValueError(f"物资[{item.material_name}]可用库存不足")
            if batch.expiry_date and app.appointment_time:
                if batch.expiry_date < app.appointment_time.date():
                    raise ValueError(f"物资[{item.material_name}]批次已过期或预约时段不在有效期内")

            locked, lock_msg = lock_inventory(db, item.batch_id, item.requested_quantity)
            if not locked:
                raise ValueError(lock_msg)
            item.locked_quantity = item.requested_quantity
            item.is_locked = True

        db.commit()
        db.refresh(app)

    except ValueError as e:
        db.rollback()
        return error_response(code=400, message=str(e))
    except Exception as e:
        db.rollback()
        return error_response(code=500, message=f"更新借用申请失败：{str(e)}")

    result = orm_to_dict(app)
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == app.elderly_id).first()
    result["elderly_name"] = elderly.name if elderly else None
    work_order = db.query(WorkOrder).filter(WorkOrder.id == app.work_order_id).first()
    result["order_no"] = work_order.order_no if work_order else None
    result["items"] = orm_to_dict(app.items)

    return success_response(data=result, message="借用申请更新成功")


@router.delete("/applications/{borrow_id}", response_model=ApiResponse)
def delete_application(borrow_id: int, db: Session = Depends(get_db)):
    app = db.query(BorrowApplication).filter(BorrowApplication.id == borrow_id).first()
    if not app:
        return error_response(code=404, message="借用申请不存在")
    if app.status != BorrowStatus.PENDING:
        return error_response(code=400, message=f"当前状态为{app.status.value}，仅PENDING状态可删除")

    release_borrow_locks(db, borrow_id)

    if app.work_order_id:
        add_progress_record(
            db, app.work_order_id, ProgressType.IN_PROGRESS,
            operator_name="系统", operator_role="system",
            remark=f"删除借用申请：{app.borrow_no}"
        )

    db.delete(app)
    db.commit()

    return success_response(message="借用申请删除成功，库存已释放")


@router.post("/applications/{borrow_id}/approve", response_model=ApiResponse[BorrowApplicationResponse])
def approve_application(borrow_id: int, approve_data: BorrowApproveRequest, db: Session = Depends(get_db)):
    app = db.query(BorrowApplication).filter(BorrowApplication.id == borrow_id).first()
    if not app:
        return error_response(code=404, message="借用申请不存在")
    if app.status != BorrowStatus.PENDING:
        return error_response(code=400, message=f"当前状态为{app.status.value}，仅PENDING状态可审批")

    try:
        for item in app.items:
            if not item.is_locked or item.locked_quantity < item.approved_quantity:
                needed_qty = item.approved_quantity - item.locked_quantity
                if needed_qty > 0:
                    batch = db.query(InventoryBatch).filter(InventoryBatch.id == item.batch_id).first()
                    if not batch or batch.available_quantity < needed_qty:
                        raise ValueError(f"物资[{item.material_name}]库存不足，无法审批通过")
                    locked, lock_msg = lock_inventory(db, item.batch_id, needed_qty)
                    if not locked:
                        raise ValueError(f"物资[{item.material_name}]：{lock_msg}")
                    item.locked_quantity = item.approved_quantity
                    item.is_locked = True

        app.status = BorrowStatus.APPROVED
        app.approver_name = approve_data.approver_name
        app.approve_time = datetime.now()

        if app.work_order_id:
            add_progress_record(
                db, app.work_order_id, ProgressType.IN_PROGRESS,
                operator_name=approve_data.approver_name, operator_role="approver",
                remark=f"借用申请审批通过：{app.borrow_no}，{approve_data.remark or ''}"
            )

        db.commit()
        db.refresh(app)

    except ValueError as e:
        db.rollback()
        return error_response(code=400, message=str(e))
    except Exception as e:
        db.rollback()
        return error_response(code=500, message=f"审批失败：{str(e)}")

    result = orm_to_dict(app)
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == app.elderly_id).first()
    result["elderly_name"] = elderly.name if elderly else None
    work_order = db.query(WorkOrder).filter(WorkOrder.id == app.work_order_id).first()
    result["order_no"] = work_order.order_no if work_order else None
    result["items"] = orm_to_dict(app.items)

    return success_response(data=result, message="审批通过")


@router.post("/applications/{borrow_id}/reject", response_model=ApiResponse[BorrowApplicationResponse])
def reject_application(borrow_id: int, reject_data: BorrowRejectRequest, db: Session = Depends(get_db)):
    app = db.query(BorrowApplication).filter(BorrowApplication.id == borrow_id).first()
    if not app:
        return error_response(code=404, message="借用申请不存在")
    if app.status != BorrowStatus.PENDING:
        return error_response(code=400, message=f"当前状态为{app.status.value}，仅PENDING状态可驳回")

    release_borrow_locks(db, borrow_id)

    app.status = BorrowStatus.REJECTED
    app.approver_name = reject_data.approver_name
    app.approve_time = datetime.now()
    app.reject_reason = reject_data.reject_reason

    if app.work_order_id:
        add_progress_record(
            db, app.work_order_id, ProgressType.IN_PROGRESS,
            operator_name=reject_data.approver_name, operator_role="approver",
            remark=f"借用申请驳回：{app.borrow_no}，原因：{reject_data.reject_reason}"
        )

    db.commit()
    db.refresh(app)

    result = orm_to_dict(app)
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == app.elderly_id).first()
    result["elderly_name"] = elderly.name if elderly else None
    work_order = db.query(WorkOrder).filter(WorkOrder.id == app.work_order_id).first()
    result["order_no"] = work_order.order_no if work_order else None
    result["items"] = orm_to_dict(app.items)

    return success_response(data=result, message="已驳回")


@router.post("/applications/{borrow_id}/pickup", response_model=ApiResponse[BorrowApplicationResponse])
def pickup_application(borrow_id: int, pickup_data: BorrowPickupRequest, db: Session = Depends(get_db)):
    app = db.query(BorrowApplication).filter(BorrowApplication.id == borrow_id).first()
    if not app:
        return error_response(code=404, message="借用申请不存在")
    if app.status != BorrowStatus.APPROVED:
        return error_response(code=400, message=f"当前状态为{app.status.value}，仅APPROVED状态可领用")

    try:
        for item in app.items:
            if item.locked_quantity < item.approved_quantity:
                raise ValueError(f"物资[{item.material_name}]库存未完全锁定，无法领用")
            batch = db.query(InventoryBatch).filter(InventoryBatch.id == item.batch_id).first()
            if not batch or batch.locked_quantity < item.approved_quantity:
                raise ValueError(f"物资[{item.material_name}]锁定库存异常")
            batch.locked_quantity -= item.approved_quantity
            item.picked_quantity = item.approved_quantity
            item.locked_quantity = 0
            item.is_locked = False
        db.flush()

        app.status = BorrowStatus.PICKED_UP
        app.pickup_operator = pickup_data.pickup_operator
        app.actual_pickup_time = pickup_data.pickup_time or datetime.now()

        if app.work_order_id:
            add_progress_record(
                db, app.work_order_id, ProgressType.IN_PROGRESS,
                operator_name=pickup_data.pickup_operator, operator_role="warehouse",
                remark=f"物资领用确认：{app.borrow_no}，共{app.total_items}种{app.total_quantity}件"
            )

        db.commit()
        db.refresh(app)

    except ValueError as e:
        db.rollback()
        return error_response(code=400, message=str(e))
    except Exception as e:
        db.rollback()
        return error_response(code=500, message=f"领用确认失败：{str(e)}")

    result = orm_to_dict(app)
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == app.elderly_id).first()
    result["elderly_name"] = elderly.name if elderly else None
    work_order = db.query(WorkOrder).filter(WorkOrder.id == app.work_order_id).first()
    result["order_no"] = work_order.order_no if work_order else None
    result["items"] = orm_to_dict(app.items)

    return success_response(data=result, message="领用确认成功")


@router.post("/applications/{borrow_id}/cancel", response_model=ApiResponse[BorrowApplicationResponse])
def cancel_application(borrow_id: int, cancel_data: BorrowCancelRequest, db: Session = Depends(get_db)):
    app = db.query(BorrowApplication).filter(BorrowApplication.id == borrow_id).first()
    if not app:
        return error_response(code=404, message="借用申请不存在")
    if app.status not in [BorrowStatus.PENDING, BorrowStatus.APPROVED]:
        return error_response(code=400, message=f"当前状态为{app.status.value}，仅PENDING或APPROVED状态可取消")

    release_borrow_locks(db, borrow_id)

    app.status = BorrowStatus.CANCELLED
    app.cancel_reason = cancel_data.cancel_reason

    if app.work_order_id:
        add_progress_record(
            db, app.work_order_id, ProgressType.DISPATCH_CANCELLED,
            operator_name="系统", operator_role="system",
            remark=f"借用申请取消：{app.borrow_no}，原因：{cancel_data.cancel_reason}"
        )

    db.commit()
    db.refresh(app)

    result = orm_to_dict(app)
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == app.elderly_id).first()
    result["elderly_name"] = elderly.name if elderly else None
    work_order = db.query(WorkOrder).filter(WorkOrder.id == app.work_order_id).first()
    result["order_no"] = work_order.order_no if work_order else None
    result["items"] = orm_to_dict(app.items)

    return success_response(data=result, message="取消成功，库存已释放")
