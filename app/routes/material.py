from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import Optional, List
from datetime import datetime, date
import uuid

from app.database import get_db
from app.models import (
    MaterialWarehouse, Material, ServiceTypeMaterial, InventoryBatch,
    WarehouseStatus, MaterialCategory, MaterialStatus, InventoryStatus, ServiceType, RiskLevel,
    ElderlyProfile
)
from app.schemas import (
    MaterialWarehouseCreate, MaterialWarehouseUpdate, MaterialWarehouseResponse, MaterialWarehouseListResponse,
    MaterialCreate, MaterialUpdate, MaterialResponse, MaterialListResponse,
    ServiceTypeMaterialCreate, ServiceTypeMaterialUpdate, ServiceTypeMaterialResponse,
    InventoryBatchCreate, InventoryBatchUpdate, InventoryBatchResponse, InventoryBatchListResponse
)
from app.utils import success_response, error_response, ApiResponse, orm_to_dict

router = APIRouter(prefix="/material", tags=["物资与库存管理"])


def generate_no(prefix: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d")
    suffix = uuid.uuid4().hex[:6].upper()
    return f"{prefix}{timestamp}{suffix}"


def validate_batch_status(batch: InventoryBatch) -> InventoryStatus:
    if batch.status == InventoryStatus.DISABLED or batch.status == InventoryStatus.SCRAPPED:
        return batch.status
    today = date.today()
    if batch.expiry_date and batch.expiry_date < today:
        return InventoryStatus.EXPIRED
    if batch.expiry_date and (batch.expiry_date - today).days <= 30:
        return InventoryStatus.EXPIRING
    if batch.available_quantity <= batch.low_stock_threshold:
        return InventoryStatus.LOW_STOCK
    return InventoryStatus.NORMAL


def update_inventory_status(db: Session, batch: InventoryBatch):
    new_status = validate_batch_status(batch)
    if batch.status != new_status and batch.status not in [InventoryStatus.DISABLED, InventoryStatus.SCRAPPED]:
        batch.status = new_status
        db.flush()


@router.post("/warehouses", response_model=ApiResponse[MaterialWarehouseResponse])
def create_warehouse(warehouse_data: MaterialWarehouseCreate, db: Session = Depends(get_db)):
    warehouse_code = generate_no("WH")
    data = warehouse_data.model_dump()
    data["warehouse_code"] = warehouse_code
    db_warehouse = MaterialWarehouse(**data)
    db.add(db_warehouse)
    db.commit()
    db.refresh(db_warehouse)
    return success_response(data=db_warehouse, message="仓库创建成功")


@router.get("/warehouses", response_model=ApiResponse[MaterialWarehouseListResponse])
def list_warehouses(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    community: Optional[str] = Query(None, description="社区筛选"),
    status: Optional[str] = Query(None, description="状态筛选"),
    db: Session = Depends(get_db)
):
    query = db.query(MaterialWarehouse)
    
    if community:
        query = query.filter(MaterialWarehouse.community == community)
    if status:
        try:
            query = query.filter(MaterialWarehouse.status == WarehouseStatus(status))
        except ValueError:
            return error_response(code=400, message=f"无效的状态值: {status}")
    
    total = query.count()
    items = query.order_by(MaterialWarehouse.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    return success_response(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    })


@router.get("/warehouses/{warehouse_id}", response_model=ApiResponse[MaterialWarehouseResponse])
def get_warehouse(warehouse_id: int, db: Session = Depends(get_db)):
    warehouse = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == warehouse_id).first()
    if not warehouse:
        return error_response(code=404, message="仓库不存在")
    return success_response(data=warehouse)


@router.put("/warehouses/{warehouse_id}", response_model=ApiResponse[MaterialWarehouseResponse])
def update_warehouse(warehouse_id: int, warehouse_update: MaterialWarehouseUpdate, db: Session = Depends(get_db)):
    warehouse = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == warehouse_id).first()
    if not warehouse:
        return error_response(code=404, message="仓库不存在")
    
    update_data = warehouse_update.model_dump(exclude_unset=True)
    
    if "status" in update_data and update_data["status"]:
        try:
            update_data["status"] = WarehouseStatus(update_data["status"])
        except ValueError:
            return error_response(code=400, message=f"无效的状态值: {update_data['status']}")
    
    for key, value in update_data.items():
        setattr(warehouse, key, value)
    
    db.commit()
    db.refresh(warehouse)
    return success_response(data=warehouse, message="仓库更新成功")


@router.delete("/warehouses/{warehouse_id}", response_model=ApiResponse)
def delete_warehouse(warehouse_id: int, db: Session = Depends(get_db)):
    warehouse = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == warehouse_id).first()
    if not warehouse:
        return error_response(code=404, message="仓库不存在")
    
    if warehouse.inventory_batches:
        return error_response(code=400, message="该仓库存在库存批次，不可删除")
    
    db.delete(warehouse)
    db.commit()
    return success_response(message="仓库删除成功")


