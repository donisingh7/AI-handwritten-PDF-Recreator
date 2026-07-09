from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.schemas import ModelOptionResponse
from app.services.model_options_service import ModelOptionsService

router = APIRouter(tags=["models"])


@router.get("/models", response_model=list[ModelOptionResponse])
def list_models(settings: Settings = Depends(get_settings)) -> list[ModelOptionResponse]:
    service = ModelOptionsService(settings)
    return [ModelOptionResponse(**option.as_response()) for option in service.list_options()]
