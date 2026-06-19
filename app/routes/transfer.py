from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import Optional, List
from datetime import datetime, timedelta, date
import uuid

from app.database import get_db
from app.models import (
    MaterialTransfer, TransferItem, TransferStatus,
    InventoryBatch, Material, MaterialWarehouse, InventoryStatus, MaterialStatus,
    BorrowApplication, BorrowItem
)
from app.schemas import (
    MaterialTransferCreate, MaterialTransferUpdate, MaterialTransferResponse, MaterialTransferListResponse,
    TransferApproveRequest, TransferRejectRequest, TransferDepartRequest,
    TransferReceiveRequest, TransferCancelRequest
)
from app.utils import success_response, error_response, ApiResponse, orm_to_dict

router = APIRouter(prefix="/material/transfer", tags=["跨社区物资调拨"])


def generate_no(prefix: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    suffix = uuid.uuid4().hex[:6].upper()
    return f"{prefix}{timestamp}{suffix}"


def lock_transfer_inventory(db: Session, batch_id: int, quantity: int):
    batch = db.query(InventoryBatch).filter(InventoryBatch.id == batch_id).first()
    if not batch:
        return False
    if batch.available_quantity < quantity:
        return False
    batch.available_quantity -= quantity
    batch.locked_quantity += quantity
    return True


def release_transfer_inventory(db: Session, batch_id: int, quantity: int):
    batch = db.query(InventoryBatch).filter(InventoryBatch.id == batch_id).first()
    if not batch:
        return False
    release_qty = min(quantity, batch.locked_quantity)
    batch.locked_quantity -= release_qty
    batch.available_quantity += release_qty
    if batch.status == InventoryStatus.SCRAPPED and batch.available_quantity > 0:
        if batch.available_quantity <= batch.low_stock_threshold:
            batch.status = InventoryStatus.LOW_STOCK
        else:
            batch.status = InventoryStatus.NORMAL
    return True


def check_batch_in_pending_transfer(db: Session, batch_id: int, exclude_transfer_id: int = None) -> bool:
    query = db.query(TransferItem).join(MaterialTransfer).filter(
        TransferItem.batch_id == batch_id,
        MaterialTransfer.status.in_([TransferStatus.PENDING, TransferStatus.APPROVED, TransferStatus.IN_TRANSIT])
    )
    if exclude_transfer_id:
        query = query.filter(MaterialTransfer.id != exclude_transfer_id)
    existing = query.first()
    return existing is not None


def find_or_create_inbound_batch(db: Session, to_warehouse_id: int, source_batch: InventoryBatch) -> InventoryBatch:
    existing = db.query(InventoryBatch).filter(
        InventoryBatch.warehouse_id == to_warehouse_id,
        InventoryBatch.material_id == source_batch.material_id,
        InventoryBatch.expiry_date == source_batch.expiry_date
    ).first()
    if existing:
        return existing

    new_batch = InventoryBatch(
        batch_no=generate_no("IB"),
        material_id=source_batch.material_id,
        warehouse_id=to_warehouse_id,
        production_date=source_batch.production_date,
        expiry_date=source_batch.expiry_date,
        initial_quantity=0,
        available_quantity=0,
        locked_quantity=0,
        unit_price=source_batch.unit_price,
        supplier=source_batch.supplier,
        low_stock_threshold=source_batch.low_stock_threshold,
        status=InventoryStatus.NORMAL
    )
    db.add(new_batch)
    db.flush()
    return new_batch


def release_transfer_locks(db: Session, transfer_id: int):
    items = db.query(TransferItem).filter(TransferItem.transfer_id == transfer_id).all()
    for item in items:
        if item.locked_quantity > 0:
            release_transfer_inventory(db, item.batch_id, item.locked_quantity)
            item.locked_quantity = 0


@router.post("/requests", response_model=ApiResponse[MaterialTransferResponse])
def create_transfer_request(transfer_data: MaterialTransferCreate, db: Session = Depends(get_db)):
    from_warehouse = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == transfer_data.from_warehouse_id).first()
    if not from_warehouse:
        return error_response(code=404, message="调出仓库不存在")

    to_warehouse = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == transfer_data.to_warehouse_id).first()
    if not to_warehouse:
        return error_response(code=404, message="调入仓库不存在")

    if from_warehouse.community == to_warehouse.community:
        return error_response(code=400, message="调出和调入仓库必须属于不同社区")

    total_quantity = 0
    validated_items = []

    for item_data in transfer_data.items:
        material = db.query(Material).filter(Material.id == item_data.material_id).first()
        if not material:
            return error_response(code=404, message=f"物资不存在: material_id={item_data.material_id}")
        if material.status != MaterialStatus.ACTIVE:
            return error_response(code=400, message=f"物资{material.material_name}状态非ACTIVE，不可调拨")
        if not material.is_cross_community_transferable:
            return error_response(code=400, message=f"物资{material.material_name}不支持跨社区调拨")

        batch = db.query(InventoryBatch).filter(InventoryBatch.id == item_data.batch_id).first()
        if not batch:
            return error_response(code=404, message=f"库存批次不存在: batch_id={item_data.batch_id}")
        if batch.warehouse_id != transfer_data.from_warehouse_id:
            return error_response(code=400, message=f"批次{batch.batch_no}不属于调出仓库")
        if batch.status in [InventoryStatus.EXPIRED, InventoryStatus.DISABLED, InventoryStatus.SCRAPPED]:
            return error_response(code=400, message=f"批次{batch.batch_no}状态为{batch.status.value}，不可调拨")
        if batch.available_quantity < item_data.transfer_quantity:
            return error_response(code=400, message=f"批次{batch.batch_no}可用数量不足")

        if check_batch_in_pending_transfer(db, item_data.batch_id):
            return error_response(code=400, message=f"批次{batch.batch_no}已在其他未完成调拨中被占用")

        validated_items.append({
            "item_data": item_data,
            "material": material,
            "batch": batch
        })
        total_quantity += item_data.transfer_quantity

    transfer_no = generate_no("TF")
    transfer = MaterialTransfer(
        transfer_no=transfer_no,
        from_warehouse_id=transfer_data.from_warehouse_id,
        to_warehouse_id=transfer_data.to_warehouse_id,
        from_community=from_warehouse.community,
        to_community=to_warehouse.community,
        applicant_name=transfer_data.applicant_name,
        applicant_phone=transfer_data.applicant_phone,
        transporter_name=transfer_data.transporter_name,
        transporter_phone=transfer_data.transporter_phone,
        estimated_arrival_time=transfer_data.estimated_arrival_time,
        status=TransferStatus.PENDING,
        total_quantity=total_quantity,
        remark=transfer_data.remark
    )
    db.add(transfer)
    db.flush()

    for vi in validated_items:
        item_data = vi["item_data"]
        material = vi["material"]
        batch = vi["batch"]

        lock_transfer_inventory(db, item_data.batch_id, item_data.transfer_quantity)

        transfer_item = TransferItem(
            transfer_id=transfer.id,
            material_id=item_data.material_id,
            batch_id=item_data.batch_id,
            material_name=material.material_name,
            material_code=material.material_code,
            spec=material.spec,
            unit=material.unit,
            transfer_quantity=item_data.transfer_quantity,
            locked_quantity=item_data.transfer_quantity,
            received_quantity=0,
            unit_price=batch.unit_price,
            remark=item_data.remark
        )
        db.add(transfer_item)

    db.commit()
    db.refresh(transfer)

    result = orm_to_dict(transfer)
    result["from_warehouse_name"] = from_warehouse.warehouse_name
    result["to_warehouse_name"] = to_warehouse.warehouse_name
    result["items"] = orm_to_dict(transfer.items)

    return success_response(data=result, message="调拨申请创建成功")


