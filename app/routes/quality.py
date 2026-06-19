from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timedelta
import uuid
from collections import defaultdict

from app.database import get_db
from app.models import (
    WorkOrder, ElderlyProfile, ProgressRecord, SupervisionRecord, VisitRecord,
    EvaluationTemplate, EvaluationIndicator, EvaluationTask, IndicatorScore,
    SatisfactionFeedback, StaffSelfEvaluation, StaffReview,
    LowScoreReason, AbnormalTag, AbnormalWarning, RectificationTask,
    ServiceType, RiskLevel, ProgressType, OrderStatus,
    EvaluationTaskStatus, EvaluationSource, FeedbackSubmitterType,
    AbnormalType, AbnormalStatus, RectificationStatus, ReviewResult
)
from app.schemas import (
    LowScoreReasonCreate, LowScoreReasonUpdate, LowScoreReasonResponse,
    AbnormalTagCreate, AbnormalTagUpdate, AbnormalTagResponse,
    EvaluationTemplateCreate, EvaluationTemplateUpdate, EvaluationTemplateResponse,
    EvaluationIndicatorCreate, EvaluationIndicatorUpdate, EvaluationIndicatorResponse,
    SatisfactionFeedbackSubmit, SatisfactionFeedbackResponse,
    StaffSelfEvaluationSubmit, StaffSelfEvaluationResponse,
    StaffReviewSubmit, StaffReviewResponse,
    EvaluationTaskCreate, EvaluationTaskGenerateRequest, EvaluationTaskUpdate,
    EvaluationTaskResponse, EvaluationTaskListResponse,
    AbnormalWarningResponse, AbnormalWarningHandleRequest,
    RectificationTaskCreate, RectificationTaskComplete, RectificationTaskReview,
    RectificationTaskResponse, RectificationTaskListResponse,
    QualityStatisticsResponse, AbnormalDetectionRequest,
    ServiceTypeSatisfactionItem, StaffQualityRankingItem, CommunityAbnormalItem,
    OverdueRectificationItem, RepeatComplaintElderlyItem, QualityTrendItem
)
from app.utils import success_response, error_response, ApiResponse, orm_to_dict

router = APIRouter(prefix="/quality", tags=["服务质量评价与异常预警"])


def generate_task_no(prefix: str = "ET") -> str:
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


def get_default_template(db: Session, service_type: ServiceType) -> EvaluationTemplate:
    template = db.query(EvaluationTemplate).filter(
        EvaluationTemplate.service_type == service_type,
        EvaluationTemplate.is_active == True,
        EvaluationTemplate.is_default == True
    ).first()
    if not template:
        template = db.query(EvaluationTemplate).filter(
            EvaluationTemplate.service_type == service_type,
            EvaluationTemplate.is_active == True
        ).order_by(EvaluationTemplate.id.desc()).first()
    if not template:
        template = db.query(EvaluationTemplate).filter(
            EvaluationTemplate.is_active == True
        ).order_by(EvaluationTemplate.id.desc()).first()
    return template


def calculate_overall_score(db: Session, evaluation_task: EvaluationTask) -> float:
    indicator_scores = db.query(IndicatorScore).filter(
        IndicatorScore.evaluation_task_id == evaluation_task.id
    ).all()
    if not indicator_scores:
        feedback = db.query(SatisfactionFeedback).filter(
            SatisfactionFeedback.evaluation_task_id == evaluation_task.id
        ).first()
        return feedback.overall_score if feedback else 0.0

    total_weight = sum(is_.weight for is_ in indicator_scores)
    if total_weight == 0:
        total_weight = 1.0
    weighted_sum = sum(is_.weighted_score for is_ in indicator_scores if is_.weighted_score is not None)
    return round(weighted_sum / total_weight, 2)


@router.post("/low-score-reasons", response_model=ApiResponse[LowScoreReasonResponse])
def create_low_score_reason(reason_data: LowScoreReasonCreate, db: Session = Depends(get_db)):
    existing = db.query(LowScoreReason).filter(LowScoreReason.code == reason_data.code).first()
    if existing:
        return error_response(code=400, message="原因编码已存在")
    reason = LowScoreReason(**reason_data.model_dump())
    db.add(reason)
    db.commit()
    db.refresh(reason)
    return success_response(data=reason, message="低分原因创建成功")


@router.get("/low-score-reasons", response_model=ApiResponse)
def list_low_score_reasons(
    category: Optional[str] = Query(None, description="分类筛选"),
    is_active: Optional[bool] = Query(None, description="是否启用"),
    db: Session = Depends(get_db)
):
    query = db.query(LowScoreReason)
    if category:
        query = query.filter(LowScoreReason.category == category)
    if is_active is not None:
        query = query.filter(LowScoreReason.is_active == is_active)
    reasons = query.order_by(LowScoreReason.id.asc()).all()
    return success_response(data={"total": len(reasons), "items": orm_to_dict(reasons)})


@router.put("/low-score-reasons/{reason_id}", response_model=ApiResponse[LowScoreReasonResponse])
def update_low_score_reason(reason_id: int, reason_update: LowScoreReasonUpdate, db: Session = Depends(get_db)):
    reason = db.query(LowScoreReason).filter(LowScoreReason.id == reason_id).first()
    if not reason:
        return error_response(code=404, message="低分原因不存在")
    update_data = reason_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(reason, key, value)
    db.commit()
    db.refresh(reason)
    return success_response(data=reason, message="低分原因更新成功")


@router.delete("/low-score-reasons/{reason_id}", response_model=ApiResponse)
def delete_low_score_reason(reason_id: int, db: Session = Depends(get_db)):
    reason = db.query(LowScoreReason).filter(LowScoreReason.id == reason_id).first()
    if not reason:
        return error_response(code=404, message="低分原因不存在")
    db.delete(reason)
    db.commit()
    return success_response(message="低分原因删除成功")


@router.post("/abnormal-tags", response_model=ApiResponse[AbnormalTagResponse])
def create_abnormal_tag(tag_data: AbnormalTagCreate, db: Session = Depends(get_db)):
    existing = db.query(AbnormalTag).filter(AbnormalTag.code == tag_data.code).first()
    if existing:
        return error_response(code=400, message="标签编码已存在")
    tag = AbnormalTag(**tag_data.model_dump())
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return success_response(data=tag, message="异常标签创建成功")


@router.get("/abnormal-tags", response_model=ApiResponse)
def list_abnormal_tags(
    abnormal_type: Optional[str] = Query(None, description="异常类型筛选"),
    risk_level: Optional[str] = Query(None, description="风险等级筛选"),
    is_active: Optional[bool] = Query(None, description="是否启用"),
    db: Session = Depends(get_db)
):
    query = db.query(AbnormalTag)
    if abnormal_type:
        query = query.filter(AbnormalTag.abnormal_type == abnormal_type)
    if risk_level:
        query = query.filter(AbnormalTag.risk_level == risk_level)
    if is_active is not None:
        query = query.filter(AbnormalTag.is_active == is_active)
    tags = query.order_by(AbnormalTag.id.asc()).all()
    return success_response(data={"total": len(tags), "items": orm_to_dict(tags)})


@router.put("/abnormal-tags/{tag_id}", response_model=ApiResponse[AbnormalTagResponse])
def update_abnormal_tag(tag_id: int, tag_update: AbnormalTagUpdate, db: Session = Depends(get_db)):
    tag = db.query(AbnormalTag).filter(AbnormalTag.id == tag_id).first()
    if not tag:
        return error_response(code=404, message="异常标签不存在")
    update_data = tag_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(tag, key, value)
    db.commit()
    db.refresh(tag)
    return success_response(data=tag, message="异常标签更新成功")


@router.delete("/abnormal-tags/{tag_id}", response_model=ApiResponse)
def delete_abnormal_tag(tag_id: int, db: Session = Depends(get_db)):
    tag = db.query(AbnormalTag).filter(AbnormalTag.id == tag_id).first()
    if not tag:
        return error_response(code=404, message="异常标签不存在")
    db.delete(tag)
    db.commit()
    return success_response(message="异常标签删除成功")


