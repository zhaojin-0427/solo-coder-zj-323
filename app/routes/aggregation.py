from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timedelta
from collections import Counter, defaultdict

from app.database import get_db
from app.models import (
    WorkOrder, ElderlyProfile, ProgressRecord,
    OrderStatus, ServiceType, RiskLevel,
    DuplicateSuggestion, MergeStatus, SupervisionRecord,
    SLAConfig
)
from app.utils import success_response, error_response, ApiResponse, orm_to_dict

router = APIRouter(prefix="/aggregation", tags=["聚合分析"])


def calculate_follow_up_suggestion(elderly: ElderlyProfile, orders: list) -> str:
    suggestions = []
    
    if elderly.risk_level == RiskLevel.HIGH or elderly.risk_level == RiskLevel.CRITICAL:
        suggestions.append("高风险老人，建议每周至少上门探访1次")
    elif elderly.risk_level == RiskLevel.MEDIUM:
        suggestions.append("中风险老人，建议每两周上门探访1次")
    
    recent_orders = [o for o in orders if (datetime.now() - o.created_at).days <= 30]
    if len(recent_orders) >= 3:
        suggestions.append(f"近30天服务{len(recent_orders)}次，求助频次较高，建议重点关注")
    
    incomplete_orders = [o for o in orders if o.status == OrderStatus.INCOMPLETE]
    if incomplete_orders:
        reasons = [o.incomplete_reason for o in incomplete_orders if o.incomplete_reason]
        if reasons:
            suggestions.append(f"存在{len(incomplete_orders)}个未完成工单，需跟进处理未完成原因")
    
    service_types = Counter([o.service_type.value for o in orders])
    if service_types:
        top_type = service_types.most_common(1)[0]
        suggestions.append(f"主要诉求类型为{top_type[0]}，可针对性安排服务资源")
    
    if elderly.health_condition and "慢病" in elderly.health_condition:
        suggestions.append("老人有慢性病史，建议定期跟进健康状况")
    
    if not suggestions:
        suggestions.append("老人状况稳定，按常规服务计划执行即可")
    
    return "；".join(suggestions)


@router.get("/elderly/{elderly_id}", response_model=ApiResponse)
def get_elderly_aggregation(
    elderly_id: int,
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    db: Session = Depends(get_db)
):
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == elderly_id).first()
    if not elderly:
        return error_response(code=404, message="老人档案不存在")
    
    start_date = datetime.now() - timedelta(days=days)
    orders = db.query(WorkOrder).filter(
        WorkOrder.elderly_id == elderly_id,
        WorkOrder.created_at >= start_date
    ).order_by(WorkOrder.created_at.desc()).all()
    
    duplicate_requests = detect_duplicate_requests(db, elderly_id, days)
    
    total_orders = len(orders)
    completed_orders = len([o for o in orders if o.status in [OrderStatus.COMPLETED, OrderStatus.CLOSED]])
    pending_orders = len([o for o in orders if o.status in [OrderStatus.PENDING, OrderStatus.ASSIGNED, OrderStatus.IN_PROGRESS]])
    
    order_items = []
    for order in orders:
        order_dict = orm_to_dict(order)
        order_dict["elderly_name"] = elderly.name
        order_items.append(order_dict)
    
    follow_up_suggestion = calculate_follow_up_suggestion(elderly, orders)
    
    result = {
        "elderly_id": elderly.id,
        "elderly_name": elderly.name,
        "risk_level": elderly.risk_level,
        "community": elderly.community,
        "total_orders": total_orders,
        "completed_orders": completed_orders,
        "pending_orders": pending_orders,
        "recent_orders": order_items,
        "duplicate_requests": duplicate_requests,
        "follow_up_suggestion": follow_up_suggestion
    }
    
    return success_response(data=result)