@router.post("/materials", response_model=ApiResponse[MaterialResponse])
def create_material(material_data: MaterialCreate, db: Session = Depends(get_db)):
    material_code = generate_no("MT")
    data = material_data.model_dump()
    data["material_code"] = material_code
    db_material = Material(**data)
    db.add(db_material)
    db.commit()
    db.refresh(db_material)
    return success_response(data=db_material, message="物资档案创建成功")


@router.get("/materials", response_model=ApiResponse[MaterialListResponse])
def list_materials(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    name: Optional[str] = Query(None, description="物资名称模糊查询"),
    category: Optional[str] = Query(None, description="物资分类筛选"),
    status: Optional[str] = Query(None, description="状态筛选"),
    db: Session = Depends(get_db)
):
    query = db.query(Material)
    
    if name:
        query = query.filter(Material.material_name.like(f"%{name}%"))
    if category:
        try:
            query = query.filter(Material.category == MaterialCategory(category))
        except ValueError:
            return error_response(code=400, message=f"无效的物资分类: {category}")
    if status:
        try:
            query = query.filter(Material.status == MaterialStatus(status))
        except ValueError:
            return error_response(code=400, message=f"无效的状态值: {status}")
    
    total = query.count()
    items = query.order_by(Material.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    return success_response(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    })


@router.get("/materials/{material_id}", response_model=ApiResponse[MaterialResponse])
def get_material(material_id: int, db: Session = Depends(get_db)):
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        return error_response(code=404, message="物资档案不存在")
    return success_response(data=material)


@router.put("/materials/{material_id}", response_model=ApiResponse[MaterialResponse])
def update_material(material_id: int, material_update: MaterialUpdate, db: Session = Depends(get_db)):
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        return error_response(code=404, message="物资档案不存在")
    
    update_data = material_update.model_dump(exclude_unset=True)
    
    if "category" in update_data and update_data["category"]:
        try:
            update_data["category"] = MaterialCategory(update_data["category"])
        except ValueError:
            return error_response(code=400, message=f"无效的物资分类: {update_data['category']}")
    if "status" in update_data and update_data["status"]:
        try:
            update_data["status"] = MaterialStatus(update_data["status"])
        except ValueError:
            return error_response(code=400, message=f"无效的状态值: {update_data['status']}")
    if "risk_level" in update_data and update_data["risk_level"]:
        try:
            update_data["risk_level"] = RiskLevel(update_data["risk_level"])
        except ValueError:
            return error_response(code=400, message=f"无效的风险等级: {update_data['risk_level']}")
    
    for key, value in update_data.items():
        setattr(material, key, value)
    
    db.commit()
    db.refresh(material)
    return success_response(data=material, message="物资档案更新成功")


@router.delete("/materials/{material_id}", response_model=ApiResponse)
def delete_material(material_id: int, db: Session = Depends(get_db)):
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        return error_response(code=404, message="物资档案不存在")
    
    if material.inventory_batches:
        return error_response(code=400, message="该物资存在库存批次，不可删除")
    if material.service_type_configs:
        return error_response(code=400, message="该物资存在服务类型配置，不可删除")
    
    db.delete(material)
    db.commit()
    return success_response(message="物资档案删除成功")


@router.post("/service-type-materials", response_model=ApiResponse[ServiceTypeMaterialResponse])
def create_service_type_material(config_data: ServiceTypeMaterialCreate, db: Session = Depends(get_db)):
    material = db.query(Material).filter(Material.id == config_data.material_id).first()
    if not material:
        return error_response(code=404, message="物资档案不存在")
    
    try:
        service_type = ServiceType(config_data.service_type) if isinstance(config_data.service_type, str) else config_data.service_type
    except ValueError:
        return error_response(code=400, message=f"无效的服务类型: {config_data.service_type}")
    
    existing = db.query(ServiceTypeMaterial).filter(
        ServiceTypeMaterial.service_type == service_type,
        ServiceTypeMaterial.material_id == config_data.material_id
    ).first()
    if existing:
        return error_response(code=400, message="该服务类型与物资的配置已存在")
    
    db_config = ServiceTypeMaterial(**config_data.model_dump())
    db.add(db_config)
    db.commit()
    db.refresh(db_config)
    
    result = orm_to_dict(db_config)
    result["material_name"] = material.material_name
    result["material_code"] = material.material_code
    result["spec"] = material.spec
    result["unit"] = material.unit
    
    return success_response(data=result, message="服务类型物资配置创建成功")


