from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import init_db
from app.routes.elderly import router as elderly_router
from app.routes.orders import router as orders_router
from app.routes.aggregation import router as aggregation_router

app = FastAPI(
    title="社区助老服务工单归档与进度聚合 API 服务",
    description="社区工作人员创建工单时登记老人基础信息、服务类型、预约时段、风险备注和联系人，占位接单人员回传到达时间、处理摘要和未完成原因，服务端负责聚合同一老人近期服务记录、识别重复诉求和超时未闭环工单，并生成后续跟进建议。",
    version="1.0.0"
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


app.include_router(elderly_router)
app.include_router(orders_router)
app.include_router(aggregation_router)