@router.post("/templates", response_model=ApiResponse[EvaluationTemplateResponse])
def create_template(template_data: EvaluationTemplateCreate, db: Session = Depends(get_db)):
    indicators_data = template_data.indicators
    template_dict = template_data.model_dump(exclude={"indicators"})
    template = EvaluationTemplate(**template_dict)
    db.add(template)
    db.flush()

    for indicator_data in indicators_data:
        indicator = EvaluationIndicator(
            template_id=template.id,
            **indicator_data.model_dump()
        )
        db.add(indicator)

    if template.is_default:
        db.query(EvaluationTemplate).filter(
            EvaluationTemplate.service_type == template.service_type,
            EvaluationTemplate.id != template.id
        ).update({"is_default": False})

    db.commit()
    db.refresh(template)
    return success_response(data=template, message="评价模板创建成功")


@router.get("/templates", response_model=ApiResponse)
def list_templates(
    service_type: Optional[str] = Query(None, description="服务类型筛选"),
    is_active: Optional[bool] = Query(None, description="是否启用"),
    db: Session = Depends(get_db)
):
    query = db.query(EvaluationTemplate)
    if service_type:
        query = query.filter(EvaluationTemplate.service_type == service_type)
    if is_active is not None:
        query = query.filter(EvaluationTemplate.is_active == is_active)
    templates = query.order_by(EvaluationTemplate.id.desc()).all()
    items = []
    for t in templates:
        t_dict = orm_to_dict(t)
        t_dict["indicators"] = orm_to_dict(t.indicators)
        items.append(t_dict)
    return success_response(data={"total": len(items), "items": items})


@router.get("/templates/{template_id}", response_model=ApiResponse[EvaluationTemplateResponse])
def get_template(template_id: int, db: Session = Depends(get_db)):
    template = db.query(EvaluationTemplate).filter(EvaluationTemplate.id == template_id).first()
    if not template:
        return error_response(code=404, message="评价模板不存在")
    result = orm_to_dict(template)
    result["indicators"] = orm_to_dict(template.indicators)
    return success_response(data=result)


@router.put("/templates/{template_id}", response_model=ApiResponse[EvaluationTemplateResponse])
def update_template(template_id: int, template_update: EvaluationTemplateUpdate, db: Session = Depends(get_db)):
    template = db.query(EvaluationTemplate).filter(EvaluationTemplate.id == template_id).first()
    if not template:
        return error_response(code=404, message="评价模板不存在")
    update_data = template_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(template, key, value)

    if template.is_default:
        db.query(EvaluationTemplate).filter(
            EvaluationTemplate.service_type == template.service_type,
            EvaluationTemplate.id != template.id
        ).update({"is_default": False})

    db.commit()
    db.refresh(template)
    return success_response(data=template, message="评价模板更新成功")


@router.post("/templates/{template_id}/indicators", response_model=ApiResponse[EvaluationIndicatorResponse])
def add_indicator(template_id: int, indicator_data: EvaluationIndicatorCreate, db: Session = Depends(get_db)):
    template = db.query(EvaluationTemplate).filter(EvaluationTemplate.id == template_id).first()
    if not template:
        return error_response(code=404, message="评价模板不存在")
    indicator = EvaluationIndicator(template_id=template_id, **indicator_data.model_dump())
    db.add(indicator)
    db.commit()
    db.refresh(indicator)
    return success_response(data=indicator, message="评价指标添加成功")


@router.put("/indicators/{indicator_id}", response_model=ApiResponse[EvaluationIndicatorResponse])
def update_indicator(indicator_id: int, indicator_update: EvaluationIndicatorUpdate, db: Session = Depends(get_db)):
    indicator = db.query(EvaluationIndicator).filter(EvaluationIndicator.id == indicator_id).first()
    if not indicator:
        return error_response(code=404, message="评价指标不存在")
    update_data = indicator_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(indicator, key, value)
    db.commit()
    db.refresh(indicator)
    return success_response(data=indicator, message="评价指标更新成功")


@router.delete("/indicators/{indicator_id}", response_model=ApiResponse)
def delete_indicator(indicator_id: int, db: Session = Depends(get_db)):
    indicator = db.query(EvaluationIndicator).filter(EvaluationIndicator.id == indicator_id).first()
    if not indicator:
        return error_response(code=404, message="评价指标不存在")
    db.delete(indicator)
    db.commit()
    return success_response(message="评价指标删除成功")


@router.post("/evaluation-tasks/generate", response_model=ApiResponse[EvaluationTaskResponse])
def generate_evaluation_task(request: EvaluationTaskGenerateRequest, db: Session = Depends(get_db)):
    order = db.query(WorkOrder).filter(WorkOrder.id == request.work_order_id).first()
    if not order:
        return error_response(code=404, message="工单不存在")

    if order.status not in [OrderStatus.COMPLETED, OrderStatus.INCOMPLETE, OrderStatus.CLOSED]:
        return error_response(code=400, message=f"当前工单状态为{order.status.value}，仅已完成、未完成或已关闭的工单可生成评价任务")

    existing = db.query(EvaluationTask).filter(
        EvaluationTask.work_order_id == request.work_order_id,
        EvaluationTask.source == request.source
    ).first()
    if existing:
        return error_response(code=400, message="该工单已生成评价任务")

    template = get_default_template(db, order.service_type)
    if not template:
        return error_response(code=400, message="未找到可用的评价模板，请先配置")

    task_no = generate_task_no("ET")
    expire_time = datetime.now() + timedelta(days=7)

    task = EvaluationTask(
        task_no=task_no,
        work_order_id=order.id,
        elderly_id=order.elderly_id,
        template_id=template.id,
        supervision_record_id=request.supervision_record_id,
        source=request.source,
        status=EvaluationTaskStatus.PENDING,
        assignee_name=order.assignee_name,
        assignee_phone=order.assignee_phone,
        expire_time=expire_time
    )
    db.add(task)
    db.flush()

    add_progress_record(
        db, order.id, ProgressType.CREATED,
        operator_name="系统", operator_role="system",
        remark=f"已生成评价任务，任务编号：{task_no}，评价模板：{template.name}"
    )

    db.commit()
    db.refresh(task)

    result = orm_to_dict(task)
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == task.elderly_id).first()
    result["elderly_name"] = elderly.name if elderly else ""
    result["work_order_no"] = order.order_no
    result["template_name"] = template.name
    result["feedbacks"] = []
    result["self_evaluation"] = None
    result["reviews"] = []

    return success_response(data=result, message="评价任务生成成功")


@router.post("/evaluation-tasks", response_model=ApiResponse[EvaluationTaskResponse])
def create_evaluation_task(task_data: EvaluationTaskCreate, db: Session = Depends(get_db)):
    order = db.query(WorkOrder).filter(WorkOrder.id == task_data.work_order_id).first()
    if not order:
        return error_response(code=404, message="工单不存在")

    if order.status not in [OrderStatus.COMPLETED, OrderStatus.INCOMPLETE, OrderStatus.CLOSED]:
        return error_response(code=400, message=f"当前工单状态为{order.status.value}，仅已完成、未完成或已关闭的工单可生成评价任务")

    existing = db.query(EvaluationTask).filter(
        EvaluationTask.work_order_id == task_data.work_order_id,
        EvaluationTask.source == task_data.source
    ).first()
    if existing:
        return error_response(code=400, message="该工单已生成同来源评价任务")

    if task_data.template_id:
        template = db.query(EvaluationTemplate).filter(EvaluationTemplate.id == task_data.template_id).first()
        if not template:
            return error_response(code=404, message="评价模板不存在")
    else:
        template = get_default_template(db, order.service_type)
        if not template:
            return error_response(code=400, message="未找到可用的评价模板，请先配置")

    task_no = generate_task_no("ET")
    expire_days = task_data.expire_days or 7
    expire_time = datetime.now() + timedelta(days=expire_days)

    task = EvaluationTask(
        task_no=task_no,
        work_order_id=order.id,
        elderly_id=order.elderly_id,
        template_id=template.id,
        supervision_record_id=task_data.supervision_record_id,
        source=task_data.source,
        status=EvaluationTaskStatus.PENDING,
        assignee_name=order.assignee_name,
        assignee_phone=order.assignee_phone,
        expire_time=expire_time
    )
    db.add(task)
    db.flush()

    add_progress_record(
        db, order.id, ProgressType.CREATED,
        operator_name="系统", operator_role="system",
        remark=f"已生成评价任务，任务编号：{task_no}，评价模板：{template.name}"
    )

    db.commit()
    db.refresh(task)

    result = orm_to_dict(task)
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == task.elderly_id).first()
    result["elderly_name"] = elderly.name if elderly else ""
    result["work_order_no"] = order.order_no
    result["template_name"] = template.name
    result["feedbacks"] = []
    result["self_evaluation"] = None
    result["reviews"] = []

    return success_response(data=result, message="评价任务创建成功")


