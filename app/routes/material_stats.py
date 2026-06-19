from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, case
from typing import Optional, List
from datetime import datetime, timedelta, date
from collections import defaultdict

from app.database import get_db
from app.models import (
    MaterialWarehouse, Material, ServiceTypeMaterial, InventoryBatch,
    BorrowApplication, BorrowItem, MaterialReturn, ReturnItem, MaterialScrap, MaterialTransfer, TransferItem,
    WarehouseStatus, MaterialCategory, MaterialStatus, InventoryStatus,
    BorrowStatus, ReturnCondition, ScrapReason, TransferStatus, ServiceType,
    ElderlyProfile, WorkOrder, OrderStatus
)
from app.schemas import (
    InventoryStatsFilter, MaterialStatisticsResponse,
    CommunityInventoryItem, LowStockWarningItem, ExpiringMaterialItem,
    MaterialTurnoverItem, OverdueBorrowItem, ScrapRateRankingItem,
    ServiceTypeMaterialConsumptionItem, ElderlyUnreturnedItem,
    InventoryGapPredictionItem
)
from app.utils import success_response, error_response, ApiResponse, orm_to_dict

router = APIRouter(prefix="/material/stats", tags=["物资统计报表"])


def _determine_inventory_status(batch: InventoryBatch, today: date) -> InventoryStatus:
    if batch.expiry_date and batch.expiry_date < today:
        return InventoryStatus.EXPIRED
    if batch.expiry_date and (batch.expiry_date - today).days <= 30 and batch.available_quantity > 0:
        return InventoryStatus.EXPIRING
    if batch.available_quantity <= batch.low_stock_threshold:
        return InventoryStatus.LOW_STOCK
    return InventoryStatus.NORMAL


