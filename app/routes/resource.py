from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from typing import Optional, List
from datetime import datetime, timedelta, date, time
import uuid
from collections import defaultdict

from app.database import get_db
from app.models import (
    ServiceStaff, StaffSkill, StaffCommunity, StaffSchedule, DispatchRecord,
    WorkOrder, ElderlyProfile, ProgressRecord,
    OrderStatus, ServiceType, RiskLevel, ProgressType,
    StaffStatus, DispatchStatus, DispatchType
)
from app.schemas import (
    ServiceStaffCreate, ServiceStaffUpdate, ServiceStaffResponse,
    StaffSkillCreate, StaffSkillUpdate, StaffSkillResponse,
    StaffCommunityCreate, StaffCommunityUpdate, StaffCommunityResponse,
    StaffScheduleCreate, StaffScheduleUpdate, StaffScheduleResponse,
    DispatchRecordCreate, DispatchReassignRequest, DispatchCancelRequest,
    DispatchReleaseRequest, DispatchConfirmRequest, DispatchRecordResponse,
    CandidateStaffListResponse, ResourceDashboardResponse
)
from app.utils import success_response, error_response, ApiResponse, orm_to_dict

router = APIRouter(prefix="/resource", tags=["资源调度与供需匹配"])


def generate_staff_no() -> str:
    timestamp = datetime.now().strftime("%Y%m%d")
    suffix = uuid.uuid4().hex[:6].upper()
    return f"SS{timestamp}{suffix}"


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


def check_time_conflict(db: Session, staff_id: int, start_time: datetime, end_time: datetime, exclude_order_id: int = None) -> bool:
    query = db.query(DispatchRecord).filter(
        DispatchRecord.staff_id == staff_id,
        DispatchRecord.dispatch_status.in_([DispatchStatus.CONFIRMED, DispatchStatus.PENDING]),
    )
    if exclude_order_id:
        query = query.filter(DispatchRecord.work_order_id != exclude_order_id)
    
    active_dispatches = query.all()
    
    for dispatch in active_dispatches:
        order = db.query(WorkOrder).filter(WorkOrder.id == dispatch.work_order_id).first()
        if order and order.status not in [OrderStatus.COMPLETED, OrderStatus.CLOSED, OrderStatus.INCOMPLETE]:
            if not (end_time <= order.appointment_start or start_time >= order.appointment_end):
                return True
    return False


def get_staff_daily_load(db: Session, staff_id: int, target_date: date) -> int:
    start_dt = datetime.combine(target_date, time.min)
    end_dt = datetime.combine(target_date, time.max)
    
    query = db.query(DispatchRecord).filter(
        DispatchRecord.staff_id == staff_id,
        DispatchRecord.dispatch_status.in_([DispatchStatus.CONFIRMED, DispatchStatus.PENDING]),
    )
    
    dispatches = query.all()
    count = 0
    for dispatch in dispatches:
        order = db.query(WorkOrder).filter(WorkOrder.id == dispatch.work_order_id).first()
        if order and order.status not in [OrderStatus.COMPLETED, OrderStatus.CLOSED, OrderStatus.INCOMPLETE]:
            if start_dt <= order.appointment_start <= end_dt or start_dt <= order.appointment_end <= end_dt:
                count += 1
    return count