@router.get("/requests", response_model=ApiResponse[MaterialTransferListResponse])
def list_transfer_requests(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    from_community: Optional[str] = Query(None, description="调出社区"),
    to_community: Optional[str] = Query(None, description="调入社区"),
    status: Optional[str] = Query(None, description="调拨状态"),
    material_id: Optional[int] = Query(None, description="物资ID"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    db: Session = Depends(get_db)
):
    query = db.query(MaterialTransfer)

    if from_community:
        query = query.filter(MaterialTransfer.from_community == from_community)
    if to_community:
        query = query.filter(MaterialTransfer.to_community == to_community)
    if status:
        try:
            query = query.filter(MaterialTransfer.status == TransferStatus(status))
        except ValueError:
            return error_response(code=400, message=f"无效的调拨状态: {status}")
    if material_id:
        query = query.join(TransferItem).filter(TransferItem.material_id == material_id)
    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        query = query.filter(MaterialTransfer.created_at >= start_dt)
    if end_date:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        query = query.filter(MaterialTransfer.created_at < end_dt)

    total = query.count()
    transfers = query.order_by(MaterialTransfer.id.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    items = []
    for t in transfers:
        t_dict = orm_to_dict(t)
        from_wh = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == t.from_warehouse_id).first()
        to_wh = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == t.to_warehouse_id).first()
        t_dict["from_warehouse_name"] = from_wh.warehouse_name if from_wh else ""
        t_dict["to_warehouse_name"] = to_wh.warehouse_name if to_wh else ""
        t_dict["items"] = orm_to_dict(t.items)
        items.append(t_dict)

    return success_response(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    })