@router.get("/evaluation-tasks", response_model=ApiResponse[EvaluationTaskListResponse])
def list_evaluation_tasks(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    work_order_id: Optional[int] = Query(None, description="工单ID"),
    elderly_id: Optional[int] = Query(None, description="老人ID"),
    service_type: Optional[str] = Query(None, description="服务类型"),
    status: Optional[str] = Query(None, description="任务状态"),
    source: Optional[str] = Query(None, description="来源"),
    assignee_name: Optional[str] = Query(None, description="接单人员"),
    is_abnormal: Optional[bool] = Query(None, description="是否异常"),
    start_date: Optional[str] = Query(None, description="开始日期"),
    end_date: Optional[str] = Query(None, description="结束日期"),
    db: Session = Depends(get_db)
):
    query = db.query(EvaluationTask)

    if work_order_id:
        query = query.filter(EvaluationTask.work_order_id == work_order_id)
    if elderly_id:
        query = query.filter(EvaluationTask.elderly_id == elderly_id)
    if service_type:
        query = query.join(EvaluationTemplate).filter(EvaluationTemplate.service_type == service_type)
    if status:
        query = query.filter(EvaluationTask.status == status)
    if source:
        query = query.filter(EvaluationTask.source == source)
    if assignee_name:
        query = query.filter(EvaluationTask.assignee_name.like(f"%{assignee_name}%"))
    if is_abnormal is not None:
        query = query.filter(EvaluationTask.is_abnormal == is_abnormal)
    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        query = query.filter(EvaluationTask.created_at >= start_dt)
    if end_date:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        query = query.filter(EvaluationTask.created_at < end_dt)

    total = query.count()
    tasks = query.order_by(EvaluationTask.id.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for task in tasks:
        task_dict = orm_to_dict(task)
        order = db.query(WorkOrder).filter(WorkOrder.id == task.work_order_id).first()
        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == task.elderly_id).first()
        template = db.query(EvaluationTemplate).filter(EvaluationTemplate.id == task.template_id).first()

        task_dict["work_order_no"] = order.order_no if order else ""
        task_dict["elderly_name"] = elderly.name if elderly else ""
        task_dict["template_name"] = template.name if template else ""
        task_dict["feedbacks"] = orm_to_dict(task.feedbacks)
        for fb in task_dict["feedbacks"]:
            if fb.get("low_score_reason_id"):
                reason = db.query(LowScoreReason).filter(LowScoreReason.id == fb["low_score_reason_id"]).first()
                fb["low_score_reason_name"] = reason.name if reason else ""

        task_dict["self_evaluation"] = orm_to_dict(task.self_evaluation) if task.self_evaluation else None
        task_dict["reviews"] = orm_to_dict(task.reviews)

        items.append(task_dict)

    return success_response(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    })


@router.get("/evaluation-tasks/{task_id}", response_model=ApiResponse[EvaluationTaskResponse])
def get_evaluation_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(EvaluationTask).filter(EvaluationTask.id == task_id).first()
    if not task:
        return error_response(code=404, message="评价任务不存在")

    result = orm_to_dict(task)
    order = db.query(WorkOrder).filter(WorkOrder.id == task.work_order_id).first()
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == task.elderly_id).first()
    template = db.query(EvaluationTemplate).filter(EvaluationTemplate.id == task.template_id).first()

    result["work_order_no"] = order.order_no if order else ""
    result["elderly_name"] = elderly.name if elderly else ""
    result["template_name"] = template.name if template else ""

    result["feedbacks"] = orm_to_dict(task.feedbacks)
    for fb in result["feedbacks"]:
        if fb.get("low_score_reason_id"):
            reason = db.query(LowScoreReason).filter(LowScoreReason.id == fb["low_score_reason_id"]).first()
            fb["low_score_reason_name"] = reason.name if reason else ""

    result["self_evaluation"] = orm_to_dict(task.self_evaluation) if task.self_evaluation else None
    result["reviews"] = orm_to_dict(task.reviews)

    return success_response(data=result)


@router.post("/feedback/submit", response_model=ApiResponse[SatisfactionFeedbackResponse])
def submit_feedback(feedback_data: SatisfactionFeedbackSubmit, db: Session = Depends(get_db)):
    task = db.query(EvaluationTask).filter(EvaluationTask.id == feedback_data.evaluation_task_id).first()
    if not task:
        return error_response(code=404, message="评价任务不存在")
    if task.status not in [EvaluationTaskStatus.PENDING, EvaluationTaskStatus.STAFF_SUBMITTED]:
        return error_response(code=400, message="当前任务状态不可提交满意度反馈")

    feedback = SatisfactionFeedback(**feedback_data.model_dump(exclude={"indicator_scores"}))
    db.add(feedback)
    db.flush()

    template = db.query(EvaluationTemplate).filter(EvaluationTemplate.id == task.template_id).first()
    indicators = {ind.id: ind for ind in template.indicators} if template else {}

    for item in feedback_data.indicator_scores:
        indicator = indicators.get(item.indicator_id)
        if not indicator:
            continue
        max_score = indicator.max_score or 5.0
        if item.score < 0 or item.score > max_score:
            db.rollback()
            return error_response(code=400, message=f"指标「{indicator.name}」得分必须在 0 到 {max_score} 之间，当前得分为 {item.score}")
        weight = indicator.weight or 1.0
        weighted_score = (item.score / max_score) * weight * 5.0
        indicator_score = IndicatorScore(
            evaluation_task_id=task.id,
            indicator_id=item.indicator_id,
            indicator_name=indicator.name,
            score=item.score,
            max_score=max_score,
            weight=weight,
            weighted_score=weighted_score
        )
        db.add(indicator_score)

    db.flush()
    overall_score = calculate_overall_score(db, task)
    task.overall_score = overall_score
    task.status = EvaluationTaskStatus.ELDERLY_SUBMITTED

    order = db.query(WorkOrder).filter(WorkOrder.id == task.work_order_id).first()
    if order:
        add_progress_record(
            db, order.id, ProgressType.COMPLETED,
            operator_name=feedback_data.submitter_name or "老人/联系人",
            operator_role=feedback_data.submitter_type.value,
            remark=f"满意度反馈已提交，评分：{overall_score}分"
        )

    if overall_score < 3.0:
        task.is_abnormal = True
        task.abnormal_reason = f"满意度评分低于3分，实际得分：{overall_score}"

    db.commit()
    db.refresh(feedback)

    result = orm_to_dict(feedback)
    if feedback.low_score_reason_id:
        reason = db.query(LowScoreReason).filter(LowScoreReason.id == feedback.low_score_reason_id).first()
        result["low_score_reason_name"] = reason.name if reason else ""

    return success_response(data=result, message="满意度反馈提交成功")


@router.post("/self-evaluation/submit", response_model=ApiResponse[StaffSelfEvaluationResponse])
def submit_self_evaluation(eval_data: StaffSelfEvaluationSubmit, db: Session = Depends(get_db)):
    task = db.query(EvaluationTask).filter(EvaluationTask.id == eval_data.evaluation_task_id).first()
    if not task:
        return error_response(code=404, message="评价任务不存在")
    if task.status not in [EvaluationTaskStatus.PENDING, EvaluationTaskStatus.ELDERLY_SUBMITTED]:
        return error_response(code=400, message="当前任务状态不可提交自评")

    existing = db.query(StaffSelfEvaluation).filter(
        StaffSelfEvaluation.evaluation_task_id == eval_data.evaluation_task_id
    ).first()
    if existing:
        return error_response(code=400, message="该任务已提交自评")

    self_eval = StaffSelfEvaluation(**eval_data.model_dump())
    db.add(self_eval)
    db.flush()

    task.staff_self_score = eval_data.self_score
    if task.status == EvaluationTaskStatus.PENDING:
        task.status = EvaluationTaskStatus.STAFF_SUBMITTED
    elif task.status == EvaluationTaskStatus.ELDERLY_SUBMITTED:
        task.status = EvaluationTaskStatus.REVIEWED

    order = db.query(WorkOrder).filter(WorkOrder.id == task.work_order_id).first()
    if order:
        add_progress_record(
            db, order.id, ProgressType.COMPLETED,
            operator_name=eval_data.staff_name,
            operator_role="staff",
            remark=f"服务人员自评已提交，自评分：{eval_data.self_score}分"
        )

    db.commit()
    db.refresh(self_eval)
    return success_response(data=self_eval, message="自评提交成功")