def get_staff_weekly_load(db: Session, staff_id: int, target_date: date) -> int:
    start_of_week = target_date - timedelta(days=target_date.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    start_dt = datetime.combine(start_of_week, time.min)
    end_dt = datetime.combine(end_of_week, time.max)
    
    query = db.query(DispatchRecord).filter(
        DispatchRecord.staff_id == staff_id,
        DispatchRecord.dispatch_status.in_([DispatchStatus.CONFIRMED, DispatchStatus.PENDING]),
    )
    
    dispatches = query.all()
    count = 0
    for dispatch in dispatches:
        order = db.query(WorkOrder).filter(WorkOrder.id == dispatch.work_order_id).first()
        if order and order.status not in [OrderStatus.COMPLETED, OrderStatus.CLOSED, OrderStatus.INCOMPLETE]:
            if not (end_dt < order.appointment_start or start_dt > order.appointment_end):
                count += 1
    return count


def get_staff_monthly_load(db: Session, staff_id: int, target_date: date) -> int:
    first_day = target_date.replace(day=1)
    if first_day.month == 12:
        last_day = first_day.replace(year=first_day.year + 1, month=1) - timedelta(days=1)
    else:
        last_day = first_day.replace(month=first_day.month + 1) - timedelta(days=1)
    start_dt = datetime.combine(first_day, time.min)
    end_dt = datetime.combine(last_day, time.max)
    
    query = db.query(DispatchRecord).filter(
        DispatchRecord.staff_id == staff_id,
        DispatchRecord.dispatch_status.in_([DispatchStatus.CONFIRMED, DispatchStatus.PENDING]),
    )
    
    dispatches = query.all()
    count = 0
    for dispatch in dispatches:
        order = db.query(WorkOrder).filter(WorkOrder.id == dispatch.work_order_id).first()
        if order and order.status not in [OrderStatus.COMPLETED, OrderStatus.CLOSED, OrderStatus.INCOMPLETE]:
            if not (end_dt < order.appointment_start or start_dt > order.appointment_end):
                count += 1
    return count


def check_staff_capacity(db: Session, staff: ServiceStaff, order_date: date) -> tuple:
    daily_load = get_staff_daily_load(db, staff.id, order_date)
    weekly_load = get_staff_weekly_load(db, staff.id, order_date)
    monthly_load = get_staff_monthly_load(db, staff.id, order_date)
    
    daily_ok = daily_load < staff.daily_capacity
    weekly_ok = weekly_load < staff.weekly_capacity
    monthly_ok = monthly_load < staff.monthly_capacity
    
    return (daily_ok and weekly_ok and monthly_ok), daily_load, weekly_load, monthly_load


def check_skill_match(db: Session, staff_id: int, service_type: str) -> bool:
    skill = db.query(StaffSkill).filter(
        StaffSkill.staff_id == staff_id,
        StaffSkill.skill_tag == service_type
    ).first()
    return skill is not None


def check_community_match(db: Session, staff_id: int, community: str) -> bool:
    comm = db.query(StaffCommunity).filter(
        StaffCommunity.staff_id == staff_id,
        StaffCommunity.community == community
    ).first()
    return comm is not None


def check_schedule_available(db: Session, staff_id: int, schedule_date: date, 
                             start_time: time, end_time: time) -> bool:
    schedule = db.query(StaffSchedule).filter(
        StaffSchedule.staff_id == staff_id,
        StaffSchedule.schedule_date == schedule_date,
        StaffSchedule.is_available == True
    ).first()
    
    if not schedule:
        return True
    
    s_start = schedule.start_time
    s_end = schedule.end_time
    
    return start_time >= s_start and end_time <= s_end


def get_staff_historical_services(db: Session, staff_id: int, service_type: str = None) -> int:
    query = db.query(DispatchRecord).filter(
        DispatchRecord.staff_id == staff_id,
        DispatchRecord.dispatch_status == DispatchStatus.COMPLETED
    )
    if service_type:
        query = query.join(WorkOrder).filter(WorkOrder.service_type == service_type)
    return query.count()


def calculate_match_score(db: Session, staff: ServiceStaff, order: WorkOrder, elderly: ElderlyProfile) -> dict:
    score = 0.0
    details = {
        "skill_match": False,
        "community_match": False,
        "time_available": False,
        "current_load": 0,
        "capacity": staff.daily_capacity,
        "load_rate": 0.0,
        "historical_services": 0,
        "is_certified": False,
        "primary_community": None
    }
    
    service_type = order.service_type.value
    community = elderly.community or ""
    
    if check_skill_match(db, staff.id, service_type):
        score += 30
        details["skill_match"] = True
        skill = db.query(StaffSkill).filter(
            StaffSkill.staff_id == staff.id,
            StaffSkill.skill_tag == service_type
        ).first()
        if skill:
            details["is_certified"] = skill.is_certified
            score += skill.proficiency * 2
    
    if check_community_match(db, staff.id, community):
        score += 25
        details["community_match"] = True
        comm = db.query(StaffCommunity).filter(
            StaffCommunity.staff_id == staff.id,
            StaffCommunity.community == community
        ).first()
        if comm:
            if comm.is_primary:
                score += 10
            details["primary_community"] = community if comm.is_primary else None
            score += (6 - comm.priority) * 2
    
    schedule_date = order.appointment_start.date()
    start_t = order.appointment_start.time()
    end_t = order.appointment_end.time()
    
    if check_schedule_available(db, staff.id, schedule_date, start_t, end_t):
        if not check_time_conflict(db, staff.id, order.appointment_start, order.appointment_end):
            score += 20
            details["time_available"] = True
    
    capacity_ok, daily_load, weekly_load, monthly_load = check_staff_capacity(db, staff, schedule_date)
    details["current_load"] = daily_load
    load_rate = daily_load / staff.daily_capacity if staff.daily_capacity > 0 else 1
    details["load_rate"] = round(load_rate, 2)
    
    if capacity_ok:
        score += (1 - load_rate) * 15
    
    historical = get_staff_historical_services(db, staff.id, service_type)
    details["historical_services"] = historical
    if historical > 0:
        score += min(historical / 10, 10)
    
    if elderly.risk_level == RiskLevel.CRITICAL and details["is_certified"]:
        score += 10
    elif elderly.risk_level == RiskLevel.HIGH and details["is_certified"]:
        score += 5
    
    return {
        "score": round(score, 2),
        **details
    }


@router.post("/staff", response_model=ApiResponse[ServiceStaffResponse])
def create_staff(staff_data: ServiceStaffCreate, db: Session = Depends(get_db)):
    if staff_data.id_card:
        existing = db.query(ServiceStaff).filter(ServiceStaff.id_card == staff_data.id_card).first()
        if existing:
            return error_response(code=400, message="身份证号已存在")
    
    staff_no = generate_staff_no()
    db_staff = ServiceStaff(
        staff_no=staff_no,
        **staff_data.model_dump()
    )
    db.add(db_staff)
    db.commit()
    db.refresh(db_staff)
    return success_response(data=db_staff, message="服务人员档案创建成功")


@router.get("/staff", response_model=ApiResponse)
def list_staff(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    name: Optional[str] = Query(None, description="姓名模糊查询"),
    status: Optional[str] = Query(None, description="状态筛选"),
    community: Optional[str] = Query(None, description="可服务社区筛选"),
    skill_tag: Optional[str] = Query(None, description="技能标签筛选"),
    db: Session = Depends(get_db)
):
    query = db.query(ServiceStaff)
    
    if name:
        query = query.filter(ServiceStaff.name.like(f"%{name}%"))
    if status:
        try:
            query = query.filter(ServiceStaff.status == StaffStatus(status))
        except ValueError:
            return error_response(code=400, message=f"无效的状态值: {status}")
    if community:
        query = query.join(StaffCommunity).filter(StaffCommunity.community == community)
    if skill_tag:
        query = query.join(StaffSkill).filter(StaffSkill.skill_tag == skill_tag)
    
    total = query.count()
    staff_list = query.order_by(ServiceStaff.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    items = []
    for staff in staff_list:
        staff_dict = orm_to_dict(staff)
        skills = db.query(StaffSkill).filter(StaffSkill.staff_id == staff.id).all()
        communities = db.query(StaffCommunity).filter(StaffCommunity.staff_id == staff.id).all()
        staff_dict["skills"] = orm_to_dict(skills)
        staff_dict["communities"] = orm_to_dict(communities)
        items.append(staff_dict)
    
    return success_response(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    })


@router.get("/staff/{staff_id}", response_model=ApiResponse)
def get_staff(staff_id: int, db: Session = Depends(get_db)):
    staff = db.query(ServiceStaff).filter(ServiceStaff.id == staff_id).first()
    if not staff:
        return error_response(code=404, message="服务人员档案不存在")
    
    result = orm_to_dict(staff)
    skills = db.query(StaffSkill).filter(StaffSkill.staff_id == staff_id).all()
    communities = db.query(StaffCommunity).filter(StaffCommunity.staff_id == staff_id).all()
    schedules = db.query(StaffSchedule).filter(
        StaffSchedule.staff_id == staff_id,
        StaffSchedule.schedule_date >= date.today()
    ).order_by(StaffSchedule.schedule_date.asc()).all()
    
    dispatches = db.query(DispatchRecord).filter(
        DispatchRecord.staff_id == staff_id
    ).order_by(DispatchRecord.created_at.desc()).limit(20).all()
    
    today_load = get_staff_daily_load(db, staff_id, date.today())
    week_load = get_staff_weekly_load(db, staff_id, date.today())
    
    result["skills"] = orm_to_dict(skills)
    result["communities"] = orm_to_dict(communities)
    result["schedules"] = orm_to_dict(schedules)
    result["recent_dispatches"] = orm_to_dict(dispatches)
    result["today_load"] = today_load
    result["week_load"] = week_load
    result["load_stats"] = {
        "daily": {"current": today_load, "capacity": staff.daily_capacity},
        "weekly": {"current": week_load, "capacity": staff.weekly_capacity}
    }
    
    return success_response(data=result)


@router.put("/staff/{staff_id}", response_model=ApiResponse[ServiceStaffResponse])
def update_staff(staff_id: int, staff_update: ServiceStaffUpdate, db: Session = Depends(get_db)):
    staff = db.query(ServiceStaff).filter(ServiceStaff.id == staff_id).first()
    if not staff:
        return error_response(code=404, message="服务人员档案不存在")
    
    update_data = staff_update.model_dump(exclude_unset=True)
    
    if "id_card" in update_data and update_data["id_card"]:
        existing = db.query(ServiceStaff).filter(
            ServiceStaff.id_card == update_data["id_card"],
            ServiceStaff.id != staff_id
        ).first()
        if existing:
            return error_response(code=400, message="身份证号已被其他档案使用")
    
    if "status" in update_data and update_data["status"]:
        try:
            update_data["status"] = StaffStatus(update_data["status"])
        except ValueError:
            return error_response(code=400, message=f"无效的状态值: {update_data['status']}")
    
    for key, value in update_data.items():
        setattr(staff, key, value)
    
    db.commit()
    db.refresh(staff)
    return success_response(data=staff, message="服务人员档案更新成功")


@router.delete("/staff/{staff_id}", response_model=ApiResponse)
def delete_staff(staff_id: int, db: Session = Depends(get_db)):
    staff = db.query(ServiceStaff).filter(ServiceStaff.id == staff_id).first()
    if not staff:
        return error_response(code=404, message="服务人员档案不存在")
    
    active_dispatches = db.query(DispatchRecord).filter(
        DispatchRecord.staff_id == staff_id,
        DispatchRecord.dispatch_status.in_([DispatchStatus.CONFIRMED, DispatchStatus.PENDING])
    ).count()
    if active_dispatches > 0:
        return error_response(code=400, message="该服务人员有进行中的派单，不可删除")
    
    db.delete(staff)
    db.commit()
    return success_response(message="服务人员档案删除成功")


@router.post("/staff/{staff_id}/skills", response_model=ApiResponse[StaffSkillResponse])
def add_staff_skill(staff_id: int, skill_data: StaffSkillCreate, db: Session = Depends(get_db)):
    staff = db.query(ServiceStaff).filter(ServiceStaff.id == staff_id).first()
    if not staff:
        return error_response(code=404, message="服务人员档案不存在")
    
    existing = db.query(StaffSkill).filter(
        StaffSkill.staff_id == staff_id,
        StaffSkill.skill_tag == skill_data.skill_tag
    ).first()
    if existing:
        return error_response(code=400, message="该技能标签已存在，请使用更新接口")
    
    skill_data.staff_id = staff_id
    db_skill = StaffSkill(**skill_data.model_dump())
    db.add(db_skill)
    db.commit()
    db.refresh(db_skill)
    return success_response(data=db_skill, message="技能标签添加成功")


@router.get("/staff/{staff_id}/skills", response_model=ApiResponse)
def list_staff_skills(staff_id: int, db: Session = Depends(get_db)):
    staff = db.query(ServiceStaff).filter(ServiceStaff.id == staff_id).first()
    if not staff:
        return error_response(code=404, message="服务人员档案不存在")
    
    skills = db.query(StaffSkill).filter(StaffSkill.staff_id == staff_id).all()
    return success_response(data={"total": len(skills), "items": orm_to_dict(skills)})


@router.put("/skills/{skill_id}", response_model=ApiResponse[StaffSkillResponse])
def update_staff_skill(skill_id: int, skill_update: StaffSkillUpdate, db: Session = Depends(get_db)):
    skill = db.query(StaffSkill).filter(StaffSkill.id == skill_id).first()
    if not skill:
        return error_response(code=404, message="技能标签不存在")
    
    update_data = skill_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(skill, key, value)
    
    db.commit()
    db.refresh(skill)
    return success_response(data=skill, message="技能标签更新成功")


@router.delete("/skills/{skill_id}", response_model=ApiResponse)
def delete_staff_skill(skill_id: int, db: Session = Depends(get_db)):
    skill = db.query(StaffSkill).filter(StaffSkill.id == skill_id).first()
    if not skill:
        return error_response(code=404, message="技能标签不存在")
    
    db.delete(skill)
    db.commit()
    return success_response(message="技能标签删除成功")


@router.post("/staff/{staff_id}/communities", response_model=ApiResponse[StaffCommunityResponse])
def add_staff_community(staff_id: int, community_data: StaffCommunityCreate, db: Session = Depends(get_db)):
    staff = db.query(ServiceStaff).filter(ServiceStaff.id == staff_id).first()
    if not staff:
        return error_response(code=404, message="服务人员档案不存在")
    
    existing = db.query(StaffCommunity).filter(
        StaffCommunity.staff_id == staff_id,
        StaffCommunity.community == community_data.community
    ).first()
    if existing:
        return error_response(code=400, message="该社区配置已存在，请使用更新接口")
    
    community_data.staff_id = staff_id
    db_comm = StaffCommunity(**community_data.model_dump())
    db.add(db_comm)
    db.commit()
    db.refresh(db_comm)
    return success_response(data=db_comm, message="可服务社区添加成功")


@router.get("/staff/{staff_id}/communities", response_model=ApiResponse)
def list_staff_communities(staff_id: int, db: Session = Depends(get_db)):
    staff = db.query(ServiceStaff).filter(ServiceStaff.id == staff_id).first()
    if not staff:
        return error_response(code=404, message="服务人员档案不存在")
    
    communities = db.query(StaffCommunity).filter(
        StaffCommunity.staff_id == staff_id
    ).order_by(StaffCommunity.priority.asc()).all()
    return success_response(data={"total": len(communities), "items": orm_to_dict(communities)})


@router.put("/communities/{comm_id}", response_model=ApiResponse[StaffCommunityResponse])
def update_staff_community(comm_id: int, comm_update: StaffCommunityUpdate, db: Session = Depends(get_db)):
    comm = db.query(StaffCommunity).filter(StaffCommunity.id == comm_id).first()
    if not comm:
        return error_response(code=404, message="社区配置不存在")
    
    update_data = comm_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(comm, key, value)
    
    db.commit()
    db.refresh(comm)
    return success_response(data=comm, message="社区配置更新成功")


@router.delete("/communities/{comm_id}", response_model=ApiResponse)
def delete_staff_community(comm_id: int, db: Session = Depends(get_db)):
    comm = db.query(StaffCommunity).filter(StaffCommunity.id == comm_id).first()
    if not comm:
        return error_response(code=404, message="社区配置不存在")
    
    db.delete(comm)
    db.commit()
    return success_response(message="社区配置删除成功")


@router.post("/staff/{staff_id}/schedules", response_model=ApiResponse[StaffScheduleResponse])
def add_staff_schedule(staff_id: int, schedule_data: StaffScheduleCreate, db: Session = Depends(get_db)):
    staff = db.query(ServiceStaff).filter(ServiceStaff.id == staff_id).first()
    if not staff:
        return error_response(code=404, message="服务人员档案不存在")
    
    existing = db.query(StaffSchedule).filter(
        StaffSchedule.staff_id == staff_id,
        StaffSchedule.schedule_date == schedule_data.schedule_date
    ).first()
    if existing:
        return error_response(code=400, message="该日期排班已存在，请使用更新接口")
    
    schedule_data.staff_id = staff_id
    db_schedule = StaffSchedule(**schedule_data.model_dump())
    db.add(db_schedule)
    db.commit()
    db.refresh(db_schedule)
    return success_response(data=db_schedule, message="排班添加成功")


@router.get("/staff/{staff_id}/schedules", response_model=ApiResponse)
def list_staff_schedules(
    staff_id: int,
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    db: Session = Depends(get_db)
):
    staff = db.query(ServiceStaff).filter(ServiceStaff.id == staff_id).first()
    if not staff:
        return error_response(code=404, message="服务人员档案不存在")
    
    query = db.query(StaffSchedule).filter(StaffSchedule.staff_id == staff_id)
    
    if start_date:
        query = query.filter(StaffSchedule.schedule_date >= start_date)
    if end_date:
        query = query.filter(StaffSchedule.schedule_date <= end_date)
    
    schedules = query.order_by(StaffSchedule.schedule_date.asc()).all()
    return success_response(data={"total": len(schedules), "items": orm_to_dict(schedules)})


@router.put("/schedules/{schedule_id}", response_model=ApiResponse[StaffScheduleResponse])
def update_staff_schedule(schedule_id: int, schedule_update: StaffScheduleUpdate, db: Session = Depends(get_db)):
    schedule = db.query(StaffSchedule).filter(StaffSchedule.id == schedule_id).first()
    if not schedule:
        return error_response(code=404, message="排班记录不存在")
    
    update_data = schedule_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(schedule, key, value)
    
    db.commit()
    db.refresh(schedule)
    return success_response(data=schedule, message="排班更新成功")


@router.delete("/schedules/{schedule_id}", response_model=ApiResponse)
def delete_staff_schedule(schedule_id: int, db: Session = Depends(get_db)):
    schedule = db.query(StaffSchedule).filter(StaffSchedule.id == schedule_id).first()
    if not schedule:
        return error_response(code=404, message="排班记录不存在")
    
    schedule_date = schedule.schedule_date
    if schedule_date < date.today():
        return error_response(code=400, message="历史排班不可删除")
    
    daily_load = get_staff_daily_load(db, schedule.staff_id, schedule_date)
    if daily_load > 0 and not schedule.is_available:
        return error_response(code=400, message="该日期已有派单，不可删除")
    
    db.delete(schedule)
    db.commit()
    return success_response(message="排班删除成功")


@router.post("/schedules/batch", response_model=ApiResponse)
def batch_create_schedules(
    staff_id: int,
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    shift_type: str = Query("day", description="班次类型"),
    start_time: str = Query("08:00:00", description="开始时间"),
    end_time: str = Query("18:00:00", description="结束时间"),
    capacity: int = Query(8, description="当日容量"),
    is_available: bool = Query(True, description="是否可派单"),
    skip_weekends: bool = Query(False, description="是否跳过周末"),
    db: Session = Depends(get_db)
):
    staff = db.query(ServiceStaff).filter(ServiceStaff.id == staff_id).first()
    if not staff:
        return error_response(code=404, message="服务人员档案不存在")
    
    start_dt = date.fromisoformat(start_date)
    end_dt = date.fromisoformat(end_date)
    
    if start_dt > end_dt:
        return error_response(code=400, message="开始日期不能晚于结束日期")
    
    created_count = 0
    skipped_count = 0
    current = start_dt
    while current <= end_dt:
        if skip_weekends and current.isoweekday() > 5:
            skipped_count += 1
            current += timedelta(days=1)
            continue
        
        existing = db.query(StaffSchedule).filter(
            StaffSchedule.staff_id == staff_id,
            StaffSchedule.schedule_date == current
        ).first()
        if existing:
            skipped_count += 1
        else:
            s = StaffSchedule(
                staff_id=staff_id,
                schedule_date=current,
                shift_type=shift_type,
                start_time=time.fromisoformat(start_time),
                end_time=time.fromisoformat(end_time),
                is_available=is_available,
                capacity=capacity
            )
            db.add(s)
            created_count += 1
        
        current += timedelta(days=1)
    
    db.commit()
    return success_response(data={
        "created_count": created_count,
        "skipped_count": skipped_count
    }, message=f"批量排班完成，新增{created_count}条，跳过{skipped_count}条")


@router.get("/orders/{order_id}/candidates", response_model=ApiResponse)
def get_candidate_staff(
    order_id: int,
    top_n: int = Query(10, ge=1, le=50, description="返回候选人数"),
    db: Session = Depends(get_db)
):
    order = db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
    if not order:
        return error_response(code=404, message="工单不存在")
    
    if order.status not in [OrderStatus.PENDING]:
        return error_response(code=400, message=f"当前工单状态为{order.status.value}，不可匹配候选人")
    
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()
    if not elderly:
        return error_response(code=404, message="老人档案不存在")
    
    active_staff = db.query(ServiceStaff).filter(
        ServiceStaff.status == StaffStatus.ACTIVE
    ).all()
    
    candidates = []
    for staff in active_staff:
        match_result = calculate_match_score(db, staff, order, elderly)
        
        candidates.append({
            "staff_id": staff.id,
            "staff_no": staff.staff_no,
            "name": staff.name,
            "phone": staff.phone,
            "position": staff.position,
            "match_score": match_result["score"],
            "skill_match": match_result["skill_match"],
            "community_match": match_result["community_match"],
            "time_available": match_result["time_available"],
            "current_load": match_result["current_load"],
            "capacity": match_result["capacity"],
            "load_rate": match_result["load_rate"],
            "historical_services": match_result["historical_services"],
            "is_certified": match_result["is_certified"],
            "primary_community": match_result["primary_community"]
        })
    
    candidates.sort(key=lambda x: x["match_score"], reverse=True)
    top_candidates = candidates[:top_n]
    
    return success_response(data={
        "total": len(top_candidates),
        "order_id": order.id,
        "order_no": order.order_no,
        "items": top_candidates
    }, message="候选人员匹配完成")


@router.post("/orders/{order_id}/dispatch", response_model=ApiResponse)
def dispatch_order(
    order_id: int,
    staff_id: int,
    dispatch_type: str = Query("manual", description="派单类型 auto/manual"),
    operator: Optional[str] = Query(None, description="操作人"),
    remark: Optional[str] = Query(None, description="备注"),
    db: Session = Depends(get_db)
):
    order = db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
    if not order:
        return error_response(code=404, message="工单不存在")
    
    if order.status not in [OrderStatus.PENDING]:
        return error_response(code=400, message=f"当前工单状态为{order.status.value}，不可派单")
    
    staff = db.query(ServiceStaff).filter(ServiceStaff.id == staff_id).first()
    if not staff:
        return error_response(code=404, message="服务人员不存在")
    
    if staff.status != StaffStatus.ACTIVE:
        return error_response(code=400, message=f"服务人员状态为{staff.status.value}，不可派单")
    
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()
    community = elderly.community if elderly else ""
    
    if not check_skill_match(db, staff_id, order.service_type.value):
        return error_response(code=400, message=f"服务人员不具备{order.service_type.value}服务技能，不可强派")
    
    if community and not check_community_match(db, staff_id, community):
        return error_response(code=400, message=f"服务人员不可服务{community}社区，跨社区不可派单")
    
    if check_time_conflict(db, staff_id, order.appointment_start, order.appointment_end):
        return error_response(code=400, message="服务人员该时间段已有派单，时间冲突")
    
    schedule_date = order.appointment_start.date()
    capacity_ok, daily_load, weekly_load, monthly_load = check_staff_capacity(db, staff, schedule_date)
    if not capacity_ok:
        if daily_load >= staff.daily_capacity:
            return error_response(code=400, message=f"服务人员当日容量已满（{daily_load}/{staff.daily_capacity}），超过人员容量")
        elif weekly_load >= staff.weekly_capacity:
            return error_response(code=400, message=f"服务人员本周容量已满（{weekly_load}/{staff.weekly_capacity}），超过人员容量")
        else:
            return error_response(code=400, message=f"服务人员本月容量已满（{monthly_load}/{staff.monthly_capacity}），超过人员容量")
    
    existing_dispatch = db.query(DispatchRecord).filter(
        DispatchRecord.work_order_id == order_id,
        DispatchRecord.dispatch_status.in_([DispatchStatus.PENDING, DispatchStatus.CONFIRMED])
    ).first()
    if existing_dispatch:
        return error_response(code=400, message="该工单已有待处理派单，请勿重复派单")
    
    try:
        dtype = DispatchType(dispatch_type)
    except ValueError:
        return error_response(code=400, message=f"无效的派单类型: {dispatch_type}")
    
    match_result = calculate_match_score(db, staff, order, elderly)
    
    dispatch = DispatchRecord(
        work_order_id=order_id,
        staff_id=staff_id,
        dispatch_type=dtype,
        dispatch_status=DispatchStatus.PENDING,
        match_score=match_result["score"],
        remark=remark
    )
    db.add(dispatch)
    db.flush()
    
    order.assignee_name = staff.name
    order.assignee_phone = staff.phone
    
    add_progress_record(
        db, order_id, ProgressType.ASSIGNED,
        operator_name=operator or "系统",
        operator_role="dispatcher",
        remark=f"派单给{staff.name}（{staff.staff_no}），派单类型：{dispatch_type}，匹配度：{match_result['score']}分"
    )
    
    db.commit()
    db.refresh(dispatch)
    
    result = orm_to_dict(dispatch)
    result["staff_name"] = staff.name
    
    return success_response(data=result, message="派单成功")


@router.post("/dispatches/{dispatch_id}/confirm", response_model=ApiResponse)
def confirm_dispatch(
    dispatch_id: int,
    confirm_data: DispatchConfirmRequest,
    db: Session = Depends(get_db)
):
    dispatch = db.query(DispatchRecord).filter(DispatchRecord.id == dispatch_id).first()
    if not dispatch:
        return error_response(code=404, message="派单记录不存在")
    
    if dispatch.dispatch_status != DispatchStatus.PENDING:
        return error_response(code=400, message=f"当前派单状态为{dispatch.dispatch_status.value}，不可确认")
    
    order = db.query(WorkOrder).filter(WorkOrder.id == dispatch.work_order_id).first()
    if not order:
        return error_response(code=404, message="工单不存在")
    
    if order.status in [OrderStatus.COMPLETED, OrderStatus.CLOSED]:
        return error_response(code=400, message="工单已关闭或已完成，不可确认派单")
    
    dispatch.dispatch_status = DispatchStatus.CONFIRMED
    dispatch.confirm_operator = confirm_data.operator
    dispatch.confirm_time = datetime.now()
    
    if order.status == OrderStatus.PENDING:
        order.status = OrderStatus.ASSIGNED
    
    add_progress_record(
        db, dispatch.work_order_id, ProgressType.ASSIGNED,
        operator_name=confirm_data.operator or "系统",
        operator_role="staff",
        remark=f"接单人员确认接单"
    )
    
    db.commit()
    db.refresh(dispatch)
    
    result = orm_to_dict(dispatch)
    staff = db.query(ServiceStaff).filter(ServiceStaff.id == dispatch.staff_id).first()
    result["staff_name"] = staff.name if staff else ""
    
    return success_response(data=result, message="派单已确认")


@router.post("/dispatches/{dispatch_id}/reassign", response_model=ApiResponse)
def reassign_dispatch(
    dispatch_id: int,
    reassign_data: DispatchReassignRequest,
    db: Session = Depends(get_db)
):
    dispatch = db.query(DispatchRecord).filter(DispatchRecord.id == dispatch_id).first()
    if not dispatch:
        return error_response(code=404, message="派单记录不存在")
    
    if dispatch.dispatch_status not in [DispatchStatus.PENDING, DispatchStatus.CONFIRMED]:
        return error_response(code=400, message=f"当前派单状态为{dispatch.dispatch_status.value}，不可改派")
    
    order = db.query(WorkOrder).filter(WorkOrder.id == dispatch.work_order_id).first()
    if not order:
        return error_response(code=404, message="工单不存在")
    
    if order.status in [OrderStatus.COMPLETED, OrderStatus.CLOSED, OrderStatus.INCOMPLETE]:
        return error_response(code=400, message="已关闭或已完成工单不可改派")
    
    new_staff = db.query(ServiceStaff).filter(ServiceStaff.id == reassign_data.new_staff_id).first()
    if not new_staff:
        return error_response(code=404, message="新的接单人员不存在")
    
    if new_staff.status != StaffStatus.ACTIVE:
        return error_response(code=400, message=f"新服务人员状态为{new_staff.status.value}，不可派单")
    
    if dispatch.staff_id == reassign_data.new_staff_id:
        return error_response(code=400, message="改派人员与原人员相同，无需改派")
    
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()
    community = elderly.community if elderly else ""
    
    if not check_skill_match(db, new_staff.id, order.service_type.value):
        return error_response(code=400, message=f"新服务人员不具备{order.service_type.value}服务技能，不可强派")
    
    if community and not check_community_match(db, new_staff.id, community):
        return error_response(code=400, message=f"新服务人员不可服务{community}社区，跨社区不可派单")
    
    if check_time_conflict(db, new_staff.id, order.appointment_start, order.appointment_end):
        return error_response(code=400, message="新服务人员该时间段已有派单，时间冲突")
    
    schedule_date = order.appointment_start.date()
    capacity_ok, daily_load, weekly_load, monthly_load = check_staff_capacity(db, new_staff, schedule_date)
    if not capacity_ok:
        if daily_load >= new_staff.daily_capacity:
            return error_response(code=400, message=f"新服务人员当日容量已满（{daily_load}/{new_staff.daily_capacity}）")
        elif weekly_load >= new_staff.weekly_capacity:
            return error_response(code=400, message=f"新服务人员本周容量已满（{weekly_load}/{new_staff.weekly_capacity}）")
        else:
            return error_response(code=400, message=f"新服务人员本月容量已满（{monthly_load}/{new_staff.monthly_capacity}）")
    
    original_staff_id = dispatch.staff_id
    original_staff = db.query(ServiceStaff).filter(ServiceStaff.id == original_staff_id).first()
    
    dispatch.dispatch_status = DispatchStatus.REASSIGNED
    dispatch.original_staff_id = original_staff_id
    dispatch.reassign_reason = reassign_data.reassign_reason
    dispatch.reassign_operator = reassign_data.operator
    dispatch.reassign_time = datetime.now()
    
    new_dispatch = DispatchRecord(
        work_order_id=dispatch.work_order_id,
        staff_id=reassign_data.new_staff_id,
        dispatch_type=DispatchType.REASSIGN,
        dispatch_status=DispatchStatus.PENDING,
        original_staff_id=original_staff_id,
        reassign_reason=reassign_data.reassign_reason,
        reassign_operator=reassign_data.operator,
        reassign_time=datetime.now(),
        remark=reassign_data.remark
    )
    db.add(new_dispatch)
    db.flush()
    
    order.assignee_name = new_staff.name
    order.assignee_phone = new_staff.phone
    if order.status == OrderStatus.IN_PROGRESS:
        order.status = OrderStatus.ASSIGNED
    
    add_progress_record(
        db, dispatch.work_order_id, ProgressType.ASSIGNED,
        operator_name=reassign_data.operator or "系统",
        operator_role="dispatcher",
        remark=f"改派：由{original_staff.name if original_staff else '原人员'}改为{new_staff.name}，原因：{reassign_data.reassign_reason}"
    )
    
    db.commit()
    db.refresh(new_dispatch)
    
    result = orm_to_dict(new_dispatch)
    result["staff_name"] = new_staff.name
    result["original_staff_name"] = original_staff.name if original_staff else ""
    
    return success_response(data=result, message="改派成功")


@router.post("/dispatches/{dispatch_id}/cancel", response_model=ApiResponse)
def cancel_dispatch(
    dispatch_id: int,
    cancel_data: DispatchCancelRequest,
    db: Session = Depends(get_db)
):
    dispatch = db.query(DispatchRecord).filter(DispatchRecord.id == dispatch_id).first()
    if not dispatch:
        return error_response(code=404, message="派单记录不存在")
    
    if dispatch.dispatch_status not in [DispatchStatus.PENDING, DispatchStatus.CONFIRMED]:
        return error_response(code=400, message=f"当前派单状态为{dispatch.dispatch_status.value}，不可取消")
    
    order = db.query(WorkOrder).filter(WorkOrder.id == dispatch.work_order_id).first()
    if not order:
        return error_response(code=404, message="工单不存在")
    
    if order.status in [OrderStatus.COMPLETED, OrderStatus.CLOSED, OrderStatus.INCOMPLETE]:
        return error_response(code=400, message="已关闭或已完成工单不可取消派单")
    
    if order.status == OrderStatus.IN_PROGRESS:
        return error_response(code=400, message="服务进行中工单不可取消派单，请先释放占用")
    
    dispatch.dispatch_status = DispatchStatus.CANCELLED
    dispatch.cancel_reason = cancel_data.cancel_reason
    dispatch.cancel_operator = cancel_data.operator
    dispatch.cancel_time = datetime.now()
    
    order.assignee_name = None
    order.assignee_phone = None
    if order.status == OrderStatus.ASSIGNED:
        order.status = OrderStatus.PENDING
    
    add_progress_record(
        db, dispatch.work_order_id, ProgressType.CREATED,
        operator_name=cancel_data.operator or "系统",
        operator_role="dispatcher",
        remark=f"取消派单，原因：{cancel_data.cancel_reason}"
    )
    
    db.commit()
    
    return success_response(message="派单已取消，资源已释放")


@router.post("/dispatches/{dispatch_id}/release", response_model=ApiResponse)
def release_dispatch(
    dispatch_id: int,
    release_data: DispatchReleaseRequest,
    db: Session = Depends(get_db)
):
    dispatch = db.query(DispatchRecord).filter(DispatchRecord.id == dispatch_id).first()
    if not dispatch:
        return error_response(code=404, message="派单记录不存在")
    
    if dispatch.dispatch_status not in [DispatchStatus.CONFIRMED]:
        return error_response(code=400, message=f"当前派单状态为{dispatch.dispatch_status.value}，不可释放")
    
    order = db.query(WorkOrder).filter(WorkOrder.id == dispatch.work_order_id).first()
    if not order:
        return error_response(code=404, message="工单不存在")
    
    if order.status in [OrderStatus.COMPLETED, OrderStatus.CLOSED]:
        return error_response(code=400, message="已关闭或已完成工单无需释放资源")
    
    dispatch.dispatch_status = DispatchStatus.RELEASED
    dispatch.release_reason = release_data.release_reason
    dispatch.release_operator = release_data.operator
    dispatch.release_time = datetime.now()
    
    if order.status == OrderStatus.IN_PROGRESS:
        order.status = OrderStatus.ASSIGNED
    
    add_progress_record(
        db, dispatch.work_order_id, ProgressType.CREATED,
        operator_name=release_data.operator or "系统",
        operator_role="staff",
        remark=f"释放资源占用，原因：{release_data.release_reason}"
    )
    
    db.commit()
    
    return success_response(message="资源已释放")


@router.get("/dispatches", response_model=ApiResponse)
def list_dispatches(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    work_order_id: Optional[int] = Query(None, description="工单ID筛选"),
    staff_id: Optional[int] = Query(None, description="人员ID筛选"),
    dispatch_status: Optional[str] = Query(None, description="派单状态筛选"),
    dispatch_type: Optional[str] = Query(None, description="派单类型筛选"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    db: Session = Depends(get_db)
):
    query = db.query(DispatchRecord)
    
    if work_order_id:
        query = query.filter(DispatchRecord.work_order_id == work_order_id)
    if staff_id:
        query = query.filter(DispatchRecord.staff_id == staff_id)
    if dispatch_status:
        try:
            query = query.filter(DispatchRecord.dispatch_status == DispatchStatus(dispatch_status))
        except ValueError:
            return error_response(code=400, message=f"无效的派单状态: {dispatch_status}")
    if dispatch_type:
        try:
            query = query.filter(DispatchRecord.dispatch_type == DispatchType(dispatch_type))
        except ValueError:
            return error_response(code=400, message=f"无效的派单类型: {dispatch_type}")
    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        query = query.filter(DispatchRecord.created_at >= start_dt)
    if end_date:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        query = query.filter(DispatchRecord.created_at < end_dt)
    
    total = query.count()
    dispatches = query.order_by(DispatchRecord.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    items = []
    for d in dispatches:
        d_dict = orm_to_dict(d)
        staff = db.query(ServiceStaff).filter(ServiceStaff.id == d.staff_id).first()
        d_dict["staff_name"] = staff.name if staff else ""
        if d.original_staff_id:
            orig_staff = db.query(ServiceStaff).filter(ServiceStaff.id == d.original_staff_id).first()
            d_dict["original_staff_name"] = orig_staff.name if orig_staff else ""
        order = db.query(WorkOrder).filter(WorkOrder.id == d.work_order_id).first()
        d_dict["order_no"] = order.order_no if order else ""
        items.append(d_dict)
    
    return success_response(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    })


@router.get("/dispatches/{dispatch_id}", response_model=ApiResponse)
def get_dispatch(dispatch_id: int, db: Session = Depends(get_db)):
    dispatch = db.query(DispatchRecord).filter(DispatchRecord.id == dispatch_id).first()
    if not dispatch:
        return error_response(code=404, message="派单记录不存在")
    
    result = orm_to_dict(dispatch)
    staff = db.query(ServiceStaff).filter(ServiceStaff.id == dispatch.staff_id).first()
    result["staff_name"] = staff.name if staff else ""
    result["staff_phone"] = staff.phone if staff else ""
    
    if dispatch.original_staff_id:
        orig_staff = db.query(ServiceStaff).filter(ServiceStaff.id == dispatch.original_staff_id).first()
        result["original_staff_name"] = orig_staff.name if orig_staff else ""
    
    order = db.query(WorkOrder).filter(WorkOrder.id == dispatch.work_order_id).first()
    result["order_no"] = order.order_no if order else ""
    result["order_status"] = order.status.value if order else ""
    result["service_type"] = order.service_type.value if order else ""
    result["appointment_start"] = order.appointment_start if order else None
    result["appointment_end"] = order.appointment_end if order else None
    
    if order:
        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()
        result["elderly_name"] = elderly.name if elderly else ""
        result["community"] = elderly.community if elderly else ""
    
    return success_response(data=result)


@router.get("/dashboard", response_model=ApiResponse)
def resource_dashboard(
    community: Optional[str] = Query(None, description="社区筛选"),
    service_type: Optional[str] = Query(None, description="服务类型筛选"),
    risk_level: Optional[str] = Query(None, description="风险等级筛选"),
    staff_name: Optional[str] = Query(None, description="人员姓名筛选"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    db: Session = Depends(get_db)
):
    now = datetime.now()
    today = date.today()
    
    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    else:
        start_dt = now - timedelta(days=7)
    
    if end_date:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    else:
        end_dt = now + timedelta(days=1)
    
    total_staff = db.query(ServiceStaff).filter(ServiceStaff.status == StaffStatus.ACTIVE).count()
    total_pending_orders = db.query(WorkOrder).filter(WorkOrder.status == OrderStatus.PENDING).count()
    total_assigned_orders = db.query(WorkOrder).filter(
        WorkOrder.status.in_([OrderStatus.ASSIGNED, OrderStatus.IN_PROGRESS])
    ).count()
    
    staff_query = db.query(ServiceStaff).filter(ServiceStaff.status == StaffStatus.ACTIVE)
    if staff_name:
        staff_query = staff_query.filter(ServiceStaff.name.like(f"%{staff_name}%"))
    if community:
        staff_query = staff_query.join(StaffCommunity).filter(StaffCommunity.community == community)
    active_staff_count = staff_query.count()
    
    order_query = db.query(WorkOrder).filter(
        WorkOrder.created_at >= start_dt,
        WorkOrder.created_at < end_dt
    )
    if community:
        order_query = order_query.join(ElderlyProfile).filter(ElderlyProfile.community == community)
    if service_type:
        try:
            order_query = order_query.filter(WorkOrder.service_type == ServiceType(service_type))
        except ValueError:
            return error_response(code=400, message=f"无效的服务类型: {service_type}")
    if risk_level:
        try:
            order_query = order_query.filter(WorkOrder.supervision_risk_level == RiskLevel(risk_level))
        except ValueError:
            return error_response(code=400, message=f"无效的风险等级: {risk_level}")
    period_orders = order_query.count()
    
    summary = {
        "total_active_staff": active_staff_count,
        "total_pending_orders": total_pending_orders,
        "total_in_service": total_assigned_orders,
        "period_orders": period_orders,
        "statistic_range": {
            "start_date": start_dt.strftime("%Y-%m-%d"),
            "end_date": (end_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        }
    }
    
    supply_gap_by_community = []
    all_communities = db.query(func.distinct(ElderlyProfile.community)).filter(
        ElderlyProfile.community.isnot(None),
        ElderlyProfile.community != ""
    ).all()
    community_list = [c[0] for c in all_communities]
    if community:
        community_list = [c for c in community_list if c == community]
    
    for comm in community_list:
        demand_q = db.query(WorkOrder).filter(WorkOrder.status == OrderStatus.PENDING)
        demand_q = demand_q.join(ElderlyProfile).filter(ElderlyProfile.community == comm)
        if service_type:
            try:
                demand_q = demand_q.filter(WorkOrder.service_type == ServiceType(service_type))
            except ValueError:
                pass
        total_demand = demand_q.count()
        
        supply_q = db.query(ServiceStaff).filter(ServiceStaff.status == StaffStatus.ACTIVE)
        supply_q = supply_q.join(StaffCommunity).filter(StaffCommunity.community == comm)
        total_supply = supply_q.count()
        
        gap = total_demand - total_supply
        gap_rate = round(gap / total_demand * 100, 2) if total_demand > 0 else 0
        
        supply_gap_by_community.append({
            "community": comm,
            "total_demand": total_demand,
            "total_supply": total_supply,
            "gap": max(gap, 0),
            "gap_rate": max(gap_rate, 0)
        })
    
    supply_gap_by_community.sort(key=lambda x: x["gap"], reverse=True)
    
    service_type_coverage = []
    for st in ServiceType:
        st_str = st.value
        if service_type and st_str != service_type:
            continue
        
        staff_with_skill = db.query(StaffSkill).filter(
            StaffSkill.skill_tag == st_str
        ).distinct(StaffSkill.staff_id).count()
        
        total_active = db.query(ServiceStaff).filter(
            ServiceStaff.status == StaffStatus.ACTIVE
        ).count()
        
        coverage_rate = round(staff_with_skill / total_active * 100, 2) if total_active > 0 else 0
        
        service_type_coverage.append({
            "service_type": st_str,
            "total_staff": staff_with_skill,
            "coverage_rate": coverage_rate
        })
    
    staff_load_ranking = []
    staffs = db.query(ServiceStaff).filter(ServiceStaff.status == StaffStatus.ACTIVE).all()
    if staff_name:
        staffs = [s for s in staffs if staff_name in s.name]
    
    for staff in staffs:
        today_load = get_staff_daily_load(db, staff.id, today)
        week_load = get_staff_weekly_load(db, staff.id, today)
        
        completed_q = db.query(DispatchRecord).filter(
            DispatchRecord.staff_id == staff.id,
            DispatchRecord.dispatch_status == DispatchStatus.COMPLETED
        )
        completed_count = completed_q.count()
        
        in_progress_q = db.query(DispatchRecord).filter(
            DispatchRecord.staff_id == staff.id,
            DispatchRecord.dispatch_status.in_([DispatchStatus.CONFIRMED, DispatchStatus.PENDING])
        )
        in_progress_count = in_progress_q.count()
        
        primary_comm = db.query(StaffCommunity).filter(
            StaffCommunity.staff_id == staff.id,
            StaffCommunity.is_primary == True
        ).first()
        
        total_load = week_load
        capacity = staff.weekly_capacity
        load_rate = round(total_load / capacity * 100, 2) if capacity > 0 else 0
        
        staff_load_ranking.append({
            "staff_id": staff.id,
            "staff_name": staff.name,
            "community": primary_comm.community if primary_comm else None,
            "completed_orders": completed_count,
            "in_progress_orders": in_progress_count,
            "total_load": total_load,
            "capacity": capacity,
            "load_rate": load_rate
        })
    
    staff_load_ranking.sort(key=lambda x: x["load_rate"], reverse=True)
    staff_load_ranking = staff_load_ranking[:20]
    
    unmatched_orders = []
    unmatched_query = db.query(WorkOrder).filter(WorkOrder.status == OrderStatus.PENDING)
    if community:
        unmatched_query = unmatched_query.join(ElderlyProfile).filter(ElderlyProfile.community == community)
    if service_type:
        try:
            unmatched_query = unmatched_query.filter(WorkOrder.service_type == ServiceType(service_type))
        except ValueError:
            pass
    if risk_level:
        try:
            unmatched_query = unmatched_query.filter(WorkOrder.supervision_risk_level == RiskLevel(risk_level))
        except ValueError:
            pass
    
    unmatched = unmatched_query.order_by(WorkOrder.supervision_priority_score.desc()).all()
    for order in unmatched[:50]:
        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()
        unmatched_orders.append({
            "order_id": order.id,
            "order_no": order.order_no,
            "elderly_id": order.elderly_id,
            "elderly_name": elderly.name if elderly else "",
            "community": elderly.community if elderly else "",
            "service_type": order.service_type.value,
            "appointment_start": order.appointment_start,
            "appointment_end": order.appointment_end,
            "risk_level": order.supervision_risk_level.value if order.supervision_risk_level else None,
            "supervision_priority_score": order.supervision_priority_score,
            "created_at": order.created_at
        })
    
    conflict_dispatches = []
    all_confirmed = db.query(DispatchRecord).filter(
        DispatchRecord.dispatch_status.in_([DispatchStatus.CONFIRMED, DispatchStatus.PENDING])
    ).all()
    
    staff_time_slots = defaultdict(list)
    for d in all_confirmed:
        order = db.query(WorkOrder).filter(WorkOrder.id == d.work_order_id).first()
        if order and order.status not in [OrderStatus.COMPLETED, OrderStatus.CLOSED, OrderStatus.INCOMPLETE]:
            staff_time_slots[d.staff_id].append((order.appointment_start, order.appointment_end, d.id))
    
    conflict_pairs = set()
    for staff_id, slots in staff_time_slots.items():
        slots.sort()
        for i in range(len(slots)):
            for j in range(i + 1, len(slots)):
                if not (slots[i][1] <= slots[j][0] or slots[i][0] >= slots[j][1]):
                    key = tuple(sorted([slots[i][2], slots[j][2]]))
                    if key not in conflict_pairs:
                        conflict_pairs.add(key)
    
    for d1_id, d2_id in conflict_pairs:
        d1 = db.query(DispatchRecord).filter(DispatchRecord.id == d1_id).first()
        d2 = db.query(DispatchRecord).filter(DispatchRecord.id == d2_id).first()
        if d1 and d2:
            staff = db.query(ServiceStaff).filter(ServiceStaff.id == d1.staff_id).first()
            o1 = db.query(WorkOrder).filter(WorkOrder.id == d1.work_order_id).first()
            o2 = db.query(WorkOrder).filter(WorkOrder.id == d2.work_order_id).first()
            
            include = True
            if community:
                e1 = db.query(ElderlyProfile).filter(ElderlyProfile.id == o1.elderly_id).first() if o1 else None
                e2 = db.query(ElderlyProfile).filter(ElderlyProfile.id == o2.elderly_id).first() if o2 else None
                if not ((e1 and e1.community == community) or (e2 and e2.community == community)):
                    include = False
            
            if include:
                conflict_dispatches.append({
                    "staff_id": d1.staff_id,
                    "staff_name": staff.name if staff else "",
                    "dispatch_1": {
                        "dispatch_id": d1.id,
                        "order_id": d1.work_order_id,
                        "order_no": o1.order_no if o1 else "",
                        "start": o1.appointment_start if o1 else None,
                        "end": o1.appointment_end if o1 else None
                    },
                    "dispatch_2": {
                        "dispatch_id": d2.id,
                        "order_id": d2.work_order_id,
                        "order_no": o2.order_no if o2 else "",
                        "start": o2.appointment_start if o2 else None,
                        "end": o2.appointment_end if o2 else None
                    }
                })
    
    capacity_warning_7days = []
    for i in range(7):
        target_date = today + timedelta(days=i)
        date_str = target_date.isoformat()
        
        day_schedules = db.query(StaffSchedule).filter(
            StaffSchedule.schedule_date == target_date,
            StaffSchedule.is_available == True
        ).all()
        
        total_capacity = sum(s.capacity for s in day_schedules)
        if total_capacity == 0:
            active_staff = db.query(ServiceStaff).filter(
                ServiceStaff.status == StaffStatus.ACTIVE
            ).count()
            total_capacity = active_staff * 8
        
        allocated_count = 0
        all_staff = db.query(ServiceStaff).filter(ServiceStaff.status == StaffStatus.ACTIVE).all()
        for s in all_staff:
            allocated_count += get_staff_daily_load(db, s.id, target_date)
        
        remaining = total_capacity - allocated_count
        utilization = round(allocated_count / total_capacity * 100, 2) if total_capacity > 0 else 0
        
        if utilization >= 90:
            warning = "critical"
        elif utilization >= 75:
            warning = "high"
        elif utilization >= 50:
            warning = "medium"
        else:
            warning = "low"
        
        capacity_warning_7days.append({
            "date": date_str,
            "total_capacity": total_capacity,
            "allocated_count": allocated_count,
            "remaining_capacity": max(remaining, 0),
            "utilization_rate": utilization,
            "warning_level": warning
        })
    
    filters = {
        "community": community,
        "service_type": service_type,
        "risk_level": risk_level,
        "staff_name": staff_name,
        "start_date": start_date,
        "end_date": end_date
    }
    
    result = {
        "summary": summary,
        "supply_gap_by_community": supply_gap_by_community,
        "service_type_coverage": service_type_coverage,
        "staff_load_ranking": staff_load_ranking,
        "unmatched_orders": unmatched_orders,
        "conflict_dispatches": conflict_dispatches,
        "capacity_warning_7days": capacity_warning_7days,
        "filters": filters
    }
    
    return success_response(data=result, message="资源看板统计完成")


@router.get("/skills/all", response_model=ApiResponse)
def list_all_skills(db: Session = Depends(get_db)):
    skills = db.query(func.distinct(StaffSkill.skill_tag)).all()
    skill_list = [s[0] for s in skills]
    
    for st in ServiceType:
        if st.value not in skill_list:
            skill_list.append(st.value)
    
    return success_response(data={
        "total": len(skill_list),
        "items": skill_list
    })


@router.get("/communities/all", response_model=ApiResponse)
def list_all_communities(db: Session = Depends(get_db)):
    communities = db.query(func.distinct(ElderlyProfile.community)).filter(
        ElderlyProfile.community.isnot(None),
        ElderlyProfile.community != ""
    ).all()
    comm_list = [c[0] for c in communities]
    
    staff_comms = db.query(func.distinct(StaffCommunity.community)).all()
    for c in staff_comms:
        if c[0] not in comm_list:
            comm_list.append(c[0])
    
    return success_response(data={
        "total": len(comm_list),
        "items": sorted(comm_list)
    })
