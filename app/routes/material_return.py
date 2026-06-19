from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timedelta
import uuid

from app.database import get_db
from app.models import (
    MaterialReturn, ReturnItem, BorrowApplication, BorrowItem, BorrowStatus,
    MaterialScrap, ScrapReason, ReturnCondition,
    InventoryBatch, InventoryStatus, Material, MaterialWarehouse,
    WorkOrder, ProgressRecord, ProgressType, OrderStatus,
    ElderlyProfile
)
from app.schemas import (
    MaterialReturnCreate, MaterialReturnResponse, MaterialReturnListResponse,
    MaterialScrapCreate, MaterialScrapResponse, MaterialScrapListResponse
)
from app.utils import success_response, error_response, ApiResponse, orm_to_dict

router = APIRouter(prefix="/material/return", tags=["物资归还与报废"])


def generate_no(prefix: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    suffix = uuid.uuid4().hex[:6].upper()
    return f"{prefix}{timestamp}{suffix}"


def add_progress_record(db: Session, work_order_id: int, progress_type: ProgressType,
                        operator: str = None, role: str = None, remark: str = None):
    record = ProgressRecord(
        work_order_id=work_order_id,
        progress_type=progress_type,
        operator_name=operator,
        operator_role=role,
        remark=remark
    )
    db.add(record)


def process_return_stock(db: Session, batch_id: int, good_qty: int, worn_qty: int,
                         damaged_qty: int, lost_qty: int):
    batch = db.query(InventoryBatch).filter(InventoryBatch.id == batch_id).first()
    if not batch:
        return
    reusable_qty = good_qty + worn_qty
    batch.available_quantity += reusable_qty
    if damaged_qty > 0 or lost_qty > 0:
        material = db.query(Material).filter(Material.id == batch.material_id).first()
        if material and not material.is_reusable:
            pass
        else:
            batch.available_quantity -= (damaged_qty + lost_qty)
            if batch.available_quantity <= 0 and batch.locked_quantity <= 0:
                batch.status = InventoryStatus.SCRAPPED
                batch.available_quantity = 0


def create_scrap_from_return(db: Session, batch_id: int, material_id: int, warehouse_id: int,
                             qty: int, reason: ScrapReason, detail: str, related_ids: dict):
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        return None
    scrap_no = generate_no("SC")
    scrap = MaterialScrap(
        scrap_no=scrap_no,
        material_id=material_id,
        batch_id=batch_id,
        warehouse_id=warehouse_id,
        material_name=material.material_name,
        material_code=material.material_code,
        scrap_quantity=qty,
        unit=material.unit,
        reason=reason,
        reason_detail=detail,
        related_borrow_id=related_ids.get("borrow_id"),
        related_return_id=related_ids.get("return_id"),
        related_order_id=related_ids.get("order_id")
    )
    db.add(scrap)
    db.flush()
    return scrap


def update_borrow_status_after_return(db: Session, borrow_id: int):
    borrow = db.query(BorrowApplication).filter(BorrowApplication.id == borrow_id).first()
    if not borrow:
        return
    items = db.query(BorrowItem).filter(BorrowItem.borrow_id == borrow_id).all()
    all_returned = True
    any_returned = False
    for item in items:
        if item.picked_quantity > 0 and item.returned_quantity < item.picked_quantity:
            all_returned = False
        if item.returned_quantity > 0:
            any_returned = True
    if all_returned and any_returned:
        borrow.status = BorrowStatus.RETURNED
    elif any_returned:
        borrow.status = BorrowStatus.PARTIAL_RETURNED


def check_and_generate_follow_up(db: Session, work_order_id: int, borrow_id: int, items_with_issues: list):
    if not work_order_id or not items_with_issues:
        return
    issues_desc = []
    for item in items_with_issues:
        if item.get("damaged_qty", 0) > 0:
            issues_desc.append(f"{item['material_name']} 损坏{item['damaged_qty']}件")
        if item.get("lost_qty", 0) > 0:
            issues_desc.append(f"{item['material_name']} 丢失{item['lost_qty']}件")
    if issues_desc:
        remark = f"物资归还发现问题：{'; '.join(issues_desc)}，请跟进处理"
        add_progress_record(
            db, work_order_id, ProgressType.FOLLOW_UP,
            operator="系统", role="system", remark=remark
        )


@router.post("/records", response_model=ApiResponse[MaterialReturnResponse])
def create_return_record(return_data: MaterialReturnCreate, db: Session = Depends(get_db)):
    borrow = db.query(BorrowApplication).filter(BorrowApplication.id == return_data.borrow_id).first()
    if not borrow:
        return error_response(code=404, message="借用申请不存在")
    if borrow.status not in [BorrowStatus.PICKED_UP, BorrowStatus.PARTIAL_RETURNED]:
        return error_response(code=400, message=f"当前借用状态为{borrow.status.value}，不可归还")

    return_no = generate_no("RT")
    work_order_id = return_data.work_order_id or borrow.work_order_id
    return_record = MaterialReturn(
        return_no=return_no,
        borrow_id=return_data.borrow_id,
        work_order_id=work_order_id,
        returner_name=return_data.returner_name,
        returner_phone=return_data.returner_phone,
        inspector_name=return_data.inspector_name,
        inspection_time=return_data.inspection_time or datetime.now(),
        overall_condition=return_data.overall_condition,
        remark=return_data.remark
    )
    db.add(return_record)
    db.flush()

    items_with_issues = []

    for item_data in return_data.items:
        borrow_item = db.query(BorrowItem).filter(BorrowItem.id == item_data.borrow_item_id).first()
        if not borrow_item:
            db.rollback()
            return error_response(code=404, message=f"借用明细不存在: borrow_item_id={item_data.borrow_item_id}")
        if borrow_item.borrow_id != return_data.borrow_id:
            db.rollback()
            return error_response(code=400, message="借用明细不属于该借用申请")

        remaining = borrow_item.picked_quantity - borrow_item.returned_quantity
        if item_data.returned_quantity > remaining:
            db.rollback()
            return error_response(code=400, message=f"{borrow_item.material_name} 归还数量超过未归还数量")

        total_check = item_data.good_quantity + item_data.worn_quantity + item_data.damaged_quantity + item_data.lost_quantity
        if total_check != item_data.returned_quantity:
            db.rollback()
            return error_response(code=400, message=f"{borrow_item.material_name} 各状态数量之和不等于归还数量")

        batch = db.query(InventoryBatch).filter(InventoryBatch.id == borrow_item.batch_id).first()
        if not batch:
            db.rollback()
            return error_response(code=404, message=f"库存批次不存在: batch_id={borrow_item.batch_id}")

        process_return_stock(
            db, borrow_item.batch_id,
            item_data.good_quantity, item_data.worn_quantity,
            item_data.damaged_quantity, item_data.lost_quantity
        )

        borrow_item.returned_quantity += item_data.returned_quantity

        material = db.query(Material).filter(Material.id == borrow_item.material_id).first()
        return_item = ReturnItem(
            return_id=return_record.id,
            borrow_item_id=item_data.borrow_item_id,
            material_id=borrow_item.material_id,
            batch_id=borrow_item.batch_id,
            material_name=borrow_item.material_name,
            material_code=borrow_item.material_code,
            spec=borrow_item.spec,
            unit=borrow_item.unit,
            returned_quantity=item_data.returned_quantity,
            good_quantity=item_data.good_quantity,
            worn_quantity=item_data.worn_quantity,
            damaged_quantity=item_data.damaged_quantity,
            lost_quantity=item_data.lost_quantity,
            condition=item_data.condition,
            damage_reason=item_data.damage_reason,
            remark=item_data.remark
        )
        db.add(return_item)

        if item_data.damaged_quantity > 0 or item_data.lost_quantity > 0:
            items_with_issues.append({
                "material_name": borrow_item.material_name,
                "damaged_qty": item_data.damaged_quantity,
                "lost_qty": item_data.lost_quantity
            })

            if item_data.damaged_quantity > 0:
                create_scrap_from_return(
                    db, borrow_item.batch_id, borrow_item.material_id, batch.warehouse_id,
                    item_data.damaged_quantity, ScrapReason.DAMAGE,
                    item_data.damage_reason or "归还时发现损坏",
                    {"borrow_id": return_data.borrow_id, "return_id": return_record.id, "order_id": work_order_id}
                )

            if item_data.lost_quantity > 0:
                create_scrap_from_return(
                    db, borrow_item.batch_id, borrow_item.material_id, batch.warehouse_id,
                    item_data.lost_quantity, ScrapReason.LOST,
                    "归还时确认丢失",
                    {"borrow_id": return_data.borrow_id, "return_id": return_record.id, "order_id": work_order_id}
                )

    update_borrow_status_after_return(db, return_data.borrow_id)

    if work_order_id:
        add_progress_record(
            db, work_order_id, ProgressType.COMPLETED,
            operator=return_data.inspector_name, role="inspector",
            remark=f"物资归还验收完成，归还单号：{return_no}"
        )

    check_and_generate_follow_up(db, work_order_id, return_data.borrow_id, items_with_issues)

    db.commit()
    db.refresh(return_record)

    result = orm_to_dict(return_record)
    result["borrow_no"] = borrow.borrow_no
    result["items"] = orm_to_dict(return_record.items)

    return success_response(data=result, message="归还验收记录创建成功")


@router.get("/records", response_model=ApiResponse[MaterialReturnListResponse])
def list_return_records(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    community: Optional[str] = Query(None, description="社区筛选"),
    borrow_id: Optional[int] = Query(None, description="借用申请ID"),
    work_order_id: Optional[int] = Query(None, description="工单ID"),
    inspector_name: Optional[str] = Query(None, description="验收人姓名"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    db: Session = Depends(get_db)
):
    query = db.query(MaterialReturn)

    if borrow_id:
        query = query.filter(MaterialReturn.borrow_id == borrow_id)
    if work_order_id:
        query = query.filter(MaterialReturn.work_order_id == work_order_id)
    if inspector_name:
        query = query.filter(MaterialReturn.inspector_name.like(f"%{inspector_name}%"))
    if community:
        query = query.join(BorrowApplication).filter(BorrowApplication.community == community)
    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        query = query.filter(MaterialReturn.created_at >= start_dt)
    if end_date:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        query = query.filter(MaterialReturn.created_at < end_dt)

    total = query.count()
    records = query.order_by(MaterialReturn.id.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    items = []
    for r in records:
        r_dict = orm_to_dict(r)
        borrow = db.query(BorrowApplication).filter(BorrowApplication.id == r.borrow_id).first()
        r_dict["borrow_no"] = borrow.borrow_no if borrow else ""
        r_dict["items"] = orm_to_dict(r.items)
        items.append(r_dict)

    return success_response(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    })


@router.get("/records/{return_id}", response_model=ApiResponse[MaterialReturnResponse])
def get_return_record(return_id: int, db: Session = Depends(get_db)):
    return_record = db.query(MaterialReturn).filter(MaterialReturn.id == return_id).first()
    if not return_record:
        return error_response(code=404, message="归还记录不存在")

    result = orm_to_dict(return_record)
    borrow = db.query(BorrowApplication).filter(BorrowApplication.id == return_record.borrow_id).first()
    result["borrow_no"] = borrow.borrow_no if borrow else ""
    result["items"] = orm_to_dict(return_record.items)

    return success_response(data=result)


@router.post("/scraps", response_model=ApiResponse[MaterialScrapResponse])
def create_scrap(scrap_data: MaterialScrapCreate, db: Session = Depends(get_db)):
    batch = db.query(InventoryBatch).filter(InventoryBatch.id == scrap_data.batch_id).first()
    if not batch:
        return error_response(code=404, message="库存批次不存在")
    if batch.warehouse_id != scrap_data.warehouse_id:
        return error_response(code=400, message="批次不属于该仓库")
    if batch.available_quantity < scrap_data.scrap_quantity:
        return error_response(code=400, message="批次可用数量不足")

    material = db.query(Material).filter(Material.id == scrap_data.material_id).first()
    if not material:
        return error_response(code=404, message="物资不存在")

    batch.available_quantity -= scrap_data.scrap_quantity
    if batch.available_quantity <= 0 and batch.locked_quantity <= 0:
        batch.status = InventoryStatus.SCRAPPED
        batch.available_quantity = 0

    scrap_no = generate_no("SC")
    scrap = MaterialScrap(
        scrap_no=scrap_no,
        material_id=scrap_data.material_id,
        batch_id=scrap_data.batch_id,
        warehouse_id=scrap_data.warehouse_id,
        material_name=material.material_name,
        material_code=material.material_code,
        scrap_quantity=scrap_data.scrap_quantity,
        unit=material.unit,
        reason=scrap_data.reason,
        reason_detail=scrap_data.reason_detail,
        applicant_name=scrap_data.applicant_name,
        approver_name=scrap_data.approver_name,
        approve_time=datetime.now() if scrap_data.approver_name else None,
        related_borrow_id=scrap_data.related_borrow_id,
        related_return_id=scrap_data.related_return_id,
        related_order_id=scrap_data.related_order_id,
        remark=scrap_data.remark
    )
    db.add(scrap)
    db.commit()
    db.refresh(scrap)

    return success_response(data=scrap, message="报废记录创建成功")


@router.get("/scraps", response_model=ApiResponse[MaterialScrapListResponse])
def list_scraps(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    community: Optional[str] = Query(None, description="社区筛选"),
    material_id: Optional[int] = Query(None, description="物资ID"),
    reason: Optional[str] = Query(None, description="报废原因"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    db: Session = Depends(get_db)
):
    query = db.query(MaterialScrap)

    if material_id:
        query = query.filter(MaterialScrap.material_id == material_id)
    if reason:
        try:
            query = query.filter(MaterialScrap.reason == ScrapReason(reason))
        except ValueError:
            return error_response(code=400, message=f"无效的报废原因: {reason}")
    if community:
        query = query.join(MaterialWarehouse).filter(MaterialWarehouse.community == community)
    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        query = query.filter(MaterialScrap.created_at >= start_dt)
    if end_date:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        query = query.filter(MaterialScrap.created_at < end_dt)

    total = query.count()
    scraps = query.order_by(MaterialScrap.id.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return success_response(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": orm_to_dict(scraps)
    })


@router.get("/scraps/{scrap_id}", response_model=ApiResponse[MaterialScrapResponse])
def get_scrap(scrap_id: int, db: Session = Depends(get_db)):
    scrap = db.query(MaterialScrap).filter(MaterialScrap.id == scrap_id).first()
    if not scrap:
        return error_response(code=404, message="报废记录不存在")
    return success_response(data=scrap)