@router.post("/review/submit", response_model=ApiResponse[StaffReviewResponse])
def submit_review(review_data: StaffReviewSubmit, db: Session = Depends(get_db)):
    task = db.query(EvaluationTask).filter(EvaluationTask.id == review_data.evaluation_task_id).first()
    if not task:
        return error_response(code=404, message="评价任务不存在")
    if task.status not in [EvaluationTaskStatus.ELDERLY_SUBMITTED, EvaluationTaskStatus.STAFF_SUBMITTED, EvaluationTaskStatus.REVIEWED]:
        return error_response(code=400, message="当前任务状态不可复核")

    review = StaffReview(**review_data.model_dump())
    db.add(review)
    db.flush()

    task.reviewer_name = review_data.reviewer_name
    task.review_time = datetime.now()
    task.review_remark = review_data.review_remark
    task.status = EvaluationTaskStatus.REVIEWED

    order = db.query(WorkOrder).filter(WorkOrder.id == task.work_order_id).first()
    if order:
        add_progress_record(
            db, order.id, ProgressType.SUPERVISION,
            operator_name=review_data.reviewer_name,
            operator_role=review_data.reviewer_role or "reviewer",
            remark=f"复核完成，结果：{review_data.review_result.value}；{'需要整改' if review_data.need_rectification else '无需整改'}"
        )

    if review_data.need_rectification:
        task.is_abnormal = True
        if task.abnormal_reason:
            task.abnormal_reason += f"；复核要求整改：{review_data.rectification_requirement}"
        else:
            task.abnormal_reason = f"复核要求整改：{review_data.rectification_requirement}"

    db.commit()
    db.refresh(review)
    return success_response(data=review, message="复核提交成功")


def create_abnormal_warning(db: Session, abnormal_type: AbnormalType, elderly_id: int,
                            work_order_id: int = None, evaluation_task_id: int = None,
                            staff_name: str = None, tag: AbnormalTag = None,
                            title: str = None, description: str = None,
                            risk_level: RiskLevel = RiskLevel.MEDIUM) -> AbnormalWarning:
    warning_no = generate_task_no("AW")

    if not title:
        title_map = {
            AbnormalType.LOW_SATISFACTION: "低满意度预警",
            AbnormalType.NO_VISIT: "未回访预警",
            AbnormalType.REPEAT_LOW_SCORE: "重复低分预警",
            AbnormalType.STAFF_CONTINUOUS_ABNORMAL: "服务人员连续异常预警",
            AbnormalType.MULTIPLE_COMPLAINTS: "老人多次投诉预警"
        }
        title = title_map.get(abnormal_type, "服务质量异常预警")

    warning = AbnormalWarning(
        warning_no=warning_no,
        abnormal_type=abnormal_type,
        work_order_id=work_order_id,
        elderly_id=elderly_id,
        evaluation_task_id=evaluation_task_id,
        staff_name=staff_name,
        tag_id=tag.id if tag else None,
        tag_name=tag.name if tag else None,
        risk_level=risk_level,
        title=title,
        description=description,
        status=AbnormalStatus.PENDING,
        triggered_by="system",
        trigger_time=datetime.now()
    )
    db.add(warning)
    db.flush()

    if work_order_id:
        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == elderly_id).first()
        add_progress_record(
            db, work_order_id, ProgressType.ESCALATION,
            operator_name="系统", operator_role="system",
            remark=f"自动生成异常预警：{title}，预警编号：{warning_no}，风险等级：{risk_level.value}"
        )

    return warning


def detect_low_satisfaction(db: Session, days: int = 30, community: str = None,
                            service_type: ServiceType = None) -> list:
    start_time = datetime.now() - timedelta(days=days)
    warnings = []

    query = db.query(EvaluationTask).filter(
        EvaluationTask.created_at >= start_time,
        EvaluationTask.is_abnormal == False,
        EvaluationTask.overall_score < 3.0
    )
    if service_type:
        query = query.join(EvaluationTemplate).filter(EvaluationTemplate.service_type == service_type)
    if community:
        query = query.join(ElderlyProfile).filter(ElderlyProfile.community == community)

    tasks = query.all()
    for task in tasks:
        existing = db.query(AbnormalWarning).filter(
            AbnormalWarning.evaluation_task_id == task.id,
            AbnormalWarning.abnormal_type == AbnormalType.LOW_SATISFACTION
        ).first()
        if existing:
            continue

        tag = db.query(AbnormalTag).filter(
            AbnormalTag.abnormal_type == AbnormalType.LOW_SATISFACTION,
            AbnormalTag.is_active == True
        ).first()

        order = db.query(WorkOrder).filter(WorkOrder.id == task.work_order_id).first()
        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == task.elderly_id).first()

        warning = create_abnormal_warning(
            db=db,
            abnormal_type=AbnormalType.LOW_SATISFACTION,
            elderly_id=task.elderly_id,
            work_order_id=task.work_order_id,
            evaluation_task_id=task.id,
            staff_name=task.assignee_name,
            tag=tag,
            title=f"低满意度预警：{elderly.name if elderly else ''} 评分{task.overall_score}分",
            description=f"服务满意度评分低于3分，实际得分：{task.overall_score}分，工单编号：{order.order_no if order else ''}",
            risk_level=RiskLevel.HIGH if task.overall_score < 2.0 else RiskLevel.MEDIUM
        )
        warnings.append(warning)
        task.is_abnormal = True
        task.abnormal_reason = f"低满意度预警：评分{task.overall_score}分"

    db.commit()
    return warnings


def detect_no_visit(db: Session, days: int = 30, community: str = None,
                    service_type: ServiceType = None) -> list:
    start_time = datetime.now() - timedelta(days=days)
    warnings = []

    query = db.query(WorkOrder).filter(
        WorkOrder.created_at >= start_time,
        WorkOrder.status.in_([OrderStatus.COMPLETED, OrderStatus.CLOSED])
    )
    if service_type:
        query = query.filter(WorkOrder.service_type == service_type)
    if community:
        query = query.join(ElderlyProfile).filter(ElderlyProfile.community == community)

    orders = query.all()
    for order in orders:
        visit_count = db.query(VisitRecord).filter(
            VisitRecord.work_order_id == order.id,
            VisitRecord.archived == True
        ).count()
        if visit_count > 0:
            continue

        existing = db.query(AbnormalWarning).filter(
            AbnormalWarning.work_order_id == order.id,
            AbnormalWarning.abnormal_type == AbnormalType.NO_VISIT
        ).first()
        if existing:
            continue

        tag = db.query(AbnormalTag).filter(
            AbnormalTag.abnormal_type == AbnormalType.NO_VISIT,
            AbnormalTag.is_active == True
        ).first()

        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == order.elderly_id).first()

        warning = create_abnormal_warning(
            db=db,
            abnormal_type=AbnormalType.NO_VISIT,
            elderly_id=order.elderly_id,
            work_order_id=order.id,
            staff_name=order.assignee_name,
            tag=tag,
            title=f"未回访预警：{elderly.name if elderly else ''} 的工单未完成回访归档",
            description=f"工单已完成但未进行回访归档，工单编号：{order.order_no}",
            risk_level=RiskLevel.MEDIUM
        )
        warnings.append(warning)

    db.commit()
    return warnings


