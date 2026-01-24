# УПРОЩЕННЫЙ storage_service.py ДЛЯ ОДНОГО АККАУНТА:

import os
import logging
from typing import Optional, Tuple
from datetime import datetime
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY, IMAGE_QUALITY

logger = logging.getLogger(__name__)

class StorageService:
    """Управление хранением изображений на Supabase"""
    
    BUCKET_NAME = "recipe-images"
    
    def __init__(self):
        self.client: Optional[Client] = None
        self.available = False
        
    async def initialize(self):
        """Инициализация подключения к Supabase Storage"""
        if SUPABASE_URL and SUPABASE_KEY:
            try:
                self.client = create_client(SUPABASE_URL, SUPABASE_KEY)
                await self._ensure_bucket_exists()
                self.available = True
                logger.info("✅ Хранилище Supabase подключено")
            except Exception as e:
                logger.error(f"❌ Ошибка подключения к хранилищу: {e}")
                self.available = False
        else:
            logger.error("❌ Supabase не настроен! Изображения не будут сохраняться")
    
    async def _ensure_bucket_exists(self):
        """Проверяет существование bucket, создаёт если нужно"""
        try:
            # Пробуем получить список buckets
            buckets = self.client.storage.list_buckets()
            bucket_names = [b.name for b in buckets]
            
            if self.BUCKET_NAME not in bucket_names:
                # Создаём bucket
                self.client.storage.create_bucket(
                    self.BUCKET_NAME,
                    options={
                        "public": True,
                        "allowedMimeTypes": ["image/*"],
                        "fileSizeLimit": 10485760  # 10MB
                    }
                )
                logger.info(f"✅ Bucket '{self.BUCKET_NAME}' создан")
            else:
                logger.debug(f"Bucket '{self.BUCKET_NAME}' уже существует")
                
        except Exception as e:
            if "already exists" in str(e).lower():
                logger.debug(f"Bucket '{self.BUCKET_NAME}' уже существует")
            else:
                logger.error(f"❌ Ошибка проверки bucket: {e}")
                raise
    
    async def upload_image(
        self, 
        image_data: bytes, 
        filename: str
    ) -> Tuple[Optional[str], str]:
        """
        Загружает изображение на Supabase
        
        Returns:
            Tuple[url, backend]: (URL изображения или None, 'supabase')
        """
        if not self.available:
            logger.error("❌ Хранилище недоступно")
            return None, "failed"
        
        try:
            # Генерируем уникальное имя файла
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_filename = self._sanitize_filename(filename)
            unique_filename = f"{timestamp}_{safe_filename}"
            
            # Загружаем файл
            response = self.client.storage.from_(self.BUCKET_NAME).upload(
                path=unique_filename,
                file=image_data,
                file_options={"content-type": "image/jpeg"}
            )
            
            # Получаем публичный URL
            public_url = self.client.storage.from_(self.BUCKET_NAME).get_public_url(unique_filename)
            
            logger.info(f"✅ Изображение загружено: {unique_filename}")
            return public_url, "supabase"
            
        except Exception as e:
            # Если файл уже существует - получаем его URL
            if "duplicate" in str(e).lower() or "already exists" in str(e).lower():
                public_url = self.client.storage.from_(self.BUCKET_NAME).get_public_url(filename)
                return public_url, "supabase"
            
            logger.error(f"❌ Ошибка загрузки изображения: {e}")
            return None, "failed"
    
    def _sanitize_filename(self, filename: str) -> str:
        """Очищает имя файла от недопустимых символов"""
        safe_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
        sanitized = "".join(c if c in safe_chars else "_" for c in filename)
        
        if len(sanitized) > 100:
            name, ext = os.path.splitext(sanitized)
            sanitized = name[:95] + ext
        
        return sanitized

# Глобальный экземпляр
storage_service = StorageService()