def detect_duplicate_requests(db: Session, elderly_id: int, days: int) -> list:
    start_date = datetime.now() - timedelta(days=days)
    orders = db.query(WorkOrder).filter(
        WorkOrder.elderly_id == elderly_id,
        WorkOrder.created_at >= start_date
    ).order_by(WorkOrder.created_at.desc()).all()
    
    duplicates = []
    service_type_groups = defaultdict(list)
    
    for order in orders:
        service_type_groups[order.service_type.value].append(order)
    
    for service_type, type_orders in service_type_groups.items():
        if len(type_orders) >= 2:
            for i in range(len(type_orders)):
                for j in range(i + 1, len(type_orders)):
                    time_diff = abs((type_orders[i].created_at - type_orders[j].created_at).total_seconds())
                    if time_diff <= 7 * 24 * 3600:
                        duplicates.append({
                            "service_type": service_type,
                            "order_1": {
                                "id": type_orders[i].id,
                                "order_no": type_orders[i].order_no,
                                "created_at": type_orders[i].created_at,
                                "status": type_orders[i].status
                            },
                            "order_2": {
                                "id": type_orders[j].id,
                                "order_no": type_orders[j].order_no,
                                "created_at": type_orders[j].created_at,
                                "status": type_orders[j].status
                            },
                            "time_diff_hours": round(time_diff / 3600, 2),
                            "description": f"7天内重复申请{service_type}服务，间隔{round(time_diff / 3600, 1)}小时"
                        })
    
    return duplicates


@router.get("/duplicate-requests", response_model=ApiResponse)
def get_duplicate_requests(
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    db: Session = Depends(get_db)
):
    start_date = datetime.now() - timedelta(days=days)
    
    elderly_list = db.query(ElderlyProfile).all()
    all_duplicates = []
    
    for elderly in elderly_list:
        duplicates = detect_duplicate_requests(db, elderly.id, days)
        if duplicates:
            all_duplicates.append({
                "elderly_id": elderly.id,
                "elderly_name": elderly.name,
                "community": elderly.community,
                "duplicate_count": len(duplicates),
                "duplicate_details": duplicates
            })
    
    all_duplicates.sort(key=lambda x: x["duplicate_count"], reverse=True)
    
    return success_response(data={
        "total_elderly": len(all_duplicates),
        "total_duplicates": sum(d["duplicate_count"] for d in all_duplicates),
        "items": all_duplicates
    })


@router.get("/timeout-orders", response_model=ApiResponse)
def get_timeout_orders(
    status: Optional[str] = Query(None, description="工单状态筛选"),
    community: Optional[str] = Query(None, description="社区筛选"),
    db: Session = Depends(get_db)
):
    now = datetime.now()
    query = db.query(WorkOrder).filter(
        WorkOrder.status.in_([OrderStatus.PENDING, OrderStatus.ASSIGNED, OrderStatus.IN_PROGRESS])
    )
    
    if status:
        query = query.filter(WorkOrder.status == status)
    
    all_orders = query.all()
    
    timeout_orders = []
    for order in all_orders:
        if now > order.appointment_end:
            time_diff = now - order.appointment_end
            timeout_hours = round(time_diff.total_seconds() / 3600, 2)
            order.is_timeout = 1
            order.timeout_hours = timeout_hours
            timeout_orders.append(order)
        else:
            order.is_timeout = 0
            order.timeout_hours = 0
    
    db.commit()
    
    result_items = []
    for order in timeout_orders:
        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()
        
        if community and elderly and elderly.community != community:
            continue
        
        result_items.append({
            "id": order.id,
            "order_no": order.order_no,
            "elderly_id": order.elderly_id,
            "elderly_name": elderly.name if elderly else "",
            "community": elderly.community if elderly else "",
            "service_type": order.service_type,
            "appointment_end": order.appointment_end,
            "status": order.status,
            "timeout_hours": order.timeout_hours,
            "assignee_name": order.assignee_name,
            "risk_remark": order.risk_remark
        })
    
    result_items.sort(key=lambda x: x["timeout_hours"], reverse=True)
    
    return success_response(data={
        "total": len(result_items),
        "items": result_items
    })