def detect_repeat_low_score(db: Session, days: int = 30, community: str = None,
                            service_type: ServiceType = None) -> list:
    start_time = datetime.now() - timedelta(days=days)
    warnings = []

    query = db.query(EvaluationTask).filter(
        EvaluationTask.created_at >= start_time,
        EvaluationTask.overall_score < 3.0
    )
    if service_type:
        query = query.join(EvaluationTemplate).filter(EvaluationTemplate.service_type == service_type)
    if community:
        query = query.join(ElderlyProfile).filter(ElderlyProfile.community == community)

    task_list = query.all()
    elderly_low_scores = defaultdict(list)
    for task in task_list:
        elderly_low_scores[task.elderly_id].append(task)

    for elderly_id, tasks in elderly_low_scores.items():
        if len(tasks) < 2:
            continue

        existing = db.query(AbnormalWarning).filter(
            AbnormalWarning.elderly_id == elderly_id,
            AbnormalWarning.abnormal_type == AbnormalType.REPEAT_LOW_SCORE,
            AbnormalWarning.trigger_time >= start_time
        ).first()
        if existing:
            continue

        tag = db.query(AbnormalTag).filter(
            AbnormalTag.abnormal_type == AbnormalType.REPEAT_LOW_SCORE,
            AbnormalTag.is_active == True
        ).first()

        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == elderly_id).first()
        scores = [t.overall_score for t in tasks]
        avg_score = round(sum(scores) / len(scores), 2)

        warning = create_abnormal_warning(
            db=db,
            abnormal_type=AbnormalType.REPEAT_LOW_SCORE,
            elderly_id=elderly_id,
            evaluation_task_id=tasks[0].id,
            work_order_id=tasks[0].work_order_id,
            tag=tag,
            title=f"重复低分预警：{elderly.name if elderly else ''} {len(tasks)}次低分",
            description=f"该老人在{days}天内{len(tasks)}次服务评分低于3分，平均分：{avg_score}分",
            risk_level=RiskLevel.HIGH
        )
        warnings.append(warning)

    db.commit()
    return warnings


def detect_staff_continuous_abnormal(db: Session, days: int = 30, community: str = None,
                                     service_type: ServiceType = None) -> list:
    start_time = datetime.now() - timedelta(days=days)
    warnings = []

    query = db.query(EvaluationTask).filter(
        EvaluationTask.created_at >= start_time,
        EvaluationTask.assignee_name.isnot(None),
        EvaluationTask.overall_score < 3.0
    )
    if service_type:
        query = query.join(EvaluationTemplate).filter(EvaluationTemplate.service_type == service_type)
    if community:
        query = query.join(ElderlyProfile).filter(ElderlyProfile.community == community)

    task_list = query.all()
    staff_low_scores = defaultdict(list)
    for task in task_list:
        if task.assignee_name:
            staff_low_scores[task.assignee_name].append(task)

    for staff_name, tasks in staff_low_scores.items():
        if len(tasks) < 3:
            continue

        existing = db.query(AbnormalWarning).filter(
            AbnormalWarning.staff_name == staff_name,
            AbnormalWarning.abnormal_type == AbnormalType.STAFF_CONTINUOUS_ABNORMAL,
            AbnormalWarning.trigger_time >= start_time
        ).first()
        if existing:
            continue

        tag = db.query(AbnormalTag).filter(
            AbnormalTag.abnormal_type == AbnormalType.STAFF_CONTINUOUS_ABNORMAL,
            AbnormalTag.is_active == True
        ).first()

        scores = [t.overall_score for t in tasks]
        avg_score = round(sum(scores) / len(scores), 2)
        elderly_ids = list(set(t.elderly_id for t in tasks))

        warning = create_abnormal_warning(
            db=db,
            abnormal_type=AbnormalType.STAFF_CONTINUOUS_ABNORMAL,
            elderly_id=tasks[0].elderly_id,
            evaluation_task_id=tasks[0].id,
            work_order_id=tasks[0].work_order_id,
            staff_name=staff_name,
            tag=tag,
            title=f"服务人员连续异常预警：{staff_name} {len(tasks)}次低分",
            description=f"服务人员 {staff_name} 在{days}天内{len(tasks)}次服务评分低于3分，涉及{len(elderly_ids)}位老人，平均分：{avg_score}分",
            risk_level=RiskLevel.HIGH
        )
        warnings.append(warning)

    db.commit()
    return warnings


def detect_multiple_complaints(db: Session, days: int = 30, community: str = None,
                               service_type: ServiceType = None) -> list:
    start_time = datetime.now() - timedelta(days=days)
    warnings = []

    query = db.query(SatisfactionFeedback).filter(
        SatisfactionFeedback.submit_time >= start_time,
        SatisfactionFeedback.is_complaint == True
    )
    if service_type:
        query = query.join(EvaluationTask).join(EvaluationTemplate).filter(
            EvaluationTemplate.service_type == service_type
        )
    if community:
        query = query.join(EvaluationTask).join(ElderlyProfile).filter(
            ElderlyProfile.community == community
        )

    feedbacks = query.all()
    elderly_complaints = defaultdict(list)
    for fb in feedbacks:
        elderly_complaints[fb.evaluation_task.elderly_id].append(fb)

    for elderly_id, complaints in elderly_complaints.items():
        if len(complaints) < 2:
            continue

        existing = db.query(AbnormalWarning).filter(
            AbnormalWarning.elderly_id == elderly_id,
            AbnormalWarning.abnormal_type == AbnormalType.MULTIPLE_COMPLAINTS,
            AbnormalWarning.trigger_time >= start_time
        ).first()
        if existing:
            continue

        tag = db.query(AbnormalTag).filter(
            AbnormalTag.abnormal_type == AbnormalType.MULTIPLE_COMPLAINTS,
            AbnormalTag.is_active == True
        ).first()

        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == elderly_id).first()
        task_ids = [c.evaluation_task_id for c in complaints]
        tasks = db.query(EvaluationTask).filter(EvaluationTask.id.in_(task_ids)).all()
        work_order_ids = [t.work_order_id for t in tasks]

        warning = create_abnormal_warning(
            db=db,
            abnormal_type=AbnormalType.MULTIPLE_COMPLAINTS,
            elderly_id=elderly_id,
            evaluation_task_id=task_ids[0],
            work_order_id=work_order_ids[0] if work_order_ids else None,
            tag=tag,
            title=f"多次投诉预警：{elderly.name if elderly else ''} {len(complaints)}次投诉",
            description=f"该老人在{days}天内投诉{len(complaints)}次，请重点关注",
            risk_level=RiskLevel.CRITICAL
        )
        warnings.append(warning)

    db.commit()
    return warnings


@router.post("/detect-abnormal", response_model=ApiResponse)
def detect_abnormal(request: AbnormalDetectionRequest, db: Session = Depends(get_db)):
    days = request.days or 30

    low_sat = detect_low_satisfaction(db, days, request.community, request.service_type)
    no_visit = detect_no_visit(db, days, request.community, request.service_type)
    repeat_low = detect_repeat_low_score(db, days, request.community, request.service_type)
    staff_abnormal = detect_staff_continuous_abnormal(db, days, request.community, request.service_type)
    complaints = detect_multiple_complaints(db, days, request.community, request.service_type)

    total = len(low_sat) + len(no_visit) + len(repeat_low) + len(staff_abnormal) + len(complaints)

    return success_response(data={
        "total_new_warnings": total,
        "low_satisfaction_count": len(low_sat),
        "no_visit_count": len(no_visit),
        "repeat_low_score_count": len(repeat_low),
        "staff_continuous_abnormal_count": len(staff_abnormal),
        "multiple_complaints_count": len(complaints),
        "message": f"完成异常检测，共生成{total}条异常预警"
    })


@router.get("/abnormal-warnings", response_model=ApiResponse)
def list_abnormal_warnings(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    abnormal_type: Optional[str] = Query(None, description="异常类型"),
    status: Optional[str] = Query(None, description="状态"),
    risk_level: Optional[str] = Query(None, description="风险等级"),
    elderly_id: Optional[int] = Query(None, description="老人ID"),
    work_order_id: Optional[int] = Query(None, description="工单ID"),
    staff_name: Optional[str] = Query(None, description="服务人员"),
    tag_id: Optional[int] = Query(None, description="异常标签ID"),
    start_date: Optional[str] = Query(None, description="开始日期"),
    end_date: Optional[str] = Query(None, description="结束日期"),
    db: Session = Depends(get_db)
):
    query = db.query(AbnormalWarning)

    if abnormal_type:
        query = query.filter(AbnormalWarning.abnormal_type == abnormal_type)
    if status:
        query = query.filter(AbnormalWarning.status == status)
    if risk_level:
        query = query.filter(AbnormalWarning.risk_level == risk_level)
    if elderly_id:
        query = query.filter(AbnormalWarning.elderly_id == elderly_id)
    if work_order_id:
        query = query.filter(AbnormalWarning.work_order_id == work_order_id)
    if staff_name:
        query = query.filter(AbnormalWarning.staff_name.like(f"%{staff_name}%"))
    if tag_id:
        query = query.filter(AbnormalWarning.tag_id == tag_id)
    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        query = query.filter(AbnormalWarning.trigger_time >= start_dt)
    if end_date:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        query = query.filter(AbnormalWarning.trigger_time < end_dt)

    total = query.count()
    warnings = query.order_by(AbnormalWarning.trigger_time.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    items = []
    for w in warnings:
        w_dict = orm_to_dict(w)
        order = db.query(WorkOrder).filter(WorkOrder.id == w.work_order_id).first()
        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == w.elderly_id).first()
        w_dict["work_order_no"] = order.order_no if order else ""
        w_dict["elderly_name"] = elderly.name if elderly else ""
        items.append(w_dict)

    return success_response(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    })


