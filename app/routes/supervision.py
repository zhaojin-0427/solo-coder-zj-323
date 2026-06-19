from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timedelta, date, time
from collections import Counter, defaultdict

from app.database import get_db
from app.models import (
    WorkOrder, ElderlyProfile, ProgressRecord, SLAConfig, CommunityCalendar,
    HolidayRecord, DuplicateSuggestion, SupervisionRecord, FollowUpPlan,
    VisitRecord, OrderStatus, ServiceType, RiskLevel, ProgressType,
    MergeStatus, SupervisionStatus, VisitStatus, VisitResult
)
from app.schemas import (
    SLAConfigCreate, SLAConfigUpdate, SLAConfigResponse,
    CommunityCalendarCreate, CommunityCalendarUpdate, CommunityCalendarResponse,
    HolidayRecordCreate, HolidayRecordUpdate, HolidayRecordResponse,
    DuplicateSuggestionConfirm, DuplicateSuggestionReject, DuplicateSuggestionResponse,
    SupervisionRecordCreate, SupervisionRecordUpdate, SupervisionRecordResponse,
    FollowUpPlanCreate, FollowUpPlanUpdate, FollowUpPlanResponse,
    VisitRecordCreate, VisitRecordUpdate, VisitRecordResponse,
    OrderEscalationRequest
)
from app.utils import success_response, error_response, ApiResponse, orm_to_dict

router = APIRouter(prefix="/supervision", tags=["闭环督办与风险升级"])


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
                HolidayRecord.community != None if community else True,
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


def get_sla_config(db: Session, service_type: ServiceType) -> SLAConfig:
    config = db.query(SLAConfig).filter(
        SLAConfig.service_type == service_type,
        SLAConfig.is_active == True
    ).first()
    if not config:
        config = SLAConfig(
            service_type=service_type,
            response_hours=2.0,
            resolution_hours=24.0,
            first_response_hours=1.0,
            is_active=True
        )
    return config


def calculate_sla_deadline(db: Session, order: WorkOrder) -> datetime:
    config = get_sla_config(db, order.service_type)
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()
    community = elderly.community if elderly else ""

    deadline = order.appointment_end
    hours_added = 0.0
    current = order.appointment_end

    while hours_added < config.resolution_hours:
        next_hour = current + timedelta(hours=1)
        working = calculate_working_hours(db, community, current, next_hour)
        if working > 0:
            hours_added += working
        current = next_hour

    return current


def check_sla_achieved(db: Session, order: WorkOrder) -> Optional[bool]:
    if not order.completion_time or not order.sla_deadline:
        return None
    return order.completion_time <= order.sla_deadline


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


def generate_follow_up_suggestion(order: WorkOrder, elderly: ElderlyProfile, score: float) -> str:
    suggestions = []

    if order.is_timeout == 1:
        if order.timeout_hours >= 24:
            suggestions.append(f"工单已超时{round(order.timeout_hours, 1)}小时，建议立即联系责任人跟进处理")
        else:
            suggestions.append(f"工单已超时{round(order.timeout_hours, 1)}小时，建议尽快联系服务人员确认进度")

    if elderly and elderly.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
        suggestions.append("老人属于高风险群体，建议安排优先上门核实情况")

    if order.historical_incomplete_count >= 2:
        suggestions.append(f"该老人历史存在{order.historical_incomplete_count}次未完成记录，建议重点关注并查明原因")

    if not order.assignee_name:
        suggestions.append("工单尚未分配接单人员，建议立即派单")

    if score >= 60:
        suggestions.append("督办优先级较高，建议主管介入协调资源")
    elif score >= 30:
        suggestions.append("督办优先级中等，建议按常规流程跟进")

    if not suggestions:
        suggestions.append("工单状态正常，按常规流程处理即可")

    return "；".join(suggestions)