@router.get("/statistics", response_model=ApiResponse)
def get_statistics(
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    db: Session = Depends(get_db)
):
    start_date = datetime.now() - timedelta(days=days)
    now = datetime.now()
    
    all_orders = db.query(WorkOrder).filter(WorkOrder.created_at >= start_date).all()
    all_elderly = db.query(ElderlyProfile).all()
    
    for order in all_orders:
        if order.status in [OrderStatus.PENDING, OrderStatus.ASSIGNED, OrderStatus.IN_PROGRESS]:
            if now > order.appointment_end:
                time_diff = now - order.appointment_end
                order.is_timeout = 1
                order.timeout_hours = round(time_diff.total_seconds() / 3600, 2)
            else:
                order.is_timeout = 0
                order.timeout_hours = 0
    
    db.commit()
    
    total_orders = len(all_orders)
    completed_orders = len([o for o in all_orders if o.status in [OrderStatus.COMPLETED, OrderStatus.CLOSED]])
    pending_orders = len([o for o in all_orders if o.status in [OrderStatus.PENDING, OrderStatus.ASSIGNED, OrderStatus.IN_PROGRESS]])
    timeout_orders = len([o for o in all_orders if o.is_timeout == 1])
    
    completion_rate = round(completed_orders / total_orders * 100, 2) if total_orders > 0 else 0
    
    service_type_stats = []
    for service_type in ServiceType:
        type_orders = [o for o in all_orders if o.service_type == service_type]
        type_completed = [o for o in type_orders if o.status in [OrderStatus.COMPLETED, OrderStatus.CLOSED]]
        
        avg_hours = 0
        if type_completed:
            durations = []
            for o in type_completed:
                if o.completion_time and o.created_at:
                    duration = (o.completion_time - o.created_at).total_seconds() / 3600
                    durations.append(duration)
            if durations:
                avg_hours = round(sum(durations) / len(durations), 2)
        
        type_completion_rate = round(len(type_completed) / len(type_orders) * 100, 2) if len(type_orders) > 0 else 0
        
        service_type_stats.append({
            "service_type": service_type.value,
            "total_orders": len(type_orders),
            "completed_orders": len(type_completed),
            "avg_completion_hours": avg_hours,
            "completion_rate": type_completion_rate
        })
    
    elderly_order_counts = Counter()
    for order in all_orders:
        elderly_order_counts[order.elderly_id] += 1
    
    duplicate_count = sum(1 for count in elderly_order_counts.values() if count >= 2)
    total_elderly_with_orders = len(elderly_order_counts)
    duplicate_request_rate = round(duplicate_count / total_elderly_with_orders * 100, 2) if total_elderly_with_orders > 0 else 0
    
    timeout_distribution = []
    timeout_ranges = [
        ("0-2小时", 0, 2),
        ("2-6小时", 2, 6),
        ("6-12小时", 6, 12),
        ("12-24小时", 12, 24),
        ("24小时以上", 24, float('inf'))
    ]
    for label, min_h, max_h in timeout_ranges:
        count = len([o for o in all_orders if o.is_timeout == 1 and min_h <= o.timeout_hours < max_h])
        timeout_distribution.append({
            "range": label,
            "count": count
        })
    
    high_freq_elderly = []
    sorted_elderly = elderly_order_counts.most_common(10)
    for elderly_id, order_count in sorted_elderly:
        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == elderly_id).first()
        if elderly:
            elderly_orders = [o for o in all_orders if o.elderly_id == elderly_id]
            completed = len([o for o in elderly_orders if o.status in [OrderStatus.COMPLETED, OrderStatus.CLOSED]])
            
            type_counts = Counter([o.service_type.value for o in elderly_orders])
            top_types = [t for t, c in type_counts.most_common(3)]
            
            high_freq_elderly.append({
                "elderly_id": elderly.id,
                "elderly_name": elderly.name,
                "community": elderly.community,
                "risk_level": elderly.risk_level,
                "order_count": order_count,
                "completed_count": completed,
                "top_service_types": top_types,
                "follow_up_suggestion": calculate_follow_up_suggestion(elderly, elderly_orders)
            })
    
    result = {
        "statistic_days": days,
        "total_orders": total_orders,
        "completed_orders": completed_orders,
        "pending_orders": pending_orders,
        "timeout_orders": timeout_orders,
        "completion_rate": completion_rate,
        "service_type_stats": service_type_stats,
        "duplicate_request_rate": duplicate_request_rate,
        "timeout_distribution": timeout_distribution,
        "high_frequency_elderly": high_freq_elderly
    }
    
    return success_response(data=result)


