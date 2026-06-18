from pydantic import BaseModel, Field
from typing import Optional, Generic, TypeVar
from sqlalchemy.orm import InstanceState

T = TypeVar("T")


def orm_to_dict(obj):
    if obj is None:
        return None
    if isinstance(obj, list):
        return [orm_to_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {k: orm_to_dict(v) for k, v in obj.items()}
    
    result = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.name)
        result[column.name] = value
    return result


class ApiResponse(BaseModel, Generic[T]):
    code: int = Field(default=200, description="响应码，200表示成功")
    message: str = Field(default="success", description="响应消息")
    data: Optional[T] = Field(default=None, description="响应数据")


def success_response(data: any = None, message: str = "success") -> ApiResponse:
    return ApiResponse(code=200, message=message, data=data)


def error_response(code: int = 400, message: str = "error", data: any = None) -> ApiResponse:
    return ApiResponse(code=code, message=message, data=data)
