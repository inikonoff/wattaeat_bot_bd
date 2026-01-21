import os
import asyncio
import logging
import io
from typing import Optional, Dict, Any, List
import replicate
from PIL import Image
from datetime import datetime
from config import REPLICATE_API_KEY, IMAGE_QUALITY

logger = logging.getLogger(__name__)

class ReplicateImageService:
    """Генерация изображений через Replicate с fallback по моделям"""
    
    # Приоритет моделей (от лучшей к запасным)
    MODEL_PRIORITY = [
        "flux-1.1-pro",
        "flux-kontext-pro",
        "sdxl",
        "realvisxl"
    ]
    
    # Пути к моделям на Replicate
    MODELS = {
        "flux-1.1-pro": "black-forest-labs/flux-1.1-pro",
        "flux-kontext-pro": "black-forest-labs/flux-kontext-pro",
        "sdxl": "stability-ai/sdxl",
        "realvisxl": "sgriebel/realvisxl-v4.0"
    }
    
    # Параметры по умолчанию для каждой модели
    # ВНИМАНИЕ: У моделей FLUX нет параметра negative_prompt в API
    MODEL_PARAMS = {
        "flux-1.1-pro": {
            "aspect_ratio": "1:1",
            "output_format": "jpg",
            "output_quality": 80
        },
        "flux-kontext-pro": {
            "aspect_ratio": "1:1",
            "output_format": "jpg"
        },
        "sdxl": {
            "width": 1024,
            "height": 1024,
            "refine": "expert_ensemble_refiner",
            "scheduler": "K_EULER",
            "num_inference_steps": 30,
            "guidance_scale": 7.5,
            "negative_prompt": "text, watermark, logo, blurry, cartoon, 3d render, drawing, bad quality, ugly, messy, distorted"
        },
        "realvisxl": {
            "width": 1024,
            "height": 1024,
            "num_inference_steps": 30,
            "guidance_scale": 7.0,
            "negative_prompt": "text, watermark, logo, blurry, cartoon, 3d render, drawing, bad quality, ugly"
        }
    }

    def __init__(self, model: str = "flux-1.1-pro"):
        if not REPLICATE_API_KEY:
            raise ValueError("REPLICATE_API_KEY не установлен")
        
        self.client = replicate.Client(api_token=REPLICATE_API_KEY)
        self.model_name = model
        self.model_path = self.MODELS.get(model, self.MODELS["flux-1.1-pro"])

    async def generate(self, dish_name: str, recipe_text: str = "") -> Optional[bytes]:
        """Генерация изображения по названию блюда"""
        try:
            # Формируем промпт: акцент на фуд-фотографию
            prompt = (
                f"Professional food photography of {dish_name}, "
                f"gourmet presentation, highly detailed, 8k, appetizing, "
                f"soft natural lighting, depth of field, studio quality."
            )
            
            params = self.MODEL_PARAMS.get(self.model_name, {}).copy()
            params["prompt"] = prompt

            # Запуск генерации (через asyncio для предотвращения блокировки)
            output = await asyncio.to_thread(
                self.client.run,
                self.model_path,
                input=params
            )

            if not output:
                return None

            # Получаем URL изображения (Replicate возвращает список или строку)
            image_url = output[0] if isinstance(output, list) else output
            
            # Скачиваем изображение
            import requests
            response = await asyncio.to_thread(requests.get, image_url)
            
            if response.status_code == 200:
                return self._optimize_image(response.content)
            
            return None

        except Exception as e:
            logger.error(f"Ошибка при генерации ({self.model_name}): {e}")
            raise e

    def _optimize_image(self, image_data: bytes) -> bytes:
        """Сжатие изображения перед отправкой в Telegram"""
        try:
            img = Image.open(io.BytesIO(image_data))
            
            # Конвертируем в RGB если нужно
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            
            output = io.BytesIO()
            # Оптимизация размера для Telegram (макс качество 80-85)
            img.save(output, format="JPEG", quality=IMAGE_QUALITY, optimize=True)
            return output.getvalue()
        except Exception as e:
            logger.error(f"❌ Ошибка оптимизации изображения: {e}")
            return image_data


# ==================== ФУНКЦИЯ С FALLBACK ====================\n
async def generate_with_fallback(dish_name: str, recipe_text: str) -> Optional[bytes]:
    """
    Генерирует изображение с автоматическим переключением моделей при ошибке
    """
    for model_name in ReplicateImageService.MODEL_PRIORITY:
        try:
            logger.info(f"🎨 Попытка генерации с моделью: {model_name}")
            service = ReplicateImageService(model=model_name)
            image = await service.generate(dish_name, recipe_text)
            
            if image:
                logger.info(f"✅ Успешная генерация с моделью: {model_name}")
                return image
            else:
                logger.warning(f"⚠️ Модель {model_name} вернула пустой результат")
                
        except Exception as e:
            logger.warning(f"⚠️ Модель {model_name} не сработала: {e}")
            # Если ошибка в API ключе или балансе, Replicate выкинет специфическую ошибку,
            # но мы продолжаем пробовать другие модели или выходим, если проблема общая.
            if "402" in str(e): # Payment Required
                logger.error("❌ Ошибка оплаты Replicate. Проверьте баланс.")
                return None
            continue
    
    logger.error("❌ Ни одна модель из списка MODEL_PRIORITY не сработала")
    return None