@router.get("/follow-up-suggestions", response_model=ApiResponse)
def get_follow_up_suggestions(
    risk_level: Optional[str] = Query(None, description="风险等级筛选"),
    community: Optional[str] = Query(None, description="社区筛选"),
    db: Session = Depends(get_db)
):
    query = db.query(ElderlyProfile)
    if risk_level:
        query = query.filter(ElderlyProfile.risk_level == risk_level)
    if community:
        query = query.filter(ElderlyProfile.community == community)
    
    elderly_list = query.all()
    
    suggestions_list = []
    for elderly in elderly_list:
        recent_orders = db.query(WorkOrder).filter(
            WorkOrder.elderly_id == elderly.id,
            WorkOrder.created_at >= datetime.now() - timedelta(days=30)
        ).order_by(WorkOrder.created_at.desc()).all()
        
        suggestion = calculate_follow_up_suggestion(elderly, recent_orders)
        priority_score = 0
        
        if elderly.risk_level == RiskLevel.CRITICAL:
            priority_score += 40
        elif elderly.risk_level == RiskLevel.HIGH:
            priority_score += 30
        elif elderly.risk_level == RiskLevel.MEDIUM:
            priority_score += 15
        
        order_count = len(recent_orders)
        if order_count >= 5:
            priority_score += 30
        elif order_count >= 3:
            priority_score += 20
        elif order_count >= 2:
            priority_score += 10
        
        incomplete_count = len([o for o in recent_orders if o.status == OrderStatus.INCOMPLETE])
        priority_score += incomplete_count * 10
        
        timeout_count = len([o for o in recent_orders if o.is_timeout == 1])
        priority_score += timeout_count * 15
        
        suggestions_list.append({
            "elderly_id": elderly.id,
            "elderly_name": elderly.name,
            "community": elderly.community,
            "risk_level": elderly.risk_level,
            "phone": elderly.phone,
            "address": elderly.address,
            "recent_order_count": order_count,
            "incomplete_count": incomplete_count,
            "priority_score": priority_score,
            "follow_up_suggestion": suggestion,
            "emergency_contact": elderly.emergency_contact_name,
            "emergency_phone": elderly.emergency_contact_phone
        })
    
    suggestions_list.sort(key=lambda x: x["priority_score"], reverse=True)
    
    return success_response(data={
        "total": len(suggestions_list),
        "items": suggestions_list
    })