@router.post("/dashboard", response_model=ApiResponse[MaterialStatisticsResponse])
def get_material_dashboard(filters: InventoryStatsFilter, db: Session = Depends(get_db)):
    today = date.today()
    now = datetime.now()
    expiring_days = filters.expiring_days or 30

    start_dt = None
    end_dt = None
    if filters.start_date:
        start_dt = datetime.strptime(filters.start_date, "%Y-%m-%d")
    if filters.end_date:
        end_dt = datetime.strptime(filters.end_date, "%Y-%m-%d") + timedelta(days=1)

    summary = {}

    summary["total_warehouses"] = db.query(func.count(MaterialWarehouse.id)).filter(
        MaterialWarehouse.status == WarehouseStatus.ACTIVE
    ).scalar() or 0

    summary["total_materials"] = db.query(func.count(Material.id)).filter(
        Material.status == MaterialStatus.ACTIVE
    ).scalar() or 0

    inventory_query = db.query(
        func.sum(InventoryBatch.initial_quantity),
        func.sum(InventoryBatch.available_quantity),
        func.sum(InventoryBatch.locked_quantity)
    ).filter(InventoryBatch.status.notin_([InventoryStatus.DISABLED, InventoryStatus.SCRAPPED]))
    if filters.warehouse_id:
        inventory_query = inventory_query.filter(InventoryBatch.warehouse_id == filters.warehouse_id)
    if filters.material_id:
        inventory_query = inventory_query.filter(InventoryBatch.material_id == filters.material_id)
    if filters.material_category:
        inventory_query = inventory_query.join(Material).filter(Material.category == filters.material_category)

    total_inv = inventory_query.first()
    summary["total_inventory_quantity"] = total_inv[0] or 0
    summary["total_available_quantity"] = total_inv[1] or 0
    summary["total_locked_quantity"] = total_inv[2] or 0

    low_stock_query = db.query(InventoryBatch).filter(
        InventoryBatch.available_quantity <= InventoryBatch.low_stock_threshold,
        InventoryBatch.status.notin_([InventoryStatus.DISABLED, InventoryStatus.SCRAPPED])
    )
    if filters.community:
        low_stock_query = low_stock_query.join(MaterialWarehouse).filter(MaterialWarehouse.community == filters.community)
    if filters.material_id:
        low_stock_query = low_stock_query.filter(InventoryBatch.material_id == filters.material_id)
    low_stock_material_ids = set()
    for batch in low_stock_query.all():
        low_stock_material_ids.add(batch.material_id)
    summary["low_stock_count"] = len(low_stock_material_ids)

    expiring_cutoff = today + timedelta(days=expiring_days)
    expiring_query = db.query(InventoryBatch).filter(
        InventoryBatch.expiry_date.isnot(None),
        InventoryBatch.expiry_date <= expiring_cutoff,
        InventoryBatch.expiry_date > today,
        InventoryBatch.available_quantity > 0,
        InventoryBatch.status != InventoryStatus.EXPIRED
    )
    if filters.community:
        expiring_query = expiring_query.join(MaterialWarehouse).filter(MaterialWarehouse.community == filters.community)
    summary["expiring_count"] = expiring_query.count()

    expired_query = db.query(InventoryBatch).filter(
        InventoryBatch.expiry_date.isnot(None),
        InventoryBatch.expiry_date < today,
        InventoryBatch.status == InventoryStatus.EXPIRED
    )
    if filters.community:
        expired_query = expired_query.join(MaterialWarehouse).filter(MaterialWarehouse.community == filters.community)
    summary["expired_count"] = expired_query.count()

    pending_borrow_query = db.query(BorrowApplication).filter(
        BorrowApplication.status == BorrowStatus.PENDING
    )
    if filters.community:
        pending_borrow_query = pending_borrow_query.filter(BorrowApplication.community == filters.community)
    summary["pending_borrow_count"] = pending_borrow_query.count()

    overdue_borrow_query = db.query(BorrowApplication).filter(
        BorrowApplication.status.in_([BorrowStatus.PICKED_UP, BorrowStatus.PARTIAL_RETURNED]),
        BorrowApplication.expected_return_time < now
    )
    if filters.community:
        overdue_borrow_query = overdue_borrow_query.filter(BorrowApplication.community == filters.community)
    summary["overdue_borrow_count"] = overdue_borrow_query.count()

    pending_transfer_query = db.query(MaterialTransfer).filter(
        MaterialTransfer.status == TransferStatus.PENDING
    )
    if filters.community:
        pending_transfer_query = pending_transfer_query.filter(
            or_(
                MaterialTransfer.from_community == filters.community,
                MaterialTransfer.to_community == filters.community
            )
        )
    summary["pending_transfer_count"] = pending_transfer_query.count()

    thirty_days_ago = now - timedelta(days=30)
    scrap_30_query = db.query(func.sum(MaterialScrap.scrap_quantity)).filter(
        MaterialScrap.created_at >= thirty_days_ago
    )
    if start_dt:
        scrap_30_query = scrap_30_query.filter(MaterialScrap.created_at >= start_dt)
    if end_dt:
        scrap_30_query = scrap_30_query.filter(MaterialScrap.created_at < end_dt)
    summary["total_scrap_quantity_30days"] = scrap_30_query.scalar() or 0

    borrow_30_query = db.query(func.sum(BorrowItem.picked_quantity)).filter(
        BorrowItem.picked_quantity > 0
    ).join(BorrowApplication).filter(
        BorrowApplication.actual_pickup_time >= thirty_days_ago
    )
    if filters.community:
        borrow_30_query = borrow_30_query.filter(BorrowApplication.community == filters.community)
    if start_dt:
        borrow_30_query = borrow_30_query.filter(BorrowApplication.actual_pickup_time >= start_dt)
    if end_dt:
        borrow_30_query = borrow_30_query.filter(BorrowApplication.actual_pickup_time < end_dt)
    summary["total_borrow_quantity_30days"] = borrow_30_query.scalar() or 0

    return_30_query = db.query(func.sum(ReturnItem.returned_quantity)).filter(
        ReturnItem.returned_quantity > 0
    ).join(MaterialReturn).filter(
        MaterialReturn.inspection_time >= thirty_days_ago
    )
    if start_dt:
        return_30_query = return_30_query.filter(MaterialReturn.inspection_time >= start_dt)
    if end_dt:
        return_30_query = return_30_query.filter(MaterialReturn.inspection_time < end_dt)
    summary["total_return_quantity_30days"] = return_30_query.scalar() or 0

    community_inventory = []
    ci_query = db.query(
        MaterialWarehouse.community,
        MaterialWarehouse.id.label("warehouse_id"),
        MaterialWarehouse.warehouse_name,
        Material.id.label("material_id"),
        Material.material_code,
        Material.material_name,
        Material.category,
        Material.spec,
        Material.unit,
        InventoryBatch.low_stock_threshold,
        func.sum(InventoryBatch.initial_quantity).label("total_qty"),
        func.sum(InventoryBatch.available_quantity).label("available_qty"),
        func.sum(InventoryBatch.locked_quantity).label("locked_qty"),
        func.min(InventoryBatch.expiry_date).label("min_expiry")
    ).select_from(InventoryBatch).join(
        MaterialWarehouse, InventoryBatch.warehouse_id == MaterialWarehouse.id
    ).join(
        Material, InventoryBatch.material_id == Material.id
    ).filter(
        InventoryBatch.status.notin_([InventoryStatus.DISABLED, InventoryStatus.SCRAPPED])
    ).group_by(
        MaterialWarehouse.community,
        MaterialWarehouse.id,
        MaterialWarehouse.warehouse_name,
        Material.id,
        Material.material_code,
        Material.material_name,
        Material.category,
        Material.spec,
        Material.unit,
        InventoryBatch.low_stock_threshold
    )
    if filters.community:
        ci_query = ci_query.filter(MaterialWarehouse.community == filters.community)
    if filters.material_category:
        ci_query = ci_query.filter(Material.category == filters.material_category)
    if filters.material_id:
        ci_query = ci_query.filter(Material.id == filters.material_id)
    if filters.warehouse_id:
        ci_query = ci_query.filter(MaterialWarehouse.id == filters.warehouse_id)

    ci_results = ci_query.all()
    for row in ci_results:
        is_low = (row.available_qty or 0) <= (row.low_stock_threshold or 0)
        status = InventoryStatus.NORMAL
        if row.min_expiry and row.min_expiry < today:
            status = InventoryStatus.EXPIRED
        elif row.min_expiry and (row.min_expiry - today).days <= expiring_days and (row.available_qty or 0) > 0:
            status = InventoryStatus.EXPIRING
        elif is_low:
            status = InventoryStatus.LOW_STOCK

        if filters.status and status != filters.status:
            continue

        community_inventory.append(CommunityInventoryItem(
            community=row.community,
            warehouse_id=row.warehouse_id,
            warehouse_name=row.warehouse_name,
            material_id=row.material_id,
            material_code=row.material_code,
            material_name=row.material_name,
            category=row.category,
            spec=row.spec,
            unit=row.unit,
            total_quantity=row.total_qty or 0,
            available_quantity=row.available_qty or 0,
            locked_quantity=row.locked_qty or 0,
            low_stock_threshold=row.low_stock_threshold or 0,
            is_low_stock=is_low,
            expiry_date=row.min_expiry,
            status=status
        ))

    low_stock_warnings = []
    ls_query = db.query(
        MaterialWarehouse.community,
        MaterialWarehouse.warehouse_name,
        Material.id.label("material_id"),
        Material.material_code,
        Material.material_name,
        Material.spec,
        Material.unit,
        InventoryBatch.low_stock_threshold,
        func.sum(InventoryBatch.available_quantity).label("available_qty")
    ).select_from(InventoryBatch).join(
        MaterialWarehouse, InventoryBatch.warehouse_id == MaterialWarehouse.id
    ).join(
        Material, InventoryBatch.material_id == Material.id
    ).filter(
        InventoryBatch.available_quantity <= InventoryBatch.low_stock_threshold,
        InventoryBatch.status.notin_([InventoryStatus.DISABLED, InventoryStatus.SCRAPPED])
    ).group_by(
        MaterialWarehouse.community,
        MaterialWarehouse.warehouse_name,
        Material.id,
        Material.material_code,
        Material.material_name,
        Material.spec,
        Material.unit,
        InventoryBatch.low_stock_threshold
    )
    if filters.community:
        ls_query = ls_query.filter(MaterialWarehouse.community == filters.community)
    if filters.material_id:
        ls_query = ls_query.filter(Material.id == filters.material_id)

    ls_results = ls_query.all()
    for row in ls_results:
        available = row.available_qty or 0
        threshold = row.low_stock_threshold or 0
        gap = max(0, threshold - available)
        suggested = max(threshold * 2 - available, threshold)
        low_stock_warnings.append(LowStockWarningItem(
            community=row.community,
            warehouse_name=row.warehouse_name,
            material_id=row.material_id,
            material_code=row.material_code,
            material_name=row.material_name,
            spec=row.spec,
            unit=row.unit,
            available_quantity=available,
            low_stock_threshold=threshold,
            gap=gap,
            suggested_replenish=suggested
        ))

    expiring_materials = []
    em_query = db.query(
        MaterialWarehouse.community,
        MaterialWarehouse.warehouse_name,
        InventoryBatch.id.label("batch_id"),
        InventoryBatch.batch_no,
        Material.id.label("material_id"),
        Material.material_code,
        Material.material_name,
        Material.spec,
        Material.unit,
        InventoryBatch.available_quantity,
        InventoryBatch.expiry_date
    ).select_from(InventoryBatch).join(
        MaterialWarehouse, InventoryBatch.warehouse_id == MaterialWarehouse.id
    ).join(
        Material, InventoryBatch.material_id == Material.id
    ).filter(
        InventoryBatch.expiry_date.isnot(None),
        InventoryBatch.expiry_date <= expiring_cutoff,
        InventoryBatch.available_quantity > 0,
        InventoryBatch.status != InventoryStatus.EXPIRED
    )
    if filters.community:
        em_query = em_query.filter(MaterialWarehouse.community == filters.community)
    if filters.material_id:
        em_query = em_query.filter(Material.id == filters.material_id)

    em_results = em_query.all()
    em_list = []
    for row in em_results:
        days_to_expire = (row.expiry_date - today).days if row.expiry_date else 0
        em_list.append({
            "row": row,
            "days_to_expire": days_to_expire
        })
    em_list.sort(key=lambda x: x["days_to_expire"])
    for item in em_list:
        row = item["row"]
        expiring_materials.append(ExpiringMaterialItem(
            community=row.community,
            warehouse_name=row.warehouse_name,
            batch_id=row.batch_id,
            batch_no=row.batch_no,
            material_id=row.material_id,
            material_code=row.material_code,
            material_name=row.material_name,
            spec=row.spec,
            unit=row.unit,
            available_quantity=row.available_quantity or 0,
            expiry_date=row.expiry_date,
            days_to_expire=item["days_to_expire"]
        ))

    material_turnover = []
    ninety_days_ago = now - timedelta(days=90)
    mt_borrow_query = db.query(
        BorrowItem.material_id,
        Material.material_code,
        Material.material_name,
        Material.category,
        Material.unit,
        func.count(BorrowApplication.id).label("borrow_cnt"),
        func.sum(BorrowItem.picked_quantity).label("borrow_qty")
    ).select_from(BorrowItem).join(
        BorrowApplication, BorrowItem.borrow_id == BorrowApplication.id
    ).join(
        Material, BorrowItem.material_id == Material.id
    ).filter(
        BorrowApplication.actual_pickup_time >= ninety_days_ago,
        BorrowItem.picked_quantity > 0
    ).group_by(
        BorrowItem.material_id,
        Material.material_code,
        Material.material_name,
        Material.category,
        Material.unit
    )
    if start_dt:
        mt_borrow_query = mt_borrow_query.filter(BorrowApplication.actual_pickup_time >= start_dt)
    if end_dt:
        mt_borrow_query = mt_borrow_query.filter(BorrowApplication.actual_pickup_time < end_dt)

    mt_borrow_map = {}
    for row in mt_borrow_query.all():
        mt_borrow_map[row.material_id] = {
            "material_id": row.material_id,
            "material_code": row.material_code,
            "material_name": row.material_name,
            "category": row.category,
            "unit": row.unit,
            "borrow_count": row.borrow_cnt or 0,
            "borrow_quantity": row.borrow_qty or 0
        }

    mt_return_query = db.query(
        ReturnItem.material_id,
        func.sum(ReturnItem.returned_quantity).label("return_qty")
    ).join(MaterialReturn).filter(
        MaterialReturn.inspection_time >= ninety_days_ago,
        ReturnItem.returned_quantity > 0
    ).group_by(ReturnItem.material_id)
    if start_dt:
        mt_return_query = mt_return_query.filter(MaterialReturn.inspection_time >= start_dt)
    if end_dt:
        mt_return_query = mt_return_query.filter(MaterialReturn.inspection_time < end_dt)

    mt_return_map = {}
    for row in mt_return_query.all():
        mt_return_map[row.material_id] = row.return_qty or 0

    mt_avg_days_query = db.query(
        BorrowItem.material_id,
        func.avg(
            func.julianday(MaterialReturn.inspection_time) - func.julianday(BorrowApplication.actual_pickup_time)
        ).label("avg_days")
    ).select_from(ReturnItem).join(
        MaterialReturn, ReturnItem.return_id == MaterialReturn.id
    ).join(
        BorrowItem, ReturnItem.borrow_item_id == BorrowItem.id
    ).join(
        BorrowApplication, BorrowItem.borrow_id == BorrowApplication.id
    ).filter(
        MaterialReturn.inspection_time >= ninety_days_ago,
        BorrowApplication.actual_pickup_time.isnot(None)
    ).group_by(BorrowItem.material_id)
    if start_dt:
        mt_avg_days_query = mt_avg_days_query.filter(MaterialReturn.inspection_time >= start_dt)
    if end_dt:
        mt_avg_days_query = mt_avg_days_query.filter(MaterialReturn.inspection_time < end_dt)

    mt_avg_days_map = {}
    for row in mt_avg_days_query.all():
        mt_avg_days_map[row.material_id] = round(row.avg_days or 0.0, 2)

    mt_inventory_query = db.query(
        InventoryBatch.material_id,
        func.avg(InventoryBatch.available_quantity + InventoryBatch.locked_quantity).label("avg_inv")
    ).group_by(InventoryBatch.material_id)
    mt_avg_inv_map = {}
    for row in mt_inventory_query.all():
        mt_avg_inv_map[row.material_id] = row.avg_inv or 0

    mt_list = []
    for material_id, data in mt_borrow_map.items():
        return_qty = mt_return_map.get(material_id, 0)
        avg_days = mt_avg_days_map.get(material_id, 0.0)
        avg_inv = mt_avg_inv_map.get(material_id, 0)
        turnover_rate = round(data["borrow_quantity"] / (avg_inv + 1), 4)
        mt_list.append(MaterialTurnoverItem(
            material_id=material_id,
            material_code=data["material_code"],
            material_name=data["material_name"],
            category=data["category"],
            unit=data["unit"],
            borrow_count=data["borrow_count"],
            borrow_quantity=data["borrow_quantity"],
            return_quantity=return_qty,
            avg_borrow_days=avg_days,
            turnover_rate=turnover_rate
        ))
    mt_list.sort(key=lambda x: -x.turnover_rate)
    material_turnover = mt_list[:50]

    overdue_borrows = []
    ob_query = db.query(BorrowApplication).filter(
        BorrowApplication.status.in_([BorrowStatus.PICKED_UP, BorrowStatus.PARTIAL_RETURNED]),
        BorrowApplication.expected_return_time < now
    )
    if filters.community:
        ob_query = ob_query.filter(BorrowApplication.community == filters.community)
    if hasattr(filters, 'elderly_id') and filters.elderly_id:
        ob_query = ob_query.filter(BorrowApplication.elderly_id == filters.elderly_id)

    ob_applications = ob_query.order_by(BorrowApplication.expected_return_time.asc()).all()
    for app in ob_applications:
        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == app.elderly_id).first()
        order = db.query(WorkOrder).filter(WorkOrder.id == app.work_order_id).first() if app.work_order_id else None
        overdue_days = (now - app.expected_return_time).days if app.expected_return_time else 0

        items_detail = []
        for item in app.items:
            if item.picked_quantity > item.returned_quantity:
                items_detail.append({
                    "material_id": item.material_id,
                    "material_code": item.material_code,
                    "material_name": item.material_name,
                    "spec": item.spec,
                    "unit": item.unit,
                    "picked_quantity": item.picked_quantity,
                    "returned_quantity": item.returned_quantity,
                    "unreturned_quantity": item.picked_quantity - item.returned_quantity
                })

        overdue_borrows.append(OverdueBorrowItem(
            borrow_id=app.id,
            borrow_no=app.borrow_no,
            elderly_id=app.elderly_id,
            elderly_name=elderly.name if elderly else "",
            community=app.community or (elderly.community if elderly else ""),
            work_order_id=app.work_order_id,
            order_no=order.order_no if order else None,
            expected_return_time=app.expected_return_time,
            overdue_days=overdue_days,
            items=items_detail
        ))

    scrap_rate_ranking = []
    sr_borrow_query = db.query(
        BorrowItem.material_id,
        func.sum(BorrowItem.picked_quantity).label("borrow_qty")
    ).join(BorrowApplication).filter(
        BorrowApplication.actual_pickup_time >= ninety_days_ago,
        BorrowItem.picked_quantity > 0
    ).group_by(BorrowItem.material_id)
    if start_dt:
        sr_borrow_query = sr_borrow_query.filter(BorrowApplication.actual_pickup_time >= start_dt)
    if end_dt:
        sr_borrow_query = sr_borrow_query.filter(BorrowApplication.actual_pickup_time < end_dt)

    sr_borrow_map = {}
    for row in sr_borrow_query.all():
        sr_borrow_map[row.material_id] = row.borrow_qty or 0

    sr_scrap_query = db.query(
        MaterialScrap.material_id,
        Material.material_code,
        Material.material_name,
        Material.category,
        Material.unit,
        func.sum(MaterialScrap.scrap_quantity).label("scrap_qty")
    ).join(Material, MaterialScrap.material_id == Material.id).filter(
        MaterialScrap.created_at >= ninety_days_ago
    ).group_by(
        MaterialScrap.material_id,
        Material.material_code,
        Material.material_name,
        Material.category,
        Material.unit
    )
    if start_dt:
        sr_scrap_query = sr_scrap_query.filter(MaterialScrap.created_at >= start_dt)
    if end_dt:
        sr_scrap_query = sr_scrap_query.filter(MaterialScrap.created_at < end_dt)

    sr_list = []
    for row in sr_scrap_query.all():
        borrowed = sr_borrow_map.get(row.material_id, 0)
        scrap_rate = round((row.scrap_qty or 0) / (borrowed + 1), 4)
        sr_list.append(ScrapRateRankingItem(
            material_id=row.material_id,
            material_code=row.material_code,
            material_name=row.material_name,
            category=row.category,
            unit=row.unit,
            total_scrapped=row.scrap_qty or 0,
            total_borrowed=borrowed,
            scrap_rate=scrap_rate
        ))
    sr_list.sort(key=lambda x: -x.scrap_rate)
    scrap_rate_ranking = sr_list[:20]

    service_type_consumption = []
    stc_query = db.query(
        func.date(BorrowApplication.created_at).label("borrow_date"),
        WorkOrder.service_type,
        BorrowItem.material_id,
        Material.material_code,
        Material.material_name,
        func.count(BorrowApplication.id).label("borrow_cnt"),
        func.sum(BorrowItem.picked_quantity).label("borrow_qty")
    ).select_from(BorrowItem).join(
        BorrowApplication, BorrowItem.borrow_id == BorrowApplication.id
    ).join(
        WorkOrder, BorrowApplication.work_order_id == WorkOrder.id
    ).join(
        Material, BorrowItem.material_id == Material.id
    ).filter(
        BorrowApplication.created_at >= thirty_days_ago,
        BorrowApplication.work_order_id.isnot(None),
        BorrowItem.picked_quantity > 0
    ).group_by(
        func.date(BorrowApplication.created_at),
        WorkOrder.service_type,
        BorrowItem.material_id,
        Material.material_code,
        Material.material_name
    )
    if hasattr(filters, 'service_type') and filters.service_type:
        stc_query = stc_query.filter(WorkOrder.service_type == filters.service_type)
    if filters.material_id:
        stc_query = stc_query.filter(BorrowItem.material_id == filters.material_id)
    if start_dt:
        stc_query = stc_query.filter(BorrowApplication.created_at >= start_dt)
    if end_dt:
        stc_query = stc_query.filter(BorrowApplication.created_at < end_dt)

    for row in stc_query.all():
        service_type_consumption.append(ServiceTypeMaterialConsumptionItem(
            date=str(row.borrow_date),
            service_type=row.service_type,
            material_id=row.material_id,
            material_code=row.material_code,
            material_name=row.material_name,
            borrow_count=row.borrow_cnt or 0,
            borrow_quantity=row.borrow_qty or 0
        ))

    elderly_unreturned_list = []
    eu_query = db.query(BorrowApplication).filter(
        BorrowApplication.status.in_([BorrowStatus.PICKED_UP, BorrowStatus.PARTIAL_RETURNED])
    )
    if filters.community:
        eu_query = eu_query.filter(BorrowApplication.community == filters.community)

    elderly_map = defaultdict(lambda: {
        "elderly_id": None,
        "elderly_name": "",
        "community": "",
        "borrow_count": 0,
        "unreturned_quantity": 0,
        "items": []
    })

    for app in eu_query.all():
        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == app.elderly_id).first()
        key = app.elderly_id
        elderly_map[key]["elderly_id"] = app.elderly_id
        elderly_map[key]["elderly_name"] = elderly.name if elderly else ""
        elderly_map[key]["community"] = app.community or (elderly.community if elderly else "")
        elderly_map[key]["borrow_count"] += 1

        for item in app.items:
            unreturned = item.picked_quantity - item.returned_quantity
            if unreturned > 0:
                elderly_map[key]["unreturned_quantity"] += unreturned
                elderly_map[key]["items"].append({
                    "borrow_id": app.id,
                    "borrow_no": app.borrow_no,
                    "material_id": item.material_id,
                    "material_code": item.material_code,
                    "material_name": item.material_name,
                    "spec": item.spec,
                    "unit": item.unit,
                    "unreturned_quantity": unreturned,
                    "expected_return_time": app.expected_return_time.isoformat() if app.expected_return_time else None
                })

    eu_list = []
    for key, data in elderly_map.items():
        if data["unreturned_quantity"] > 0:
            eu_list.append(ElderlyUnreturnedItem(
                elderly_id=data["elderly_id"],
                elderly_name=data["elderly_name"],
                community=data["community"],
                borrow_count=data["borrow_count"],
                unreturned_quantity=data["unreturned_quantity"],
                items=data["items"]
            ))
    eu_list.sort(key=lambda x: -x.unreturned_quantity)
    elderly_unreturned_list = eu_list[:30]

    inventory_gap_prediction_7days = []
    igp_query = db.query(
        MaterialWarehouse.community,
        BorrowItem.material_id,
        Material.material_code,
        Material.material_name,
        Material.category,
        Material.unit,
        func.sum(BorrowItem.picked_quantity).label("total_borrowed")
    ).select_from(BorrowItem).join(
        BorrowApplication, BorrowItem.borrow_id == BorrowApplication.id
    ).join(
        Material, BorrowItem.material_id == Material.id
    ).join(
        MaterialWarehouse, BorrowApplication.community == MaterialWarehouse.community
    ).filter(
        BorrowApplication.actual_pickup_time >= thirty_days_ago,
        BorrowItem.picked_quantity > 0
    ).group_by(
        MaterialWarehouse.community,
        BorrowItem.material_id,
        Material.material_code,
        Material.material_name,
        Material.category,
        Material.unit
    )
    if filters.community:
        igp_query = igp_query.filter(MaterialWarehouse.community == filters.community)
    if filters.material_id:
        igp_query = igp_query.filter(BorrowItem.material_id == filters.material_id)

    igp_borrow_map = {}
    for row in igp_query.all():
        key = (row.community, row.material_id)
        igp_borrow_map[key] = {
            "community": row.community,
            "material_id": row.material_id,
            "material_code": row.material_code,
            "material_name": row.material_name,
            "category": row.category,
            "unit": row.unit,
            "total_borrowed_30days": row.total_borrowed or 0
        }

    igp_inv_query = db.query(
        MaterialWarehouse.community,
        InventoryBatch.material_id,
        InventoryBatch.low_stock_threshold,
        func.sum(InventoryBatch.available_quantity).label("available_qty")
    ).select_from(InventoryBatch).join(
        MaterialWarehouse, InventoryBatch.warehouse_id == MaterialWarehouse.id
    ).filter(
        InventoryBatch.status.notin_([InventoryStatus.DISABLED, InventoryStatus.SCRAPPED])
    ).group_by(
        MaterialWarehouse.community,
        InventoryBatch.material_id,
        InventoryBatch.low_stock_threshold
    )
    if filters.community:
        igp_inv_query = igp_inv_query.filter(MaterialWarehouse.community == filters.community)
    if filters.material_id:
        igp_inv_query = igp_inv_query.filter(InventoryBatch.material_id == filters.material_id)

    igp_inv_map = {}
    for row in igp_inv_query.all():
        key = (row.community, row.material_id)
        if key not in igp_inv_map:
            igp_inv_map[key] = {
                "available_qty": 0,
                "threshold": row.low_stock_threshold or 0
            }
        igp_inv_map[key]["available_qty"] += row.available_qty or 0

    prediction_date = today + timedelta(days=7)
    for key, borrow_data in igp_borrow_map.items():
        inv_data = igp_inv_map.get(key, {"available_qty": 0, "threshold": 0})
        daily_consumption = borrow_data["total_borrowed_30days"] / 30.0
        predicted_demand = round(daily_consumption * 7)
        current_available = inv_data["available_qty"]
        predicted_gap = max(0, predicted_demand - current_available)
        threshold = inv_data["threshold"]

        if predicted_gap == 0 and current_available > threshold:
            continue

        if predicted_gap == 0:
            suggested_action = "库存充足"
        elif predicted_gap <= threshold:
            suggested_action = "建议关注"
        else:
            suggested_action = "需要补货"

        inventory_gap_prediction_7days.append(InventoryGapPredictionItem(
            date=str(prediction_date),
            material_id=borrow_data["material_id"],
            material_code=borrow_data["material_code"],
            material_name=borrow_data["material_name"],
            category=borrow_data["category"],
            unit=borrow_data["unit"],
            community=borrow_data["community"],
            current_available=current_available,
            predicted_demand=predicted_demand,
            predicted_gap=predicted_gap,
            suggested_action=suggested_action
        ))

    response = MaterialStatisticsResponse(
        summary=summary,
        community_inventory=community_inventory,
        low_stock_warnings=low_stock_warnings,
        expiring_materials=expiring_materials,
        material_turnover=material_turnover,
        overdue_borrows=overdue_borrows,
        scrap_rate_ranking=scrap_rate_ranking,
        service_type_consumption=service_type_consumption,
        elderly_unreturned_list=elderly_unreturned_list,
        inventory_gap_prediction_7days=inventory_gap_prediction_7days,
        filters=filters.model_dump()
    )

    return success_response(data=response)
