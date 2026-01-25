import os
import asyncio
import aiohttp
import aiofiles
import textwrap
import logging
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

# Импортируем путь к папке шрифтов из конфига, чтобы Docker не запутался
from config import FONTS_DIR

# Константы дизайна (можно вынести в config, но удобнее держать тут)
CARD_WIDTH = 1200
CARD_HEIGHT = 1600
BG_COLOR = "#FDFBF7"       # Теплый кремовый
TEXT_COLOR = "#2C2C2C"     # Глубокий серый
ACCENT_COLOR = "#8B7355"   # Благородный бронзовый/оливковый

logger = logging.getLogger(__name__)

class RecipeCardGenerator:
    # Шрифты Lora (с засечками) для элегантности + Roboto для цифр
    FONTS_URLS = {
        "Lora-Bold.ttf": "https://github.com/google/fonts/raw/main/ofl/lora/Lora-Bold.ttf",
        "Lora-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/lora/Lora-Regular.ttf",
        "Lora-Italic.ttf": "https://github.com/google/fonts/raw/main/ofl/lora/Lora-Italic.ttf",
        "Roboto-Regular.ttf": "https://github.com/google/fonts/raw/main/apache/roboto/Roboto-Regular.ttf"
    }
    
    def __init__(self):
        self.fonts_loaded = False
        self.fonts = {}
        
    def _get_font_path(self, name):
        # Используем переменную из config.py
        return os.path.join(FONTS_DIR, name)

    async def ensure_fonts(self):
        """Скачивает шрифты при старте бота"""
        if not os.path.exists(FONTS_DIR):
            os.makedirs(FONTS_DIR)

        logger.info("📦 Проверка шрифтов для карточек...")
        async with aiohttp.ClientSession() as session:
            for filename, url in self.FONTS_URLS.items():
                path = self._get_font_path(filename)
                # Если файла нет или он пустой
                if not os.path.exists(path) or os.path.getsize(path) == 0:
                    logger.info(f"📥 Скачиваю шрифт {filename}...")
                    try:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                content = await resp.read()
                                async with aiofiles.open(path, mode='wb') as f:
                                    await f.write(content)
                            else:
                                logger.error(f"❌ Ошибка скачивания {filename}: {resp.status}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка сети для шрифта {filename}: {e}")
        
        self._load_fonts()

    def _load_fonts(self):
        """Загрузка шрифтов в память"""
        try:
            self.fonts['title'] = ImageFont.truetype(self._get_font_path("Lora-Bold.ttf"), 85)
            self.fonts['section'] = ImageFont.truetype(self._get_font_path("Lora-Bold.ttf"), 45)
            self.fonts['main'] = ImageFont.truetype(self._get_font_path("Lora-Regular.ttf"), 38)
            self.fonts['italic'] = ImageFont.truetype(self._get_font_path("Lora-Italic.ttf"), 38)
            self.fonts['meta'] = ImageFont.truetype(self._get_font_path("Roboto-Regular.ttf"), 30)
            self.fonts_loaded = True
            logger.info("✅ Шрифты успешно загружены")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки шрифтов (использую дефолтные): {e}")
            default = ImageFont.load_default()
            self.fonts = {k: default for k in ['title', 'section', 'main', 'italic', 'meta']}
            self.fonts_loaded = True

    def generate_card(self, title, ingredients, time, portions, difficulty, chef_tip, dish_image_data=None):
        # Страховка: если шрифты еще не загружены
        if not self.fonts_loaded: 
            self._load_fonts()

        img = Image.new('RGB', (CARD_WIDTH, CARD_HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        margin = 80

        # --- 1. ЗАГОЛОВОК ---
        title_text = title.upper()
        # Авто-подбор размера шрифта если заголовок очень длинный
        if len(title_text) > 40:
            font_title = self.fonts['section'] # Поменьше
        else:
            font_title = self.fonts['title']

        wrapped_title = textwrap.wrap(title_text, width=25)
        current_y = 100
        
        for line in wrapped_title:
            bbox = draw.textbbox((0, 0), line, font=font_title)
            text_w = bbox[2] - bbox[0]
            draw.text(((CARD_WIDTH - text_w)//2, current_y), line, font=font_title, fill=TEXT_COLOR)
            current_y += 100

        # Разделительная линия
        draw.line([(margin, current_y + 20), (CARD_WIDTH - margin, current_y + 20)], fill=ACCENT_COLOR, width=2)
        current_y += 80

        # --- 2. ФОТО И ИНГРЕДИЕНТЫ (2 КОЛОНКИ) ---
        photo_width = 500
        photo_height = 600
        
        # Левая колонка - Фото
        if dish_image_data:
            try:
                dish_img = Image.open(BytesIO(dish_image_data)).convert("RGB")
                
                # Smart Crop (Центрирование и кроп)
                aspect = dish_img.width / dish_img.height
                target_aspect = photo_width / photo_height
                
                if aspect > target_aspect:
                    # Картинка шире целевой
                    new_w = int(dish_img.height * target_aspect)
                    offset = (dish_img.width - new_w) // 2
                    dish_img = dish_img.crop((offset, 0, offset + new_w, dish_img.height))
                else:
                    # Картинка выше целевой
                    new_h = int(dish_img.width / target_aspect)
                    offset = (dish_img.height - new_h) // 2
                    dish_img = dish_img.crop((0, offset, dish_img.width, offset + new_h))
                
                dish_img = dish_img.resize((photo_width, photo_height), Image.Resampling.LANCZOS)
                
                img.paste(dish_img, (margin, current_y))
                # Рамка фото
                draw.rectangle([margin, current_y, margin + photo_width, current_y + photo_height], outline=ACCENT_COLOR, width=3)
            except Exception as e:
                logger.error(f"Image paste error: {e}")
                # Плейсхолдер
                draw.rectangle([margin, current_y, margin + photo_width, current_y + photo_height], fill="#E0E0E0", outline=ACCENT_COLOR)
                draw.text((margin + 130, current_y + 280), "Нет фото", font=self.fonts['section'], fill=ACCENT_COLOR)
        else:
            # Плейсхолдер если нет фото
            draw.rectangle([margin, current_y, margin + photo_width, current_y + photo_height], fill="#E0E0E0", outline=ACCENT_COLOR)
            draw.text((margin + 130, current_y + 280), "Нет фото", font=self.fonts['section'], fill=ACCENT_COLOR)

        # Правая колонка - Ингредиенты
        ing_x = margin + photo_width + 60
        draw.text((ing_x, current_y), "ИНГРЕДИЕНТЫ:", font=self.fonts['section'], fill=ACCENT_COLOR)
        
        ing_y = current_y + 70
        # Берем первые 10-12 ингредиентов, чтобы влезло
        for ing in ingredients[:11]:
            line = f"• {ing}"
            wrapped_ing = textwrap.wrap(line, width=28)
            for w_line in wrapped_ing:
                draw.text((ing_x, ing_y), w_line, font=self.fonts['main'], fill=TEXT_COLOR)
                ing_y += 45
            ing_y += 10 # Отступ между пунктами

        # Сдвигаем курсор ниже самого высокого элемента
        current_y += max(photo_height, (ing_y - current_y)) + 50

        # --- 3. МЕТА ДАННЫЕ ---
        meta_y = current_y
        
        # Иконки (текстовые, так как эмодзи в PIL ч/б и зависят от шрифта)
        # Лучше использовать текстовые метки для надежности стиля
        meta_items = [
            f"ВРЕМЯ: {time} мин", 
            f"ПОРЦИИ: {portions}", 
            f"УРОВЕНЬ: {difficulty}"
        ]
        
        # Распределяем по ширине (3 колонки)
        col_width = (CARD_WIDTH - 2 * margin) // 3
        
        for i, item in enumerate(meta_items):
            x_pos = margin + (i * col_width)
            # Центрируем текст внутри своей колонки
            bbox = draw.textbbox((0, 0), item, font=self.fonts['meta'])
            text_w = bbox[2] - bbox[0]
            # Небольшая коррекция для центрирования
            draw.text((x_pos + (col_width - text_w)//2, meta_y), item, font=self.fonts['meta'], fill=ACCENT_COLOR)

        current_y += 80

        # --- 4. СОВЕТ ШЕФА ---
        if chef_tip:
            tip_margin = margin
            tip_y_start = current_y + 30
            
            # Рассчитываем высоту блока
            tip_text = textwrap.wrap(f"«{chef_tip}»", width=55)
            box_h = len(tip_text) * 50 + 130
            
            # Проверяем, не вылезаем ли за пределы (footer занимает ~60px снизу)
            if tip_y_start + box_h > CARD_HEIGHT - 80:
                # Если не влезает, сокращаем текст
                tip_text = tip_text[:3] 
                tip_text.append("...")
                box_h = len(tip_text) * 50 + 130

            # Двойная рамка
            draw.rectangle([tip_margin, tip_y_start, CARD_WIDTH - tip_margin, tip_y_start + box_h], outline=ACCENT_COLOR, width=1)
            draw.rectangle([tip_margin+8, tip_y_start+8, CARD_WIDTH - tip_margin - 8, tip_y_start + box_h - 8], outline=ACCENT_COLOR, width=3)
            
            # Заголовок блока
            header = "СОВЕТ ШЕФА"
            bbox = draw.textbbox((0, 0), header, font=self.fonts['section'])
            header_w = bbox[2] - bbox[0]
            # Рисуем подложку под заголовок, чтобы перекрыть рамку
            draw.rectangle([((CARD_WIDTH - header_w)//2 - 20, tip_y_start - 25), ((CARD_WIDTH + header_w)//2 + 20, tip_y_start + 25)], fill=BG_COLOR)
            draw.text(((CARD_WIDTH - header_w)//2, tip_y_start - 25), header, font=self.fonts['section'], fill=ACCENT_COLOR)
            
            ty = tip_y_start + 60
            for t_line in tip_text:
                bbox = draw.textbbox((0, 0), t_line, font=self.fonts['italic'])
                draw.text(((CARD_WIDTH - (bbox[2]-bbox[0]))//2, ty), t_line, font=self.fonts['italic'], fill=TEXT_COLOR)
                ty += 50

        # --- 5. ФУТЕР ---
        footer_text = "Сгенерировано ботом @chto_poest_bot"
        bbox = draw.textbbox((0, 0), footer_text, font=self.fonts['meta'])
        footer_w = bbox[2] - bbox[0]
        draw.text(((CARD_WIDTH - footer_w)//2, CARD_HEIGHT - 60), footer_text, font=self.fonts['meta'], fill="#AAAAAA")

        buffer = BytesIO()
        img.save(buffer, format='PNG', quality=95)
        return buffer.getvalue()

# Создаем экземпляр, чтобы его можно было импортировать
recipe_card_generator = RecipeCardGenerator()
