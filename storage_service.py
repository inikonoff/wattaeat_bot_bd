import os
import logging
import hashlib
from typing import Optional, Tuple
from datetime import datetime
from supabase import create_client, Client
from config import (
    SUPABASE_URL, SUPABASE_KEY,
    SUPABASE_IMAGES_URL, SUPABASE_IMAGES_KEY,
    IMAGE_QUALITY
)

logger = logging.getLogger(__name__)

class StorageService:
    """Управление хранением изображений на Supabase с fallback"""
    
    BUCKET_NAME = "recipe-images"  # Название bucket в Supabase
    
    def __init__(self):
        self.main_client: Optional[Client] = None
        self.fallback_client: Optional[Client] = None
        self.main_available = False
        self.fallback_available = False
        
    async def initialize(self):
        """Инициализация подключений к Supabase Storage"""
        # Основное хранилище
        if SUPABASE_URL and SUPABASE_KEY:
            try:
                self.main_client = create_client(SUPABASE_URL, SUPABASE_KEY)
                # Проверяем bucket
                await self._ensure_bucket_exists(self.main_client, "main")
                self.main_available = True
                logger.info("✅ Основное хранилище Supabase подключено")
            except Exception as e:
                logger.error(f"❌ Ошибка подключения к основному хранилищу: {e}")
        else:
            logger.warning("⚠️ Основное хранилище Supabase не настроено")
        
        # Fallback хранилище (второй аккаунт)
        if SUPABASE_IMAGES_URL and SUPABASE_IMAGES_KEY:
            try:
                self.fallback_client = create_client(SUPABASE_IMAGES_URL, SUPABASE_IMAGES_KEY)
                await self._ensure_bucket_exists(self.fallback_client, "fallback")
                self.fallback_available = True
                logger.info("✅ Fallback хранилище Supabase подключено")
            except Exception as e:
                logger.error(f"❌ Ошибка подключения к fallback хранилищу: {e}")
        else:
            logger.info("ℹ️ Fallback хранилище не настроено (опционально)")
        
        if not self.main_available and not self.fallback_available:
            logger.error("❌ Ни одно хранилище не доступно! Изображения не будут сохраняться")
    
    async def _ensure_bucket_exists(self, client: Client, storage_type: str):
        """Проверяет существование bucket, создаёт если нужно"""
        try:
            # Пробуем получить список buckets
            buckets = client.storage.list_buckets()
            bucket_names = [b.name for b in buckets]
            
            if self.BUCKET_NAME not in bucket_names:
                # Создаём bucket
                client.storage.create_bucket(
                    self.BUCKET_NAME,
                    options={"public": True}  # Публичный доступ
                )
                logger.info(f"✅ Bucket '{self.BUCKET_NAME}' создан в {storage_type} хранилище")
            else:
                logger.debug(f"Bucket '{self.BUCKET_NAME}' уже существует в {storage_type}")
                
        except Exception as e:
            # Если bucket уже существует - игнорируем ошибку
            if "already exists" in str(e).lower():
                logger.debug(f"Bucket '{self.BUCKET_NAME}' уже существует")
            else:
                raise
    
    async def upload_image(
        self, 
        image_data: bytes, 
        filename: str
    ) -> Tuple[Optional[str], str]:
        """
        Загружает изображение с автоматическим fallback
        
        Args:
            image_data: Данные изображения
            filename: Имя файла (без пути)
            
        Returns:
            Tuple[url, backend]: (URL изображения или None, название backend)
        """
        # Генерируем уникальное имя файла
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = self._sanitize_filename(filename)
        unique_filename = f"{timestamp}_{safe_filename}"
        
        # Пробуем основное хранилище
        if self.main_available:
            try:
                url = await self._upload_to_storage(
                    self.main_client, 
                    image_data, 
                    unique_filename
                )
                if url:
                    logger.info(f"✅ Изображение загружено в основное хранилище: {unique_filename}")
                    return url, "supabase_main"
            except Exception as e:
                logger.error(f"❌ Ошибка загрузки в основное хранилище: {e}")
        
        # Fallback на второе хранилище
        if self.fallback_available:
            try:
                url = await self._upload_to_storage(
                    self.fallback_client, 
                    image_data, 
                    unique_filename
                )
                if url:
                    logger.info(f"✅ Изображение загружено в fallback хранилище: {unique_filename}")
                    return url, "supabase_fallback"
            except Exception as e:
                logger.error(f"❌ Ошибка загрузки в fallback хранилище: {e}")
        
        # Если оба хранилища недоступны - сохраняем локально (последний резерв)
        try:
            local_path = os.path.join("temp", unique_filename)
            with open(local_path, "wb") as f:
                f.write(image_data)
            logger.warning(f"⚠️ Изображение сохранено локально: {local_path}")
            return None, "local_temp"
        except Exception as e:
            logger.error(f"❌ Критическая ошибка сохранения изображения: {e}")
            return None, "failed"
    
    async def _upload_to_storage(
        self, 
        client: Client, 
        image_data: bytes, 
        filename: str
    ) -> Optional[str]:
        """Загружает изображение в конкретное хранилище"""
        try:
            # Загружаем файл
            response = client.storage.from_(self.BUCKET_NAME).upload(
                path=filename,
                file=image_data,
                file_options={"content-type": "image/jpeg"}
            )
            
            # Получаем публичный URL
            public_url = client.storage.from_(self.BUCKET_NAME).get_public_url(filename)
            
            return public_url
            
        except Exception as e:
            # Если файл уже существует - получаем его URL
            if "duplicate" in str(e).lower() or "already exists" in str(e).lower():
                public_url = client.storage.from_(self.BUCKET_NAME).get_public_url(filename)
                return public_url
            raise
    
    async def delete_image(self, filename: str, backend: str = "supabase_main"):
        """Удаляет изображение из хранилища"""
        try:
            client = self.main_client if backend == "supabase_main" else self.fallback_client
            
            if not client:
                logger.warning(f"Клиент {backend} недоступен для удаления")
                return
            
            client.storage.from_(self.BUCKET_NAME).remove([filename])
            logger.info(f"🗑️ Изображение удалено: {filename}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка удаления изображения: {e}")
    
    def _sanitize_filename(self, filename: str) -> str:
        """Очищает имя файла от недопустимых символов"""
        # Убираем небезопасные символы
        safe_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
        sanitized = "".join(c if c in safe_chars else "_" for c in filename)
        
        # Ограничиваем длину
        if len(sanitized) > 100:
            name, ext = os.path.splitext(sanitized)
            sanitized = name[:95] + ext
        
        return sanitized
    
    async def get_storage_stats(self) -> dict:
        """Получает статистику по хранилищам"""
        stats = {
            "main_available": self.main_available,
            "fallback_available": self.fallback_available,
        }
        
        # Пробуем получить размер bucket (если API поддерживает)
        try:
            if self.main_available:
                files = self.main_client.storage.from_(self.BUCKET_NAME).list()
                stats["main_files_count"] = len(files)
        except:
            pass
            
        return stats

# Глобальный экземпляр
storage_service = StorageService()