@router.post("/abnormal-warnings/{warning_id}/handle", response_model=ApiResponse[AbnormalWarningResponse])
def handle_abnormal_warning(warning_id: int, handle_data: AbnormalWarningHandleRequest, db: Session = Depends(get_db)):
    warning = db.query(AbnormalWarning).filter(AbnormalWarning.id == warning_id).first()
    if not warning:
        return error_response(code=404, message="异常预警不存在")

    warning.handler_name = handle_data.handler_name
    warning.handle_remark = handle_data.handle_remark
    warning.handle_time = datetime.now()
    warning.status = handle_data.status or AbnormalStatus.PROCESSING

    if warning.work_order_id:
        add_progress_record(
            db, warning.work_order_id, ProgressType.SUPERVISION,
            operator_name=handle_data.handler_name, operator_role="handler",
            remark=f"异常预警处理：{handle_data.handle_remark}"
        )

    db.commit()
    db.refresh(warning)

    result = orm_to_dict(warning)
    order = db.query(WorkOrder).filter(WorkOrder.id == warning.work_order_id).first()
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == warning.elderly_id).first()
    result["work_order_no"] = order.order_no if order else ""
    result["elderly_name"] = elderly.name if elderly else ""

    return success_response(data=result, message="异常预警已处理")


@router.post("/rectification-tasks", response_model=ApiResponse[RectificationTaskResponse])
def create_rectification_task(task_data: RectificationTaskCreate, db: Session = Depends(get_db)):
    task_no = generate_task_no("RT")

    work_order_id = None
    elderly_id = None
    if task_data.abnormal_warning_id:
        warning = db.query(AbnormalWarning).filter(AbnormalWarning.id == task_data.abnormal_warning_id).first()
        if not warning:
            return error_response(code=404, message="异常预警不存在")
        work_order_id = warning.work_order_id
        elderly_id = warning.elderly_id
    elif task_data.evaluation_task_id:
        eval_task = db.query(EvaluationTask).filter(EvaluationTask.id == task_data.evaluation_task_id).first()
        if not eval_task:
            return error_response(code=404, message="评价任务不存在")
        work_order_id = eval_task.work_order_id
        elderly_id = eval_task.elderly_id

    task = RectificationTask(
        task_no=task_no,
        abnormal_warning_id=task_data.abnormal_warning_id,
        evaluation_task_id=task_data.evaluation_task_id,
        work_order_id=work_order_id,
        elderly_id=elderly_id,
        title=task_data.title,
        description=task_data.description,
        responsible_person=task_data.responsible_person,
        responsible_phone=task_data.responsible_phone,
        deadline=task_data.deadline,
        status=RectificationStatus.PENDING,
        created_by=task_data.created_by
    )
    db.add(task)
    db.flush()

    if work_order_id:
        add_progress_record(
            db, work_order_id, ProgressType.SUPERVISION,
            operator_name=task_data.created_by or "系统", operator_role="supervisor",
            remark=f"已生成整改任务，任务编号：{task_no}，责任人：{task_data.responsible_person}，截止时间：{task_data.deadline.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    db.commit()
    db.refresh(task)

    result = orm_to_dict(task)
    order = db.query(WorkOrder).filter(WorkOrder.id == task.work_order_id).first()
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == task.elderly_id).first()
    result["work_order_no"] = order.order_no if order else ""
    result["elderly_name"] = elderly.name if elderly else ""

    return success_response(data=result, message="整改任务创建成功")


@router.get("/rectification-tasks", response_model=ApiResponse[RectificationTaskListResponse])
def list_rectification_tasks(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    abnormal_warning_id: Optional[int] = Query(None, description="异常预警ID"),
    evaluation_task_id: Optional[int] = Query(None, description="评价任务ID"),
    work_order_id: Optional[int] = Query(None, description="工单ID"),
    elderly_id: Optional[int] = Query(None, description="老人ID"),
    status: Optional[str] = Query(None, description="状态"),
    responsible_person: Optional[str] = Query(None, description="责任人"),
    is_overdue: Optional[bool] = Query(None, description="是否超期"),
    start_date: Optional[str] = Query(None, description="开始日期"),
    end_date: Optional[str] = Query(None, description="结束日期"),
    db: Session = Depends(get_db)
):
    now = datetime.now()
    all_tasks = db.query(RectificationTask).filter(
        RectificationTask.status.in_([RectificationStatus.PENDING, RectificationStatus.IN_PROGRESS, RectificationStatus.COMPLETED])
    ).all()
    for task in all_tasks:
        if now > task.deadline and not task.is_overdue:
            task.is_overdue = True
    db.commit()

    query = db.query(RectificationTask)

    if abnormal_warning_id:
        query = query.filter(RectificationTask.abnormal_warning_id == abnormal_warning_id)
    if evaluation_task_id:
        query = query.filter(RectificationTask.evaluation_task_id == evaluation_task_id)
    if work_order_id:
        query = query.filter(RectificationTask.work_order_id == work_order_id)
    if elderly_id:
        query = query.filter(RectificationTask.elderly_id == elderly_id)
    if status:
        query = query.filter(RectificationTask.status == status)
    if responsible_person:
        query = query.filter(RectificationTask.responsible_person.like(f"%{responsible_person}%"))
    if is_overdue is not None:
        query = query.filter(RectificationTask.is_overdue == is_overdue)
    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        query = query.filter(RectificationTask.created_at >= start_dt)
    if end_date:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        query = query.filter(RectificationTask.created_at < end_dt)

    total = query.count()
    tasks = query.order_by(RectificationTask.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    items = []
    for task in tasks:
        t_dict = orm_to_dict(task)
        order = db.query(WorkOrder).filter(WorkOrder.id == task.work_order_id).first()
        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == task.elderly_id).first()
        t_dict["work_order_no"] = order.order_no if order else ""
        t_dict["elderly_name"] = elderly.name if elderly else ""
        items.append(t_dict)

    return success_response(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items
    })


@router.put("/rectification-tasks/{task_id}/in-progress", response_model=ApiResponse[RectificationTaskResponse])
def start_rectification(task_id: int, db: Session = Depends(get_db)):
    task = db.query(RectificationTask).filter(RectificationTask.id == task_id).first()
    if not task:
        return error_response(code=404, message="整改任务不存在")
    if task.status != RectificationStatus.PENDING:
        return error_response(code=400, message="当前状态不可开始处理")

    task.status = RectificationStatus.IN_PROGRESS

    if task.work_order_id:
        add_progress_record(
            db, task.work_order_id, ProgressType.SUPERVISION,
            operator_name=task.responsible_person, operator_role="responsible",
            remark="整改任务已开始处理"
        )

    db.commit()
    db.refresh(task)

    result = orm_to_dict(task)
    order = db.query(WorkOrder).filter(WorkOrder.id == task.work_order_id).first()
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == task.elderly_id).first()
    result["work_order_no"] = order.order_no if order else ""
    result["elderly_name"] = elderly.name if elderly else ""

    return success_response(data=result, message="整改任务已开始处理")


@router.put("/rectification-tasks/{task_id}/complete", response_model=ApiResponse[RectificationTaskResponse])
def complete_rectification(task_id: int, complete_data: RectificationTaskComplete, db: Session = Depends(get_db)):
    task = db.query(RectificationTask).filter(RectificationTask.id == task_id).first()
    if not task:
        return error_response(code=404, message="整改任务不存在")
    if task.status != RectificationStatus.IN_PROGRESS:
        return error_response(code=400, message="当前状态不可完成")

    task.handle_description = complete_data.handle_description
    task.handle_evidence = complete_data.handle_evidence
    task.completion_time = datetime.now()
    task.status = RectificationStatus.COMPLETED

    if task.work_order_id:
        add_progress_record(
            db, task.work_order_id, ProgressType.COMPLETED,
            operator_name=task.responsible_person, operator_role="responsible",
            remark=f"整改任务已完成处理，处理说明：{complete_data.handle_description[:50]}..."
        )

    db.commit()
    db.refresh(task)

    result = orm_to_dict(task)
    order = db.query(WorkOrder).filter(WorkOrder.id == task.work_order_id).first()
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == task.elderly_id).first()
    result["work_order_no"] = order.order_no if order else ""
    result["elderly_name"] = elderly.name if elderly else ""

    return success_response(data=result, message="整改任务已完成")


