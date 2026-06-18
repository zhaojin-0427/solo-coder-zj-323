from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.models import ElderlyProfile
from app.schemas import (
    ElderlyProfileCreate, ElderlyProfileUpdate, ElderlyProfileResponse,
    ElderlyProfileListResponse
)
from app.utils import success_response, error_response, ApiResponse

router = APIRouter(prefix="/elderly", tags=["老人档案管理"])


@router.post("", response_model=ApiResponse[ElderlyProfileResponse])
def create_elderly(profile: ElderlyProfileCreate, db: Session = Depends(get_db)):
    if profile.id_card:
        existing = db.query(ElderlyProfile).filter(ElderlyProfile.id_card == profile.id_card).first()
        if existing:
            return error_response(code=400, message="身份证号已存在")
    
    db_profile = ElderlyProfile(**profile.model_dump())
    db.add(db_profile)
    db.commit()
    db.refresh(db_profile)
    return success_response(data=db_profile, message="老人档案创建成功")


@router.get("", response_model=ApiResponse[ElderlyProfileListResponse])
def list_elderly(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    name: Optional[str] = Query(None, description="姓名模糊查询"),
    community: Optional[str] = Query(None, description="社区查询"),
    risk_level: Optional[str] = Query(None, description="风险等级"),
    db: Session = Depends(get_db)
):
    query = db.query(ElderlyProfile)
    
    if name:
        query = query.filter(ElderlyProfile.name.like(f"%{name}%"))
    if community:
        query = query.filter(ElderlyProfile.community == community)
    if risk_level:
        query = query.filter(ElderlyProfile.risk_level == risk_level)
    
    total = query.count()
    items = query.order_by(ElderlyProfile.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    return success_response(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    })


@router.get("/{elderly_id}", response_model=ApiResponse[ElderlyProfileResponse])
def get_elderly(elderly_id: int, db: Session = Depends(get_db)):
    profile = db.query(ElderlyProfile).filter(ElderlyProfile.id == elderly_id).first()
    if not profile:
        return error_response(code=404, message="老人档案不存在")
    return success_response(data=profile)


@router.put("/{elderly_id}", response_model=ApiResponse[ElderlyProfileResponse])
def update_elderly(elderly_id: int, profile_update: ElderlyProfileUpdate, db: Session = Depends(get_db)):
    profile = db.query(ElderlyProfile).filter(ElderlyProfile.id == elderly_id).first()
    if not profile:
        return error_response(code=404, message="老人档案不存在")
    
    update_data = profile_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(profile, key, value)
    
    db.commit()
    db.refresh(profile)
    return success_response(data=profile, message="老人档案更新成功")


@router.delete("/{elderly_id}", response_model=ApiResponse)
def delete_elderly(elderly_id: int, db: Session = Depends(get_db)):
    profile = db.query(ElderlyProfile).filter(ElderlyProfile.id == elderly_id).first()
    if not profile:
        return error_response(code=404, message="老人档案不存在")
    
    db.delete(profile)
    db.commit()
    return success_response(message="老人档案删除成功")