@router.post("/sla-config", response_model=ApiResponse[SLAConfigResponse])
def create_sla_config(config_data: SLAConfigCreate, db: Session = Depends(get_db)):
    existing = db.query(SLAConfig).filter(
        SLAConfig.service_type == config_data.service_type
    ).first()
    if existing:
        return error_response(code=400, message="该服务类型SLA配置已存在，请使用更新接口")

    config = SLAConfig(**config_data.model_dump())
    db.add(config)
    db.commit()
    db.refresh(config)
    return success_response(data=config, message="SLA配置创建成功")


@router.get("/sla-config", response_model=ApiResponse)
def list_sla_configs(
    service_type: Optional[str] = Query(None, description="服务类型筛选"),
    is_active: Optional[bool] = Query(None, description="是否启用"),
    db: Session = Depends(get_db)
):
    query = db.query(SLAConfig)
    if service_type:
        query = query.filter(SLAConfig.service_type == service_type)
    if is_active is not None:
        query = query.filter(SLAConfig.is_active == is_active)

    configs = query.order_by(SLAConfig.id.asc()).all()
    return success_response(data={"total": len(configs), "items": orm_to_dict(configs)})


@router.get("/sla-config/{config_id}", response_model=ApiResponse[SLAConfigResponse])
def get_sla_config(config_id: int, db: Session = Depends(get_db)):
    config = db.query(SLAConfig).filter(SLAConfig.id == config_id).first()
    if not config:
        return error_response(code=404, message="SLA配置不存在")
    return success_response(data=config)


@router.put("/sla-config/{config_id}", response_model=ApiResponse[SLAConfigResponse])
def update_sla_config(config_id: int, config_update: SLAConfigUpdate, db: Session = Depends(get_db)):
    config = db.query(SLAConfig).filter(SLAConfig.id == config_id).first()
    if not config:
        return error_response(code=404, message="SLA配置不存在")

    update_data = config_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(config, key, value)

    db.commit()
    db.refresh(config)
    return success_response(data=config, message="SLA配置更新成功")


@router.post("/community-calendar", response_model=ApiResponse[CommunityCalendarResponse])
def create_community_calendar(calendar_data: CommunityCalendarCreate, db: Session = Depends(get_db)):
    existing = db.query(CommunityCalendar).filter(
        CommunityCalendar.community == calendar_data.community
    ).first()
    if existing:
        return error_response(code=400, message="该社区日历配置已存在，请使用更新接口")

    calendar = CommunityCalendar(**calendar_data.model_dump())
    db.add(calendar)
    db.commit()
    db.refresh(calendar)
    return success_response(data=calendar, message="社区日历配置创建成功")


@router.get("/community-calendar", response_model=ApiResponse)
def list_community_calendars(
    community: Optional[str] = Query(None, description="社区筛选"),
    db: Session = Depends(get_db)
):
    query = db.query(CommunityCalendar)
    if community:
        query = query.filter(CommunityCalendar.community.like(f"%{community}%"))

    calendars = query.order_by(CommunityCalendar.id.asc()).all()
    return success_response(data={"total": len(calendars), "items": orm_to_dict(calendars)})


@router.put("/community-calendar/{calendar_id}", response_model=ApiResponse[CommunityCalendarResponse])
def update_community_calendar(calendar_id: int, calendar_update: CommunityCalendarUpdate, db: Session = Depends(get_db)):
    calendar = db.query(CommunityCalendar).filter(CommunityCalendar.id == calendar_id).first()
    if not calendar:
        return error_response(code=404, message="社区日历配置不存在")

    update_data = calendar_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(calendar, key, value)

    db.commit()
    db.refresh(calendar)
    return success_response(data=calendar, message="社区日历配置更新成功")


@router.post("/holidays", response_model=ApiResponse[HolidayRecordResponse])
def create_holiday(holiday_data: HolidayRecordCreate, db: Session = Depends(get_db)):
    holiday = HolidayRecord(**holiday_data.model_dump())
    db.add(holiday)
    db.commit()
    db.refresh(holiday)
    return success_response(data=holiday, message="节假日记录创建成功")