@router.post("/rectification-tasks/{task_id}/review", response_model=ApiResponse[RectificationTaskResponse])
def review_rectification(task_id: int, review_data: RectificationTaskReview, db: Session = Depends(get_db)):
    task = db.query(RectificationTask).filter(RectificationTask.id == task_id).first()
    if not task:
        return error_response(code=404, message="整改任务不存在")
    if task.status != RectificationStatus.COMPLETED:
        return error_response(code=400, message="当前状态不可复核")

    task.reviewer_name = review_data.reviewer_name
    task.review_remark = review_data.review_remark
    task.review_time = datetime.now()

    if review_data.passed:
        task.status = RectificationStatus.REVIEW_PASSED
    else:
        task.status = RectificationStatus.REVIEW_REJECTED

    if task.work_order_id:
        result_text = "通过" if review_data.passed else "驳回"
        add_progress_record(
            db, task.work_order_id, ProgressType.SUPERVISION,
            operator_name=review_data.reviewer_name, operator_role="reviewer",
            remark=f"整改复核{result_text}，复核意见：{review_data.review_remark[:50]}..."
        )

    db.commit()
    db.refresh(task)

    result = orm_to_dict(task)
    order = db.query(WorkOrder).filter(WorkOrder.id == task.work_order_id).first()
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == task.elderly_id).first()
    result["work_order_no"] = order.order_no if order else ""
    result["elderly_name"] = elderly.name if elderly else ""

    return success_response(data=result, message=f"整改复核{'通过' if review_data.passed else '驳回'}")


@router.put("/rectification-tasks/{task_id}/archive", response_model=ApiResponse[RectificationTaskResponse])
def archive_rectification(task_id: int, db: Session = Depends(get_db)):
    task = db.query(RectificationTask).filter(RectificationTask.id == task_id).first()
    if not task:
        return error_response(code=404, message="整改任务不存在")
    if task.status != RectificationStatus.REVIEW_PASSED:
        return error_response(code=400, message="仅复核通过的任务可归档")

    task.status = RectificationStatus.ARCHIVED
    task.archive_time = datetime.now()

    if task.work_order_id:
        add_progress_record(
            db, task.work_order_id, ProgressType.CLOSED,
            operator_name="系统", operator_role="system",
            remark="整改任务已归档"
        )

    db.commit()
    db.refresh(task)

    result = orm_to_dict(task)
    order = db.query(WorkOrder).filter(WorkOrder.id == task.work_order_id).first()
    elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == task.elderly_id).first()
    result["work_order_no"] = order.order_no if order else ""
    result["elderly_name"] = elderly.name if elderly else ""

    return success_response(data=result, message="整改任务已归档")