@router.get("/service-type-materials", response_model=ApiResponse)
def list_service_type_materials(
    service_type: Optional[str] = Query(None, description="服务类型筛选"),
    material_id: Optional[int] = Query(None, description="物资ID筛选"),
    db: Session = Depends(get_db)
):
    query = db.query(ServiceTypeMaterial)
    
    if service_type:
        try:
            query = query.filter(ServiceTypeMaterial.service_type == ServiceType(service_type))
        except ValueError:
            return error_response(code=400, message=f"无效的服务类型: {service_type}")
    if material_id:
        query = query.filter(ServiceTypeMaterial.material_id == material_id)
    
    configs = query.order_by(ServiceTypeMaterial.sort_order.asc(), ServiceTypeMaterial.id.desc()).all()
    
    items = []
    for config in configs:
        item = orm_to_dict(config)
        material = db.query(Material).filter(Material.id == config.material_id).first()
        if material:
            item["material_name"] = material.material_name
            item["material_code"] = material.material_code
            item["spec"] = material.spec
            item["unit"] = material.unit
        items.append(item)
    
    return success_response(data={"total": len(items), "items": items})


@router.put("/service-type-materials/{id}", response_model=ApiResponse[ServiceTypeMaterialResponse])
def update_service_type_material(id: int, config_update: ServiceTypeMaterialUpdate, db: Session = Depends(get_db)):
    config = db.query(ServiceTypeMaterial).filter(ServiceTypeMaterial.id == id).first()
    if not config:
        return error_response(code=404, message="服务类型物资配置不存在")
    
    update_data = config_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(config, key, value)
    
    db.commit()
    db.refresh(config)
    
    result = orm_to_dict(config)
    material = db.query(Material).filter(Material.id == config.material_id).first()
    if material:
        result["material_name"] = material.material_name
        result["material_code"] = material.material_code
        result["spec"] = material.spec
        result["unit"] = material.unit
    
    return success_response(data=result, message="服务类型物资配置更新成功")


@router.delete("/service-type-materials/{id}", response_model=ApiResponse)
def delete_service_type_material(id: int, db: Session = Depends(get_db)):
    config = db.query(ServiceTypeMaterial).filter(ServiceTypeMaterial.id == id).first()
    if not config:
        return error_response(code=404, message="服务类型物资配置不存在")
    
    db.delete(config)
    db.commit()
    return success_response(message="服务类型物资配置删除成功")


@router.get("/service-types/{service_type}/materials", response_model=ApiResponse)
def get_service_type_materials(service_type: str, db: Session = Depends(get_db)):
    try:
        st = ServiceType(service_type)
    except ValueError:
        return error_response(code=400, message=f"无效的服务类型: {service_type}")
    
    configs = db.query(ServiceTypeMaterial).filter(
        ServiceTypeMaterial.service_type == st
    ).order_by(ServiceTypeMaterial.sort_order.asc(), ServiceTypeMaterial.id.desc()).all()
    
    items = []
    for config in configs:
        item = orm_to_dict(config)
        material = db.query(Material).filter(Material.id == config.material_id).first()
        if material:
            item["material_name"] = material.material_name
            item["material_code"] = material.material_code
            item["spec"] = material.spec
            item["unit"] = material.unit
            item["category"] = material.category.value if material.category else None
            item["is_reusable"] = material.is_reusable
        items.append(item)
    
    return success_response(data={"total": len(items), "service_type": service_type, "items": items})


@router.post("/inventory-batches", response_model=ApiResponse[InventoryBatchResponse])
def create_inventory_batch(batch_data: InventoryBatchCreate, db: Session = Depends(get_db)):
    material = db.query(Material).filter(Material.id == batch_data.material_id).first()
    if not material:
        return error_response(code=404, message="物资档案不存在")
    
    warehouse = db.query(MaterialWarehouse).filter(MaterialWarehouse.id == batch_data.warehouse_id).first()
    if not warehouse:
        return error_response(code=404, message="仓库不存在")
    
    batch_no = generate_no("BT")
    data = batch_data.model_dump()
    data["batch_no"] = batch_no
    data["inbound_time"] = datetime.now()
    
    if batch_data.initial_quantity > 0 and "available_quantity" not in data:
        data["available_quantity"] = batch_data.initial_quantity
    
    if "low_stock_threshold" not in data or data["low_stock_threshold"] is None:
        data["low_stock_threshold"] = material.default_low_stock_threshold
    
    db_batch = InventoryBatch(**data)
    update_inventory_status(db, db_batch)
    db.add(db_batch)
    db.commit()
    db.refresh(db_batch)
    
    result = orm_to_dict(db_batch)
    result["material_name"] = material.material_name
    result["material_code"] = material.material_code
    result["spec"] = material.spec
    result["unit"] = material.unit
    result["warehouse_name"] = warehouse.warehouse_name
    result["community"] = warehouse.community
    
    return success_response(data=result, message="库存批次创建成功")


