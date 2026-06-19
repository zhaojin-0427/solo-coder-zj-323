from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError, HTTPException
from fastapi.responses import JSONResponse
from app.database import init_db
from app.routes.elderly import router as elderly_router
from app.routes.orders import router as orders_router
from app.routes.aggregation import router as aggregation_router
from app.routes.supervision import router as supervision_router
from app.routes.resource import router as resource_router

app = FastAPI(
    title="社区助老服务工单归档与进度聚合 API 服务",
    description="社区助老服务闭环督办与风险升级系统：支持服务类型级SLA配置、社区级节假日/工作时段扣除规则、重复诉求合并建议、督办记录、人工确认升级、跟进计划和回访结果归档；系统可按同一老人、同类服务、近7/15/30天窗口识别疑似重复诉求并生成可确认的合并建议；对超时未闭环工单按风险等级、超时时长、历史未完成次数自动计算督办优先级，并生成下一步跟进建议；新增助老服务资源调度与供需匹配能力，包括服务资源库、服务人员档案、技能标签、可服务社区、排班时段、容量上限、工单自动匹配、人工改派、冲突检测、资源占用释放和调度统计。",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    init_db()


@app.get("/", tags=["系统"])
async def root():
    return {
        "code": 200,
        "message": "success",
        "data": {
            "name": "社区助老服务工单归档与进度聚合 API 服务",
            "version": "1.0.0",
            "status": "running"
        }
    }


@app.get("/health", tags=["系统"])
async def health_check():
    return {
        "code": 200,
        "message": "success",
        "data": {"status": "healthy"}
    }


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    error_details = []
    for error in errors:
        loc = " -> ".join([str(x) for x in error.get("loc", [])])
        msg = error.get("msg", "")
        error_details.append(f"{loc}: {msg}")
    message = "参数校验失败: " + "; ".join(error_details) if error_details else "参数校验失败"
    return JSONResponse(
        status_code=200,
        content={
            "code": 400,
            "message": message,
            "data": None
        }
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=200,
        content={
            "code": exc.status_code,
            "message": exc.detail,
            "data": None
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=200,
        content={
            "code": 500,
            "message": f"服务器内部错误: {str(exc)}",
            "data": None
        }
    )


app.include_router(elderly_router)
app.include_router(orders_router)
app.include_router(aggregation_router)
app.include_router(supervision_router)
app.include_router(resource_router)