@router.get("/holidays", response_model=ApiResponse)
def list_holidays(
    community: Optional[str] = Query(None, description="社区筛选"),
    year: Optional[int] = Query(None, description="年份筛选"),
    month: Optional[int] = Query(None, ge=1, le=12, description="月份筛选"),
    db: Session = Depends(get_db)
):
    from sqlalchemy import func

    query = db.query(HolidayRecord)
    if community:
        query = query.filter(HolidayRecord.community == community)
    if year:
        query = query.filter(func.strftime('%Y', HolidayRecord.holiday_date) == str(year))
    if month:
        query = query.filter(func.strftime('%m', HolidayRecord.holiday_date) == f"{month:02d}")

    holidays = query.order_by(HolidayRecord.holiday_date.asc()).all()
    return success_response(data={"total": len(holidays), "items": orm_to_dict(holidays)})


@router.put("/holidays/{holiday_id}", response_model=ApiResponse[HolidayRecordResponse])
def update_holiday(holiday_id: int, holiday_update: HolidayRecordUpdate, db: Session = Depends(get_db)):
    holiday = db.query(HolidayRecord).filter(HolidayRecord.id == holiday_id).first()
    if not holiday:
        return error_response(code=404, message="节假日记录不存在")

    update_data = holiday_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(holiday, key, value)

    db.commit()
    db.refresh(holiday)
    return success_response(data=holiday, message="节假日记录更新成功")


@router.delete("/holidays/{holiday_id}", response_model=ApiResponse)
def delete_holiday(holiday_id: int, db: Session = Depends(get_db)):
    holiday = db.query(HolidayRecord).filter(HolidayRecord.id == holiday_id).first()
    if not holiday:
        return error_response(code=404, message="节假日记录不存在")

    db.delete(holiday)
    db.commit()
    return success_response(message="节假日记录删除成功")


def detect_duplicate_requests_for_window(db: Session, elderly_id: int, service_type: ServiceType, days: int) -> list:
    start_date = datetime.now() - timedelta(days=days)
    orders = db.query(WorkOrder).filter(
        WorkOrder.elderly_id == elderly_id,
        WorkOrder.service_type == service_type,
        WorkOrder.created_at >= start_date,
        WorkOrder.master_order_id == None
    ).order_by(WorkOrder.created_at.asc()).all()

    suggestions = []
    for i in range(len(orders)):
        for j in range(i + 1, len(orders)):
            time_diff = abs((orders[i].created_at - orders[j].created_at).total_seconds())
            if time_diff <= days * 24 * 3600:
                similarity = 1.0 - min(time_diff / (days * 24 * 3600), 1.0)
                master_idx = i if orders[i].created_at <= orders[j].created_at else j
                slave_idx = j if master_idx == i else i

                existing = db.query(DuplicateSuggestion).filter(
                    ((DuplicateSuggestion.master_order_id == orders[master_idx].id) &
                     (DuplicateSuggestion.slave_order_id == orders[slave_idx].id)) |
                    ((DuplicateSuggestion.master_order_id == orders[slave_idx].id) &
                     (DuplicateSuggestion.slave_order_id == orders[master_idx].id))
                ).first()
                if existing and existing.status == MergeStatus.CONFIRMED:
                    continue
                if not existing:
                    suggestion = DuplicateSuggestion(
                        master_order_id=orders[master_idx].id,
                        slave_order_id=orders[slave_idx].id,
                        elderly_id=elderly_id,
                        service_type=service_type,
                        time_window_days=days,
                        similarity_score=round(similarity, 4),
                        status=MergeStatus.SUGGESTED,
                        suggested_by="system"
                    )
                    db.add(suggestion)
                    db.flush()
                    suggestions.append(suggestion)

    return suggestions