@router.get("/advanced-statistics", response_model=ApiResponse)
def get_advanced_statistics(
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    community: Optional[str] = Query(None, description="社区筛选"),
    service_type: Optional[str] = Query(None, description="服务类型筛选"),
    risk_level: Optional[str] = Query(None, description="风险等级筛选"),
    db: Session = Depends(get_db)
):
    now = datetime.now()

    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    else:
        start_dt = now - timedelta(days=30)

    if end_date:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    else:
        end_dt = now + timedelta(days=1)

    order_query = db.query(WorkOrder).filter(
        WorkOrder.created_at >= start_dt,
        WorkOrder.created_at < end_dt
    )

    if community:
        order_query = order_query.join(ElderlyProfile).filter(ElderlyProfile.community == community)
    if service_type:
        order_query = order_query.filter(WorkOrder.service_type == service_type)

    all_orders = order_query.all()

    for order in all_orders:
        if order.status in [OrderStatus.PENDING, OrderStatus.ASSIGNED, OrderStatus.IN_PROGRESS]:
            if now > order.appointment_end:
                time_diff = now - order.appointment_end
                order.is_timeout = 1
                order.timeout_hours = round(time_diff.total_seconds() / 3600, 2)
            else:
                order.is_timeout = 0
                order.timeout_hours = 0

    db.commit()

    total_orders = len(all_orders)
    completed_orders = [o for o in all_orders if o.status in [OrderStatus.COMPLETED, OrderStatus.CLOSED]]
    completed_count = len(completed_orders)

    sla_deadline_count = len([o for o in completed_orders if o.sla_deadline])
    sla_achieved_count = len([o for o in completed_orders if o.sla_achieved == True])
    sla_achievement_rate = round(sla_achieved_count / sla_deadline_count * 100, 2) if sla_deadline_count > 0 else 0

    all_suggestions_query = db.query(DuplicateSuggestion).filter(
        DuplicateSuggestion.created_at >= start_dt,
        DuplicateSuggestion.created_at < end_dt
    )
    if community:
        all_suggestions_query = all_suggestions_query.join(
            ElderlyProfile, DuplicateSuggestion.elderly_id == ElderlyProfile.id
        ).filter(ElderlyProfile.community == community)
    all_suggestions = all_suggestions_query.all()

    total_suggestions = len(all_suggestions)
    confirmed_suggestions = len([s for s in all_suggestions if s.status == MergeStatus.CONFIRMED])
    duplicate_confirmation_rate = round(
        confirmed_suggestions / total_suggestions * 100, 2
    ) if total_suggestions > 0 else 0

    risk_distribution = []
    for rl in [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]:
        count = len([o for o in all_orders if o.supervision_risk_level == rl])
        manually = len([o for o in all_orders if o.supervision_risk_level == rl and o.manually_escalated])
        risk_distribution.append({
            "risk_level": rl.value,
            "order_count": count,
            "manually_escalated_count": manually,
            "percentage": round(count / total_orders * 100, 2) if total_orders > 0 else 0
        })

    supervision_query = db.query(SupervisionRecord).filter(
        SupervisionRecord.created_at >= start_dt,
        SupervisionRecord.created_at < end_dt
    )
    if community:
        supervision_query = supervision_query.join(
            WorkOrder, SupervisionRecord.work_order_id == WorkOrder.id
        ).join(ElderlyProfile).filter(ElderlyProfile.community == community)
    all_supervisions = supervision_query.all()

    supervision_durations = []
    for sr in all_supervisions:
        if sr.status.value in ["resolved", "closed"] and sr.updated_at and sr.created_at:
            duration = (sr.updated_at - sr.created_at).total_seconds() / 3600
            supervision_durations.append(duration)

    avg_supervision_hours = round(sum(supervision_durations) / len(supervision_durations), 2) if supervision_durations else 0
    supervision_total = len(all_supervisions)
    supervision_resolved = len([s for s in all_supervisions if s.status.value in ["resolved", "closed"]])

    community_timeout_heatmap = []
    community_orders = defaultdict(list)
    for order in all_orders:
        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()
        if elderly and elderly.community:
            community_orders[elderly.community].append(order)

    for comm, orders in community_orders.items():
        total = len(orders)
        timeout = len([o for o in orders if o.is_timeout == 1])
        avg_timeout_hours = round(
            sum([o.timeout_hours for o in orders if o.is_timeout == 1]) / timeout, 2
        ) if timeout > 0 else 0
        sla_met = len([o for o in orders if o.sla_achieved == True])
        community_timeout_heatmap.append({
            "community": comm,
            "total_orders": total,
            "timeout_orders": timeout,
            "timeout_rate": round(timeout / total * 100, 2) if total > 0 else 0,
            "avg_timeout_hours": avg_timeout_hours,
            "sla_achieved_count": sla_met,
            "sla_achievement_rate": round(sla_met / total * 100, 2) if total > 0 else 0,
            "heat_level": "critical" if timeout >= 10 else ("high" if timeout >= 5 else ("medium" if timeout >= 2 else "low"))
        })

    community_timeout_heatmap.sort(key=lambda x: x["timeout_orders"], reverse=True)

    high_risk_pending = []
    pending_orders = [o for o in all_orders if o.status in [OrderStatus.PENDING, OrderStatus.ASSIGNED, OrderStatus.IN_PROGRESS]]

    if risk_level:
        pending_orders = [o for o in pending_orders if o.supervision_risk_level and o.supervision_risk_level.value == risk_level]
    else:
        pending_orders = [o for o in pending_orders if o.supervision_risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]]

    pending_orders.sort(key=lambda x: x.supervision_priority_score or 0, reverse=True)

    for order in pending_orders[:50]:
        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()

        recent_supervisions = db.query(SupervisionRecord).filter(
            SupervisionRecord.work_order_id == order.id
        ).order_by(SupervisionRecord.created_at.desc()).limit(3).all()

        high_risk_pending.append({
            "order_id": order.id,
            "order_no": order.order_no,
            "elderly_id": order.elderly_id,
            "elderly_name": elderly.name if elderly else "",
            "community": elderly.community if elderly else "",
            "risk_level": elderly.risk_level.value if elderly and elderly.risk_level else None,
            "service_type": order.service_type.value,
            "status": order.status.value,
            "appointment_end": order.appointment_end,
            "is_timeout": order.is_timeout,
            "timeout_hours": order.timeout_hours,
            "supervision_priority_score": order.supervision_priority_score,
            "supervision_risk_level": order.supervision_risk_level.value if order.supervision_risk_level else None,
            "assignee_name": order.assignee_name,
            "manually_escalated": order.manually_escalated,
            "historical_incomplete_count": order.historical_incomplete_count,
            "recent_supervision_count": len(recent_supervisions),
            "last_supervision_time": recent_supervisions[0].created_at if recent_supervisions else None,
            "follow_up_suggestion": order.follow_up_suggestion
        })

    service_type_sla_stats = []
    for st in ServiceType:
        type_orders = [o for o in all_orders if o.service_type == st]
        type_completed = [o for o in type_orders if o.status in [OrderStatus.COMPLETED, OrderStatus.CLOSED]]
        type_sla_met = len([o for o in type_completed if o.sla_achieved == True])
        type_sla_total = len([o for o in type_completed if o.sla_deadline])

        avg_hours = 0
        if type_completed:
            durations = []
            for o in type_completed:
                if o.completion_time and o.created_at:
                    duration = (o.completion_time - o.created_at).total_seconds() / 3600
                    durations.append(duration)
            if durations:
                avg_hours = round(sum(durations) / len(durations), 2)

        service_type_sla_stats.append({
            "service_type": st.value,
            "total_orders": len(type_orders),
            "completed_orders": len(type_completed),
            "sla_achieved": type_sla_met,
            "sla_total": type_sla_total,
            "sla_achievement_rate": round(type_sla_met / type_sla_total * 100, 2) if type_sla_total > 0 else 0,
            "avg_completion_hours": avg_hours,
            "timeout_orders": len([o for o in type_orders if o.is_timeout == 1])
        })

    result = {
        "statistic_range": {
            "start_date": start_dt.strftime("%Y-%m-%d"),
            "end_date": (end_dt - timedelta(days=1)).strftime("%Y-%m-%d"),
            "filter_community": community,
            "filter_service_type": service_type,
            "filter_risk_level": risk_level
        },
        "total_orders": total_orders,
        "completed_orders": completed_count,
        "completion_rate": round(completed_count / total_orders * 100, 2) if total_orders > 0 else 0,
        "sla_achievement_rate": sla_achievement_rate,
        "sla_achieved_count": sla_achieved_count,
        "sla_eligible_count": sla_deadline_count,
        "duplicate_request_stats": {
            "total_suggestions": total_suggestions,
            "confirmed_suggestions": confirmed_suggestions,
            "rejected_suggestions": len([s for s in all_suggestions if s.status == MergeStatus.REJECTED]),
            "pending_suggestions": len([s for s in all_suggestions if s.status == MergeStatus.SUGGESTED]),
            "confirmation_rate": duplicate_confirmation_rate
        },
        "risk_escalation_distribution": risk_distribution,
        "supervision_stats": {
            "total_supervisions": supervision_total,
            "resolved_supervisions": supervision_resolved,
            "resolution_rate": round(supervision_resolved / supervision_total * 100, 2) if supervision_total > 0 else 0,
            "avg_processing_hours": avg_supervision_hours,
            "processing_count": len(supervision_durations)
        },
        "community_timeout_heatmap": community_timeout_heatmap,
        "high_risk_pending_orders": {
            "total": len(high_risk_pending),
            "items": high_risk_pending
        },
        "service_type_sla_stats": service_type_sla_stats
    }

    return success_response(data=result)