@router.get("/requests/{transfer_id}", response_model=ApiResponse[MaterialTransferResponse])
def get_transfer_request(transfer_id: int, db: Session = Depends(get_db)):
    transfer = db.query(MaterialTransfer).filter(MaterialTransfer.id == transfer_id).first()
    if not transfer:
        return error_response(code=404, message="调拨申请不存在")

    result = orm_to_dict(transfer)
    from_wh = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == transfer.from_warehouse_id).first()
    to_wh = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == transfer.to_warehouse_id).first()
    result["from_warehouse_name"] = from_wh.warehouse_name if from_wh else ""
    result["to_warehouse_name"] = to_wh.warehouse_name if to_wh else ""
    result["items"] = orm_to_dict(transfer.items)

    return success_response(data=result)


@router.post("/requests/{transfer_id}/approve", response_model=ApiResponse[MaterialTransferResponse])
def approve_transfer(transfer_id: int, approve_data: TransferApproveRequest, db: Session = Depends(get_db)):
    transfer = db.query(MaterialTransfer).filter(MaterialTransfer.id == transfer_id).first()
    if not transfer:
        return error_response(code=404, message="调拨申请不存在")
    if transfer.status != TransferStatus.PENDING:
        return error_response(code=400, message=f"当前调拨状态为{transfer.status.value}，仅待审批状态可审批通过")

    transfer.status = TransferStatus.APPROVED
    transfer.approver_name = approve_data.approver_name
    transfer.approve_time = datetime.now()

    db.commit()
    db.refresh(transfer)

    result = orm_to_dict(transfer)
    from_wh = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == transfer.from_warehouse_id).first()
    to_wh = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == transfer.to_warehouse_id).first()
    result["from_warehouse_name"] = from_wh.warehouse_name if from_wh else ""
    result["to_warehouse_name"] = to_wh.warehouse_name if to_wh else ""
    result["items"] = orm_to_dict(transfer.items)

    return success_response(data=result, message="调拨审批通过")


@router.post("/requests/{transfer_id}/reject", response_model=ApiResponse[MaterialTransferResponse])
def reject_transfer(transfer_id: int, reject_data: TransferRejectRequest, db: Session = Depends(get_db)):
    transfer = db.query(MaterialTransfer).filter(MaterialTransfer.id == transfer_id).first()
    if not transfer:
        return error_response(code=404, message="调拨申请不存在")
    if transfer.status != TransferStatus.PENDING:
        return error_response(code=400, message=f"当前调拨状态为{transfer.status.value}，仅待审批状态可驳回")

    transfer.status = TransferStatus.REJECTED
    transfer.approver_name = reject_data.approver_name
    transfer.approve_time = datetime.now()
    transfer.reject_reason = reject_data.reject_reason

    release_transfer_locks(db, transfer_id)

    db.commit()
    db.refresh(transfer)

    result = orm_to_dict(transfer)
    from_wh = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == transfer.from_warehouse_id).first()
    to_wh = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == transfer.to_warehouse_id).first()
    result["from_warehouse_name"] = from_wh.warehouse_name if from_wh else ""
    result["to_warehouse_name"] = to_wh.warehouse_name if to_wh else ""
    result["items"] = orm_to_dict(transfer.items)

    return success_response(data=result, message="调拨已驳回")


@router.post("/requests/{transfer_id}/depart", response_model=ApiResponse[MaterialTransferResponse])
def depart_transfer(transfer_id: int, depart_data: TransferDepartRequest, db: Session = Depends(get_db)):
    transfer = db.query(MaterialTransfer).filter(MaterialTransfer.id == transfer_id).first()
    if not transfer:
        return error_response(code=404, message="调拨申请不存在")
    if transfer.status != TransferStatus.APPROVED:
        return error_response(code=400, message=f"当前调拨状态为{transfer.status.value}，仅已审批状态可出库发运")

    transfer.status = TransferStatus.IN_TRANSIT
    transfer.actual_departure_time = depart_data.actual_departure_time or datetime.now()
    transfer.transport_status = "in_transit"

    items = db.query(TransferItem).filter(TransferItem.transfer_id == transfer_id).all()
    for item in items:
        if item.locked_quantity > 0:
            batch = db.query(InventoryBatch).filter(InventoryBatch.id == item.batch_id).first()
            if batch:
                release_qty = min(item.locked_quantity, batch.locked_quantity)
                batch.locked_quantity -= release_qty
                item.locked_quantity = 0

    db.commit()
    db.refresh(transfer)

    result = orm_to_dict(transfer)
    from_wh = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == transfer.from_warehouse_id).first()
    to_wh = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == transfer.to_warehouse_id).first()
    result["from_warehouse_name"] = from_wh.warehouse_name if from_wh else ""
    result["to_warehouse_name"] = to_wh.warehouse_name if to_wh else ""
    result["items"] = orm_to_dict(transfer.items)

    return success_response(data=result, message="调拨已出库发运")