@router.post("/detect-duplicates", response_model=ApiResponse)
def detect_duplicates(
    days: int = Query(7, ge=1, le=365, description="时间窗口天数"),
    elderly_id: Optional[int] = Query(None, description="指定老人ID"),
    db: Session = Depends(get_db)
):
    windows = [days] if days not in [7, 15, 30] else [7, 15, 30]

    elderly_query = db.query(ElderlyProfile)
    if elderly_id:
        elderly_query = elderly_query.filter(ElderlyProfile.id == elderly_id)
    elderly_list = elderly_query.all()

    total_suggestions = 0
    for elderly in elderly_list:
        for service_type in ServiceType:
            for w in windows:
                new_suggestions = detect_duplicate_requests_for_window(db, elderly.id, service_type, w)
                total_suggestions += len(new_suggestions)

    db.commit()
    return success_response(data={
        "new_suggestions_count": total_suggestions,
        "message": f"完成{len(elderly_list)}位老人的重复诉求检测，新增{total_suggestions}条合并建议"
    })


@router.get("/duplicate-suggestions", response_model=ApiResponse)
def list_duplicate_suggestions(
    status: Optional[str] = Query(None, description="状态筛选"),
    elderly_id: Optional[int] = Query(None, description="老人ID筛选"),
    service_type: Optional[str] = Query(None, description="服务类型筛选"),
    time_window_days: Optional[int] = Query(None, description="时间窗口天数"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db)
):
    query = db.query(DuplicateSuggestion)
    if status:
        try:
            query = query.filter(DuplicateSuggestion.status == MergeStatus(status))
        except ValueError:
            return error_response(code=400, message=f"无效的状态值: {status}")
    if elderly_id:
        query = query.filter(DuplicateSuggestion.elderly_id == elderly_id)
    if service_type:
        try:
            query = query.filter(DuplicateSuggestion.service_type == ServiceType(service_type))
        except ValueError:
            return error_response(code=400, message=f"无效的服务类型: {service_type}")
    if time_window_days:
        query = query.filter(DuplicateSuggestion.time_window_days == time_window_days)

    total = query.count()
    suggestions = query.order_by(DuplicateSuggestion.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    items = []
    for s in suggestions:
        s_dict = orm_to_dict(s)
        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == s.elderly_id).first()
        s_dict["elderly_name"] = elderly.name if elderly else ""

        master = db.query(WorkOrder).filter(WorkOrder.id == s.master_order_id).first()
        slave = db.query(WorkOrder).filter(WorkOrder.id == s.slave_order_id).first()
        s_dict["master_order_no"] = master.order_no if master else ""
        s_dict["slave_order_no"] = slave.order_no if slave else ""

        items.append(s_dict)

    return success_response(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    })


@router.post("/duplicate-suggestions/{suggestion_id}/confirm", response_model=ApiResponse)
def confirm_duplicate_suggestion(
    suggestion_id: int,
    confirm_data: DuplicateSuggestionConfirm,
    db: Session = Depends(get_db)
):
    suggestion = db.query(DuplicateSuggestion).filter(
        DuplicateSuggestion.id == suggestion_id
    ).first()
    if not suggestion:
        return error_response(code=404, message="合并建议不存在")
    if suggestion.status != MergeStatus.SUGGESTED:
        return error_response(code=400, message=f"当前状态为{suggestion.status}，不可确认")

    suggestion.status = MergeStatus.CONFIRMED
    suggestion.confirmed_by = confirm_data.confirmed_by
    suggestion.confirmed_at = datetime.now()

    master_order = db.query(WorkOrder).filter(WorkOrder.id == suggestion.master_order_id).first()
    slave_order = db.query(WorkOrder).filter(WorkOrder.id == suggestion.slave_order_id).first()

    if master_order and slave_order:
        master_order.is_master_order = True
        slave_order.master_order_id = master_order.id

        add_progress_record(
            db, master_order.id, ProgressType.MERGE_CONFIRMED,
            operator_name=confirm_data.confirmed_by or "系统", operator_role="supervisor",
            remark=f"确认合并工单：{slave_order.order_no}"
        )
        add_progress_record(
            db, slave_order.id, ProgressType.MERGE_CONFIRMED,
            operator_name=confirm_data.confirmed_by or "系统", operator_role="supervisor",
            remark=f"已合并至主工单：{master_order.order_no}"
        )

    db.commit()
    db.refresh(suggestion)
    return success_response(message="合并建议已确认")