@router.get("/sla-dashboard", response_model=ApiResponse)
def get_sla_dashboard(
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    db: Session = Depends(get_db)
):
    start_date = datetime.now() - timedelta(days=days)
    all_orders = db.query(WorkOrder).filter(WorkOrder.created_at >= start_date).all()
    sla_configs = db.query(SLAConfig).filter(SLAConfig.is_active == True).all()

    completed_orders = [o for o in all_orders if o.status in [OrderStatus.COMPLETED, OrderStatus.CLOSED]]

    overall_sla_met = len([o for o in completed_orders if o.sla_achieved == True])
    overall_sla_total = len([o for o in completed_orders if o.sla_deadline])

    sla_by_service = []
    for config in sla_configs:
        type_orders = [o for o in all_orders if o.service_type == config.service_type]
        type_completed = [o for o in type_orders if o.status in [OrderStatus.COMPLETED, OrderStatus.CLOSED]]
        type_sla_met = len([o for o in type_completed if o.sla_achieved == True])
        type_sla_total = len([o for o in type_completed if o.sla_deadline])

        sla_by_service.append({
            "service_type": config.service_type.value,
            "response_hours": config.response_hours,
            "resolution_hours": config.resolution_hours,
            "first_response_hours": config.first_response_hours,
            "total_orders": len(type_orders),
            "completed_orders": len(type_completed),
            "sla_met": type_sla_met,
            "sla_total": type_sla_total,
            "achievement_rate": round(type_sla_met / type_sla_total * 100, 2) if type_sla_total > 0 else 0
        })

    sla_trend = []
    for i in range(min(days, 30)):
        day_start = datetime.now() - timedelta(days=days - i)
        day_end = day_start + timedelta(days=1)
        day_orders = [o for o in completed_orders if day_start <= o.created_at < day_end]
        day_sla_met = len([o for o in day_orders if o.sla_achieved == True])
        day_sla_total = len([o for o in day_orders if o.sla_deadline])
        sla_trend.append({
            "date": day_start.strftime("%Y-%m-%d"),
            "completed_orders": len(day_orders),
            "sla_met": day_sla_met,
            "achievement_rate": round(day_sla_met / day_sla_total * 100, 2) if day_sla_total > 0 else 0
        })

    return success_response(data={
        "statistic_days": days,
        "overall": {
            "total_orders": len(all_orders),
            "completed_orders": len(completed_orders),
            "sla_eligible": overall_sla_total,
            "sla_met": overall_sla_met,
            "achievement_rate": round(overall_sla_met / overall_sla_total * 100, 2) if overall_sla_total > 0 else 0
        },
        "by_service_type": sla_by_service,
        "daily_trend": sla_trend
    })