@router.get("/statistics", response_model=ApiResponse[QualityStatisticsResponse])
def get_quality_statistics(
    community: Optional[str] = Query(None, description="社区筛选"),
    service_type: Optional[str] = Query(None, description="服务类型筛选"),
    staff_name: Optional[str] = Query(None, description="服务人员筛选"),
    risk_level: Optional[str] = Query(None, description="风险等级筛选"),
    min_score: Optional[float] = Query(None, ge=0, le=5, description="最低评分"),
    max_score: Optional[float] = Query(None, ge=0, le=5, description="最高评分"),
    abnormal_tag_id: Optional[int] = Query(None, description="异常标签筛选"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    db: Session = Depends(get_db)
):
    from sqlalchemy import func, and_, case

    base_query = db.query(EvaluationTask).filter(
        EvaluationTask.overall_score.isnot(None)
    )

    if community:
        base_query = base_query.join(ElderlyProfile).filter(ElderlyProfile.community == community)
    if service_type:
        base_query = base_query.join(EvaluationTemplate).filter(EvaluationTemplate.service_type == service_type)
    if staff_name:
        base_query = base_query.filter(EvaluationTask.assignee_name.like(f"%{staff_name}%"))
    if min_score is not None:
        base_query = base_query.filter(EvaluationTask.overall_score >= min_score)
    if max_score is not None:
        base_query = base_query.filter(EvaluationTask.overall_score <= max_score)

    start_dt = None
    end_dt = None
    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        base_query = base_query.filter(EvaluationTask.created_at >= start_dt)
    if end_date:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        base_query = base_query.filter(EvaluationTask.created_at < end_dt)

    total_evaluations = base_query.count()

    avg_overall = 0.0
    if total_evaluations > 0:
        avg_result = db.query(func.avg(EvaluationTask.overall_score)).filter(
            EvaluationTask.id.in_([t.id for t in base_query.all()])
        ).scalar()
        avg_overall = round(avg_result or 0.0, 2)

    low_score_count = base_query.filter(EvaluationTask.overall_score < 3.0).count()
    abnormal_count = base_query.filter(EvaluationTask.is_abnormal == True).count()
    complaint_count = db.query(SatisfactionFeedback).filter(
        SatisfactionFeedback.is_complaint == True,
        SatisfactionFeedback.evaluation_task_id.in_([t.id for t in base_query.all()])
    ).count()

    service_type_stats = []
    type_query = db.query(
        EvaluationTemplate.service_type,
        func.count(EvaluationTask.id),
        func.avg(EvaluationTask.overall_score)
    ).join(EvaluationTemplate).filter(
        EvaluationTask.id.in_([t.id for t in base_query.all()])
    ).group_by(EvaluationTemplate.service_type).all()

    for st_type, count, avg_score in type_query:
        service_type_stats.append(ServiceTypeSatisfactionItem(
            service_type=st_type,
            total_evaluations=count,
            avg_satisfaction=round(avg_score or 0.0, 2),
            weighted_avg=round(avg_score or 0.0, 2)
        ))

    staff_ranking = []
    staff_query = db.query(
        EvaluationTask.assignee_name,
        func.count(EvaluationTask.id),
        func.avg(EvaluationTask.overall_score),
        func.sum(case((EvaluationTask.overall_score < 3.0, 1), else_=0))
    ).filter(
        EvaluationTask.assignee_name.isnot(None),
        EvaluationTask.id.in_([t.id for t in base_query.all()])
    ).group_by(EvaluationTask.assignee_name).all()

    staff_complaint_counts = defaultdict(int)
    complaint_feedbacks = db.query(SatisfactionFeedback).filter(
        SatisfactionFeedback.is_complaint == True,
        SatisfactionFeedback.evaluation_task_id.in_([t.id for t in base_query.all()])
    ).all()
    for fb in complaint_feedbacks:
        eval_task = db.query(EvaluationTask).filter(EvaluationTask.id == fb.evaluation_task_id).first()
        if eval_task and eval_task.assignee_name:
            staff_complaint_counts[eval_task.assignee_name] += 1

    staff_list = []
    for staff_name, count, avg_score, low_count in staff_query:
        staff_list.append({
            "staff_name": staff_name,
            "total_evaluations": count,
            "avg_score": round(avg_score or 0.0, 2),
            "low_score_count": low_count,
            "complaint_count": staff_complaint_counts.get(staff_name, 0)
        })

    staff_list.sort(key=lambda x: (-x["avg_score"], x["low_score_count"]))
    for idx, staff in enumerate(staff_list):
        staff_ranking.append(StaffQualityRankingItem(
            staff_name=staff["staff_name"],
            total_evaluations=staff["total_evaluations"],
            avg_score=staff["avg_score"],
            low_score_count=staff["low_score_count"],
            complaint_count=staff["complaint_count"],
            ranking=idx + 1
        ))

    warning_query = db.query(AbnormalWarning)
    if start_dt:
        warning_query = warning_query.filter(AbnormalWarning.trigger_time >= start_dt)
    if end_dt:
        warning_query = warning_query.filter(AbnormalWarning.trigger_time < end_dt)
    if risk_level:
        warning_query = warning_query.filter(AbnormalWarning.risk_level == risk_level)
    if abnormal_tag_id:
        warning_query = warning_query.filter(AbnormalWarning.tag_id == abnormal_tag_id)

    community_abnormal = defaultdict(lambda: {
        "total_abnormal": 0,
        "low_satisfaction_count": 0,
        "no_visit_count": 0,
        "repeat_low_score_count": 0,
        "staff_abnormal_count": 0,
        "multiple_complaints_count": 0
    })

    all_warnings = warning_query.all()
    for w in all_warnings:
        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == w.elderly_id).first()
        comm = elderly.community if elderly else "未知"
        if community and comm != community:
            continue
        community_abnormal[comm]["total_abnormal"] += 1
        if w.abnormal_type == AbnormalType.LOW_SATISFACTION:
            community_abnormal[comm]["low_satisfaction_count"] += 1
        elif w.abnormal_type == AbnormalType.NO_VISIT:
            community_abnormal[comm]["no_visit_count"] += 1
        elif w.abnormal_type == AbnormalType.REPEAT_LOW_SCORE:
            community_abnormal[comm]["repeat_low_score_count"] += 1
        elif w.abnormal_type == AbnormalType.STAFF_CONTINUOUS_ABNORMAL:
            community_abnormal[comm]["staff_abnormal_count"] += 1
        elif w.abnormal_type == AbnormalType.MULTIPLE_COMPLAINTS:
            community_abnormal[comm]["multiple_complaints_count"] += 1

    community_abnormal_list = []
    for comm, data in community_abnormal.items():
        community_abnormal_list.append(CommunityAbnormalItem(
            community=comm,
            **data
        ))

    overdue_query = db.query(RectificationTask).filter(
        RectificationTask.is_overdue == True,
        RectificationTask.status.in_([RectificationStatus.PENDING, RectificationStatus.IN_PROGRESS])
    )
    if start_dt:
        overdue_query = overdue_query.filter(RectificationTask.created_at >= start_dt)
    if end_dt:
        overdue_query = overdue_query.filter(RectificationTask.created_at < end_dt)

    overdue_tasks = overdue_query.all()
    overdue_list = []
    for task in overdue_tasks:
        now = datetime.now()
        overdue_days = (now - task.deadline).days
        order = db.query(WorkOrder).filter(WorkOrder.id == task.work_order_id).first()
        elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == task.elderly_id).first()
        overdue_list.append(OverdueRectificationItem(
            task_id=task.id,
            task_no=task.task_no,
            title=task.title,
            responsible_person=task.responsible_person,
            deadline=task.deadline,
            overdue_days=overdue_days,
            work_order_no=order.order_no if order else "",
            elderly_name=elderly.name if elderly else ""
        ))

    complaint_query = db.query(SatisfactionFeedback).filter(
        SatisfactionFeedback.is_complaint == True
    )
    if start_dt:
        complaint_query = complaint_query.filter(SatisfactionFeedback.submit_time >= start_dt)
    if end_dt:
        complaint_query = complaint_query.filter(SatisfactionFeedback.submit_time < end_dt)

    all_complaints = complaint_query.all()
    elderly_complaints = defaultdict(list)
    for fb in all_complaints:
        eval_task = db.query(EvaluationTask).filter(EvaluationTask.id == fb.evaluation_task_id).first()
        if eval_task:
            elderly_complaints[eval_task.elderly_id].append(fb)

    repeat_complaint_list = []
    for elderly_id, complaints in elderly_complaints.items():
        if len(complaints) >= 2:
            elderly = db.query(ElderlyProfile).filter(ElderlyProfile.id == elderly_id).first()
            if community and elderly and elderly.community != community:
                continue
            last_complaint = max(complaints, key=lambda x: x.submit_time)
            related_orders = []
            for c in complaints:
                eval_task = db.query(EvaluationTask).filter(EvaluationTask.id == c.evaluation_task_id).first()
                if eval_task:
                    order = db.query(WorkOrder).filter(WorkOrder.id == eval_task.work_order_id).first()
                    related_orders.append({
                        "order_id": eval_task.work_order_id,
                        "order_no": order.order_no if order else "",
                        "complaint_time": c.submit_time,
                        "complaint_content": c.complaint_content
                    })
            repeat_complaint_list.append(RepeatComplaintElderlyItem(
                elderly_id=elderly_id,
                elderly_name=elderly.name if elderly else "",
                community=elderly.community if elderly else "",
                complaint_count=len(complaints),
                last_complaint_time=last_complaint.submit_time,
                related_orders=related_orders
            ))

    repeat_complaint_list.sort(key=lambda x: -x.complaint_count)

    all_tasks_query = db.query(EvaluationTask)
    if start_dt:
        all_tasks_query = all_tasks_query.filter(EvaluationTask.created_at >= start_dt)
    if end_dt:
        all_tasks_query = all_tasks_query.filter(EvaluationTask.created_at < end_dt)

    total_tasks = all_tasks_query.count()
    completed_tasks = all_tasks_query.filter(
        EvaluationTask.status.in_([EvaluationTaskStatus.REVIEWED, EvaluationTaskStatus.CLOSED])
    ).count()
    evaluation_completion_rate = round(completed_tasks / total_tasks * 100, 2) if total_tasks > 0 else 0.0

    visit_query = db.query(VisitRecord).filter(VisitRecord.archived == True)
    if start_dt:
        visit_query = visit_query.filter(VisitRecord.visit_time >= start_dt)
    if end_dt:
        visit_query = visit_query.filter(VisitRecord.visit_time < end_dt)

    total_visits = visit_query.count()
    total_with_visits = 0
    if total_tasks > 0:
        task_ids = [t.id for t in all_tasks_query.all()]
        task_orders = db.query(EvaluationTask.work_order_id).filter(
            EvaluationTask.id.in_(task_ids)
        ).all()
        order_ids = [o[0] for o in task_orders]
        total_with_visits = db.query(VisitRecord).filter(
            VisitRecord.work_order_id.in_(order_ids),
            VisitRecord.archived == True
        ).distinct(VisitRecord.work_order_id).count()

    visit_coverage_rate = round(total_with_visits / total_tasks * 100, 2) if total_tasks > 0 else 0.0

    quality_trend = []
    for i in range(29, -1, -1):
        day = (datetime.now() - timedelta(days=i)).date()
        day_start = datetime.combine(day, datetime.min.time())
        day_end = day_start + timedelta(days=1)

        day_tasks = base_query.filter(
            EvaluationTask.created_at >= day_start,
            EvaluationTask.created_at < day_end
        ).all()
        day_task_ids = [t.id for t in day_tasks]

        total_eval = len(day_tasks)
        avg_score = 0.0
        if total_eval > 0:
            scores = [t.overall_score for t in day_tasks if t.overall_score is not None]
            avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0

        low_count = len([t for t in day_tasks if t.overall_score is not None and t.overall_score < 3.0])

        day_warnings = warning_query.filter(
            AbnormalWarning.trigger_time >= day_start,
            AbnormalWarning.trigger_time < day_end
        ).count()

        quality_trend.append(QualityTrendItem(
            date=day.strftime("%Y-%m-%d"),
            total_evaluations=total_eval,
            avg_satisfaction=avg_score,
            low_score_count=low_count,
            abnormal_count=day_warnings
        ))

    summary = {
        "total_evaluations": total_evaluations,
        "avg_overall_score": avg_overall,
        "low_score_count": low_score_count,
        "low_score_rate": round(low_score_count / total_evaluations * 100, 2) if total_evaluations > 0 else 0.0,
        "abnormal_count": abnormal_count,
        "complaint_count": complaint_count,
        "evaluation_completion_rate": evaluation_completion_rate,
        "visit_coverage_rate": visit_coverage_rate
    }

    filters = {
        "community": community,
        "service_type": service_type,
        "staff_name": staff_name,
        "risk_level": risk_level,
        "min_score": min_score,
        "max_score": max_score,
        "abnormal_tag_id": abnormal_tag_id,
        "start_date": start_date,
        "end_date": end_date
    }

    result = QualityStatisticsResponse(
        summary=summary,
        service_type_satisfaction=service_type_stats,
        staff_quality_ranking=staff_ranking,
        community_abnormal_distribution=community_abnormal_list,
        overdue_rectification_list=overdue_list,
        repeat_complaint_elderly_list=repeat_complaint_list,
        evaluation_completion_rate=evaluation_completion_rate,
        visit_coverage_rate=visit_coverage_rate,
        quality_trend_30days=quality_trend,
        filters=filters
    )

    return success_response(data=result)