@router.post("/duplicate-suggestions/{suggestion_id}/reject", response_model=ApiResponse)
def reject_duplicate_suggestion(
    suggestion_id: int,
    reject_data: DuplicateSuggestionReject,
    db: Session = Depends(get_db)
):
    suggestion = db.query(DuplicateSuggestion).filter(
        DuplicateSuggestion.id == suggestion_id
    ).first()
    if not suggestion:
        return error_response(code=404, message="合并建议不存在")
    if suggestion.status != MergeStatus.SUGGESTED:
        return error_response(code=400, message=f"当前状态为{suggestion.status}，不可拒绝")

    suggestion.status = MergeStatus.REJECTED
    suggestion.reject_reason = reject_data.reject_reason

    db.commit()
    return success_response(message="合并建议已拒绝")


@router.post("/orders/{order_id}/escalate", response_model=ApiResponse)
def escalate_order(
    order_id: int,
    escalation_data: OrderEscalationRequest,
    db: Session = Depends(get_db)
):
    order = db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
    if not order:
        return error_response(code=404, message="工单不存在")

    order.manually_escalated = True
    order.escalation_reason = escalation_data.escalation_reason

    add_progress_record(
        db, order.id, ProgressType.ESCALATION,
        operator_name=escalation_data.operator_name or "系统",
        operator_role="supervisor",
        remark=f"人工确认升级，原因：{escalation_data.escalation_reason}"
    )

    score, risk_level = calculate_supervision_priority(db, order)
    order.supervision_priority_score = score
    order.supervision_risk_level = risk_level

    db.commit()
    db.refresh(order)

    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()
    result = orm_to_dict(order)
    result["elderly_name"] = elderly.name if elderly else ""
    result["supervision_suggestion"] = generate_follow_up_suggestion(order, elderly, score)

    return success_response(data=result, message="工单已人工确认升级")