@router.post("/requests/{transfer_id}/receive", response_model=ApiResponse[MaterialTransferResponse])
def receive_transfer(transfer_id: int, receive_data: TransferReceiveRequest, db: Session = Depends(get_db)):
    transfer = db.query(MaterialTransfer).filter(MaterialTransfer.id == transfer_id).first()
    if not transfer:
        return error_response(code=404, message="调拨申请不存在")
    if transfer.status != TransferStatus.IN_TRANSIT:
        return error_response(code=400, message=f"当前调拨状态为{transfer.status.value}，仅运输中状态可入库确认")

    transfer.status = TransferStatus.RECEIVED
    transfer.receiver_name = receive_data.receiver_name
    transfer.receive_time = receive_data.receive_time or datetime.now()
    transfer.receive_remark = receive_data.receive_remark
    transfer.actual_arrival_time = transfer.receive_time

    items = db.query(TransferItem).filter(TransferItem.transfer_id == transfer_id).all()
    for item in items:
        source_batch = db.query(InventoryBatch).filter(InventoryBatch.id == item.batch_id).first()
        if not source_batch:
            continue

        inbound_batch = find_or_create_inbound_batch(db, transfer.to_warehouse_id, source_batch)
        inbound_batch.available_quantity += item.transfer_quantity
        inbound_batch.initial_quantity += item.transfer_quantity

        if inbound_batch.available_quantity <= inbound_batch.low_stock_threshold:
            inbound_batch.status = InventoryStatus.LOW_STOCK
        else:
            inbound_batch.status = InventoryStatus.NORMAL

        item.received_quantity = item.transfer_quantity

    db.commit()
    db.refresh(transfer)

    result = orm_to_dict(transfer)
    from_wh = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == transfer.from_warehouse_id).first()
    to_wh = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == transfer.to_warehouse_id).first()
    result["from_warehouse_name"] = from_wh.warehouse_name if from_wh else ""
    result["to_warehouse_name"] = to_wh.warehouse_name if to_wh else ""
    result["items"] = orm_to_dict(transfer.items)

    return success_response(data=result, message="调拨入库确认完成")


@router.post("/requests/{transfer_id}/cancel", response_model=ApiResponse[MaterialTransferResponse])
def cancel_transfer(transfer_id: int, cancel_data: TransferCancelRequest, db: Session = Depends(get_db)):
    transfer = db.query(MaterialTransfer).filter(MaterialTransfer.id == transfer_id).first()
    if not transfer:
        return error_response(code=404, message="调拨申请不存在")
    if transfer.status not in [TransferStatus.PENDING, TransferStatus.APPROVED]:
        return error_response(code=400, message=f"当前调拨状态为{transfer.status.value}，仅待审批或已审批状态可取消")

    transfer.status = TransferStatus.CANCELLED
    transfer.reject_reason = cancel_data.cancel_reason

    release_transfer_locks(db, transfer_id)

    db.commit()
    db.refresh(transfer)

    result = orm_to_dict(transfer)
    from_wh = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == transfer.from_warehouse_id).first()
    to_wh = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == transfer.to_warehouse_id).first()
    result["from_warehouse_name"] = from_wh.warehouse_name if from_wh else ""
    result["to_warehouse_name"] = to_wh.warehouse_name if to_wh else ""
    result["items"] = orm_to_dict(transfer.items)

    return success_response(data=result, message="调拨已取消")


@router.put("/requests/{transfer_id}", response_model=ApiResponse[MaterialTransferResponse])
def update_transfer(transfer_id: int, transfer_update: MaterialTransferUpdate, db: Session = Depends(get_db)):
    transfer = db.query(MaterialTransfer).filter(MaterialTransfer.id == transfer_id).first()
    if not transfer:
        return error_response(code=404, message="调拨申请不存在")
    if transfer.status != TransferStatus.PENDING:
        return error_response(code=400, message=f"当前调拨状态为{transfer.status.value}，仅待审批状态可更新")

    update_data = transfer_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(transfer, key, value)

    db.commit()
    db.refresh(transfer)

    result = orm_to_dict(transfer)
    from_wh = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == transfer.from_warehouse_id).first()
    to_wh = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == transfer.to_warehouse_id).first()
    result["from_warehouse_name"] = from_wh.warehouse_name if from_wh else ""
    result["to_warehouse_name"] = to_wh.warehouse_name if to_wh else ""
    result["items"] = orm_to_dict(transfer.items)

    return success_response(data=result, message="调拨更新成功")