@router.get("/inventory-batches", response_model=ApiResponse[InventoryBatchListResponse])
def list_inventory_batches(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    material_id: Optional[int] = Query(None, description="物资ID筛选"),
    warehouse_id: Optional[int] = Query(None, description="仓库ID筛选"),
    community: Optional[str] = Query(None, description="社区筛选"),
    status: Optional[str] = Query(None, description="状态筛选"),
    expiry_date_start: Optional[str] = Query(None, description="有效期开始日期 YYYY-MM-DD"),
    expiry_date_end: Optional[str] = Query(None, description="有效期结束日期 YYYY-MM-DD"),
    db: Session = Depends(get_db)
):
    query = db.query(InventoryBatch).join(Material).join(MaterialWarehouse)
    
    if material_id:
        query = query.filter(InventoryBatch.material_id == material_id)
    if warehouse_id:
        query = query.filter(InventoryBatch.warehouse_id == warehouse_id)
    if community:
        query = query.filter(MaterialWarehouse.community == community)
    if status:
        try:
            query = query.filter(InventoryBatch.status == InventoryStatus(status))
        except ValueError:
            return error_response(code=400, message=f"无效的状态值: {status}")
    if expiry_date_start:
        try:
            start_dt = date.fromisoformat(expiry_date_start)
            query = query.filter(InventoryBatch.expiry_date >= start_dt)
        except ValueError:
            return error_response(code=400, message=f"无效的日期格式: {expiry_date_start}")
    if expiry_date_end:
        try:
            end_dt = date.fromisoformat(expiry_date_end)
            query = query.filter(InventoryBatch.expiry_date <= end_dt)
        except ValueError:
            return error_response(code=400, message=f"无效的日期格式: {expiry_date_end}")
    
    total = query.count()
    batches = query.order_by(InventoryBatch.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    items = []
    for batch in batches:
        update_inventory_status(db, batch)
        item = orm_to_dict(batch)
        material = batch.material
        warehouse = batch.warehouse
        if material:
            item["material_name"] = material.material_name
            item["material_code"] = material.material_code
            item["spec"] = material.spec
            item["unit"] = material.unit
        if warehouse:
            item["warehouse_name"] = warehouse.warehouse_name
            item["community"] = warehouse.community
        items.append(item)
    
    db.commit()
    
    return success_response(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    })


@router.get("/inventory-batches/{batch_id}", response_model=ApiResponse[InventoryBatchResponse])
def get_inventory_batch(batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(InventoryBatch).filter(InventoryBatch.id == batch_id).first()
    if not batch:
        return error_response(code=404, message="库存批次不存在")
    
    update_inventory_status(db, batch)
    db.commit()
    db.refresh(batch)
    
    result = orm_to_dict(batch)
    material = batch.material
    warehouse = batch.warehouse
    if material:
        result["material_name"] = material.material_name
        result["material_code"] = material.material_code
        result["spec"] = material.spec
        result["unit"] = material.unit
    if warehouse:
        result["warehouse_name"] = warehouse.warehouse_name
        result["community"] = warehouse.community
    
    return success_response(data=result)


@router.put("/inventory-batches/{batch_id}", response_model=ApiResponse[InventoryBatchResponse])
def update_inventory_batch(batch_id: int, batch_update: InventoryBatchUpdate, db: Session = Depends(get_db)):
    batch = db.query(InventoryBatch).filter(InventoryBatch.id == batch_id).first()
    if not batch:
        return error_response(code=404, message="库存批次不存在")
    
    update_data = batch_update.model_dump(exclude_unset=True)
    
    if "status" in update_data and update_data["status"]:
        try:
            update_data["status"] = InventoryStatus(update_data["status"])
        except ValueError:
            return error_response(code=400, message=f"无效的状态值: {update_data['status']}")
    
    for key, value in update_data.items():
        setattr(batch, key, value)
    
    update_inventory_status(db, batch)
    db.commit()
    db.refresh(batch)
    
    result = orm_to_dict(batch)
    material = batch.material
    warehouse = batch.warehouse
    if material:
        result["material_name"] = material.material_name
        result["material_code"] = material.material_code
        result["spec"] = material.spec
        result["unit"] = material.unit
    if warehouse:
        result["warehouse_name"] = warehouse.warehouse_name
        result["community"] = warehouse.community
    
    return success_response(data=result, message="库存批次更新成功")


@router.delete("/inventory-batches/{batch_id}", response_model=ApiResponse)
def delete_inventory_batch(batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(InventoryBatch).filter(InventoryBatch.id == batch_id).first()
    if not batch:
        return error_response(code=404, message="库存批次不存在")
    
    if batch.borrow_items:
        return error_response(code=400, message="该批次存在借用记录，不可删除")
    if batch.transfer_items:
        return error_response(code=400, message="该批次存在调拨记录，不可删除")
    
    db.delete(batch)
    db.commit()
    return success_response(message="库存批次删除成功")