@router.post("/supervision-records", response_model=ApiResponse[SupervisionRecordResponse])
def create_supervision_record(record_data: SupervisionRecordCreate, db: Session = Depends(get_db)):
    order = db.query(WorkOrder).filter(WorkOrder.id == record_data.work_order_id).first()
    if not order:
        return error_response(code=404, message="工单不存在")

    record = SupervisionRecord(**record_data.model_dump())
    db.add(record)
    db.flush()

    add_progress_record(
        db, order.id, ProgressType.SUPERVISION,
        operator_name=record_data.supervisor_name or "系统",
        operator_role=record_data.supervisor_role or "supervisor",
        remark=f"督办记录：{record_data.supervision_remark}"
    )

    if record_data.is_visited:
        add_progress_record(
            db, order.id, ProgressType.VISIT_COMPLETED,
            operator_name=record_data.supervisor_name or "系统",
            operator_role=record_data.supervisor_role or "supervisor",
            remark="已完成回访"
        )
    elif record_data.next_follow_up_time:
        add_progress_record(
            db, order.id, ProgressType.VISIT_SCHEDULED,
            operator_name=record_data.supervisor_name or "系统",
            operator_role=record_data.supervisor_role or "supervisor",
            remark=f"下次跟进时间：{record_data.next_follow_up_time.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    if record_data.no_follow_up_needed:
        add_progress_record(
            db, order.id, ProgressType.VISIT_SKIPPED,
            operator_name=record_data.supervisor_name or "系统",
            operator_role=record_data.supervisor_role or "supervisor",
            remark=f"无需跟进，原因：{record_data.no_follow_up_reason or '未提供'}"
        )

    db.commit()
    db.refresh(record)
    return success_response(data=record, message="督办记录创建成功")


@router.get("/supervision-records", response_model=ApiResponse)
def list_supervision_records(
    work_order_id: Optional[int] = Query(None, description="工单ID筛选"),
    status: Optional[str] = Query(None, description="状态筛选"),
    is_visited: Optional[bool] = Query(None, description="是否已回访"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db)
):
    query = db.query(SupervisionRecord)
    if work_order_id:
        query = query.filter(SupervisionRecord.work_order_id == work_order_id)
    if status:
        try:
            query = query.filter(SupervisionRecord.status == SupervisionStatus(status))
        except ValueError:
            return error_response(code=400, message=f"无效的状态值: {status}")
    if is_visited is not None:
        query = query.filter(SupervisionRecord.is_visited == is_visited)

    total = query.count()
    records = query.order_by(SupervisionRecord.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return success_response(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": orm_to_dict(records)
    })


@router.put("/supervision-records/{record_id}", response_model=ApiResponse[SupervisionRecordResponse])
def update_supervision_record(
    record_id: int,
    record_update: SupervisionRecordUpdate,
    db: Session = Depends(get_db)
):
    record = db.query(SupervisionRecord).filter(SupervisionRecord.id == record_id).first()
    if not record:
        return error_response(code=404, message="督办记录不存在")

    update_data = record_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(record, key, value)

    db.commit()
    db.refresh(record)
    return success_response(data=record, message="督办记录更新成功")


@router.post("/follow-up-plans", response_model=ApiResponse[FollowUpPlanResponse])
def create_follow_up_plan(plan_data: FollowUpPlanCreate, db: Session = Depends(get_db)):
    order = db.query(WorkOrder).filter(WorkOrder.id == plan_data.work_order_id).first()
    if not order:
        return error_response(code=404, message="工单不存在")

    plan = FollowUpPlan(**plan_data.model_dump())
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return success_response(data=plan, message="跟进计划创建成功")


@router.get("/follow-up-plans", response_model=ApiResponse)
def list_follow_up_plans(
    work_order_id: Optional[int] = Query(None, description="工单ID筛选"),
    is_completed: Optional[bool] = Query(None, description="是否完成"),
    responsible_person: Optional[str] = Query(None, description="责任人筛选"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db)
):
    query = db.query(FollowUpPlan)
    if work_order_id:
        query = query.filter(FollowUpPlan.work_order_id == work_order_id)
    if is_completed is not None:
        query = query.filter(FollowUpPlan.is_completed == is_completed)
    if responsible_person:
        query = query.filter(FollowUpPlan.responsible_person.like(f"%{responsible_person}%"))

    total = query.count()
    plans = query.order_by(FollowUpPlan.planned_time.asc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return success_response(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": orm_to_dict(plans)
    })


@router.put("/follow-up-plans/{plan_id}", response_model=ApiResponse[FollowUpPlanResponse])
def update_follow_up_plan(
    plan_id: int,
    plan_update: FollowUpPlanUpdate,
    db: Session = Depends(get_db)
):
    plan = db.query(FollowUpPlan).filter(FollowUpPlan.id == plan_id).first()
    if not plan:
        return error_response(code=404, message="跟进计划不存在")

    update_data = plan_update.model_dump(exclude_unset=True)
    if "is_completed" in update_data and update_data["is_completed"] and not plan.is_completed:
        update_data["completed_time"] = update_data.get("completed_time") or datetime.now()

    for key, value in update_data.items():
        setattr(plan, key, value)

    db.commit()
    db.refresh(plan)
    return success_response(data=plan, message="跟进计划更新成功")


@router.delete("/follow-up-plans/{plan_id}", response_model=ApiResponse)
def delete_follow_up_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.query(FollowUpPlan).filter(FollowUpPlan.id == plan_id).first()
    if not plan:
        return error_response(code=404, message="跟进计划不存在")

    db.delete(plan)
    db.commit()
    return success_response(message="跟进计划删除成功")


@router.post("/visit-records", response_model=ApiResponse[VisitRecordResponse])
def create_visit_record(record_data: VisitRecordCreate, db: Session = Depends(get_db)):
    order = db.query(WorkOrder).filter(WorkOrder.id == record_data.work_order_id).first()
    if not order:
        return error_response(code=404, message="工单不存在")

    record = VisitRecord(**record_data.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return success_response(data=record, message="回访记录创建成功")


@router.get("/visit-records", response_model=ApiResponse)
def list_visit_records(
    work_order_id: Optional[int] = Query(None, description="工单ID筛选"),
    visit_status: Optional[str] = Query(None, description="回访状态筛选"),
    visit_result: Optional[str] = Query(None, description="回访结果筛选"),
    archived: Optional[bool] = Query(None, description="是否归档"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db)
):
    query = db.query(VisitRecord)
    if work_order_id:
        query = query.filter(VisitRecord.work_order_id == work_order_id)
    if visit_status:
        try:
            query = query.filter(VisitRecord.visit_status == VisitStatus(visit_status))
        except ValueError:
            return error_response(code=400, message=f"无效的回访状态值: {visit_status}")
    if visit_result:
        try:
            query = query.filter(VisitRecord.visit_result == VisitResult(visit_result))
        except ValueError:
            return error_response(code=400, message=f"无效的回访结果值: {visit_result}")
    if archived is not None:
        query = query.filter(VisitRecord.archived == archived)

    total = query.count()
    records = query.order_by(VisitRecord.visit_time.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return success_response(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": orm_to_dict(records)
    })


@router.put("/visit-records/{record_id}", response_model=ApiResponse[VisitRecordResponse])
def update_visit_record(
    record_id: int,
    record_update: VisitRecordUpdate,
    db: Session = Depends(get_db)
):
    record = db.query(VisitRecord).filter(VisitRecord.id == record_id).first()
    if not record:
        return error_response(code=404, message="回访记录不存在")

    update_data = record_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(record, key, value)

    db.commit()
    db.refresh(record)
    return success_response(data=record, message="回访记录更新成功")


@router.post("/visit-records/{record_id}/archive", response_model=ApiResponse)
def archive_visit_record(record_id: int, db: Session = Depends(get_db)):
    record = db.query(VisitRecord).filter(VisitRecord.id == record_id).first()
    if not record:
        return error_response(code=404, message="回访记录不存在")

    record.archived = True
    db.commit()
    return success_response(message="回访记录已归档")


@router.get("/orders/{order_id}/priority", response_model=ApiResponse)
def get_order_priority(order_id: int, db: Session = Depends(get_db)):
    order = db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
    if not order:
        return error_response(code=404, message="工单不存在")

    now = datetime.now()
    if order.status in [OrderStatus.PENDING, OrderStatus.ASSIGNED, OrderStatus.IN_PROGRESS]:
        if now > order.appointment_end:
            timeout_delta = now - order.appointment_end
            order.timeout_hours = round(timeout_delta.total_seconds() / 3600, 2)
            order.is_timeout = 1
        else:
            order.is_timeout = 0
            order.timeout_hours = 0

    if not order.sla_deadline:
        order.sla_deadline = calculate_sla_deadline(db, order)

    score, risk_level = calculate_supervision_priority(db, order)
    order.supervision_priority_score = score
    order.supervision_risk_level = risk_level

    if order.completion_time and order.sla_deadline:
        order.sla_achieved = order.completion_time <= order.sla_deadline

    db.commit()
    db.refresh(order)

    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()

    supervision_records = db.query(SupervisionRecord).filter(
        SupervisionRecord.work_order_id == order_id
    ).order_by(SupervisionRecord.created_at.desc()).all()

    follow_up_plans = db.query(FollowUpPlan).filter(
        FollowUpPlan.work_order_id == order_id
    ).order_by(FollowUpPlan.planned_time.asc()).all()

    visit_records = db.query(VisitRecord).filter(
        VisitRecord.work_order_id == order_id
    ).order_by(VisitRecord.visit_time.desc()).all()

    merge_suggestions = db.query(DuplicateSuggestion).filter(
        (DuplicateSuggestion.master_order_id == order_id) |
        (DuplicateSuggestion.slave_order_id == order_id)
    ).order_by(DuplicateSuggestion.created_at.desc()).all()

    merged_orders = []
    if order.is_master_order:
        slaves = db.query(WorkOrder).filter(WorkOrder.master_order_id == order_id).all()
        for s in slaves:
            merged_orders.append({
                "id": s.id,
                "order_no": s.order_no,
                "status": s.status,
                "created_at": s.created_at
            })

    return success_response(data={
        "order_id": order.id,
        "order_no": order.order_no,
        "elderly_id": order.elderly_id,
        "elderly_name": elderly.name if elderly else "",
        "supervision_priority_score": score,
        "supervision_risk_level": risk_level,
        "sla_deadline": order.sla_deadline,
        "sla_achieved": order.sla_achieved,
        "is_timeout": order.is_timeout,
        "timeout_hours": order.timeout_hours,
        "historical_incomplete_count": order.historical_incomplete_count,
        "manually_escalated": order.manually_escalated,
        "escalation_reason": order.escalation_reason,
        "follow_up_suggestion": generate_follow_up_suggestion(order, elderly, score),
        "is_master_order": order.is_master_order,
        "master_order_id": order.master_order_id,
        "merged_orders": merged_orders,
        "supervision_records_count": len(supervision_records),
        "follow_up_plans_count": len(follow_up_plans),
        "visit_records_count": len(visit_records),
        "merge_suggestions_count": len(merge_suggestions)
    })


@router.get("/high-risk-orders", response_model=ApiResponse)
def get_high_risk_orders(
    risk_level: Optional[str] = Query(None, description="风险等级筛选"),
    community: Optional[str] = Query(None, description="社区筛选"),
    service_type: Optional[str] = Query(None, description="服务类型筛选"),
    only_timeout: Optional[bool] = Query(False, description="仅显示超时工单"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db)
):
    now = datetime.now()
    all_pending = db.query(WorkOrder).filter(
        WorkOrder.status.in_([OrderStatus.PENDING, OrderStatus.ASSIGNED, OrderStatus.IN_PROGRESS])
    ).all()

    for order in all_pending:
        if now > order.appointment_end:
            timeout_delta = now - order.appointment_end
            order.timeout_hours = round(timeout_delta.total_seconds() / 3600, 2)
            order.is_timeout = 1
        else:
            order.is_timeout = 0
            order.timeout_hours = 0

        if not order.sla_deadline:
            order.sla_deadline = calculate_sla_deadline(db, order)

        score, rl = calculate_supervision_priority(db, order)
        order.supervision_priority_score = score
        order.supervision_risk_level = rl

    db.commit()

    query = db.query(WorkOrder).filter(
        WorkOrder.status.in_([OrderStatus.PENDING, OrderStatus.ASSIGNED, OrderStatus.IN_PROGRESS])
    )

    if risk_level:
        try:
            query = query.filter(WorkOrder.supervision_risk_level == RiskLevel(risk_level))
        except ValueError:
            return error_response(code=400, message=f"无效的风险等级值: {risk_level}")
    if community:
        query = query.join(ElderlyProfile).filter(ElderlyProfile.community == community)
    if service_type:
        try:
            query = query.filter(WorkOrder.service_type == ServiceType(service_type))
        except ValueError:
            return error_response(code=400, message=f"无效的服务类型: {service_type}")
    if only_timeout:
        query = query.filter(WorkOrder.is_timeout == 1)

    total = query.count()
    orders = query.order_by(WorkOrder.supervision_priority_score.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    items = []
    for order in orders:
        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()
        items.append({
            "id": order.id,
            "order_no": order.order_no,
            "elderly_id": order.elderly_id,
            "elderly_name": elderly.name if elderly else "",
            "community": elderly.community if elderly else "",
            "service_type": order.service_type,
            "status": order.status,
            "appointment_end": order.appointment_end,
            "is_timeout": order.is_timeout,
            "timeout_hours": order.timeout_hours,
            "supervision_priority_score": order.supervision_priority_score,
            "supervision_risk_level": order.supervision_risk_level,
            "assignee_name": order.assignee_name,
            "manually_escalated": order.manually_escalated,
            "follow_up_suggestion": generate_follow_up_suggestion(order, elderly, order.supervision_priority_score)
        })

    return success_response(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    })
