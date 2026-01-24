import os
import textwrap
import logging
from io import BytesIO
from typing import List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

from config import (
    CARD_WIDTH, CARD_HEIGHT, CARD_BG_COLOR, CARD_ACCENT_COLOR,
    CARD_TEXT_COLOR, CARD_SECONDARY_COLOR,
    FONT_BOLD, FONT_MEDIUM, FONT_REGULAR,
    TEMP_DIR
)

logger = logging.getLogger(__name__)

class RecipeCardGenerator:
    """Генератор красивых PNG карточек рецептов"""
    
    def __init__(self):
        # Загружаем шрифты (если нет - используем дефолтные)
        try:
            self.font_bold_large = ImageFont.truetype(FONT_BOLD, 64)
            self.font_bold_medium = ImageFont.truetype(FONT_BOLD, 44)
            self.font_medium = ImageFont.truetype(FONT_MEDIUM, 36)
            self.font_regular = ImageFont.truetype(FONT_REGULAR, 36)
            self.font_small = ImageFont.truetype(FONT_REGULAR, 32)
            self.fonts_loaded = True
        except:
            logger.warning("Шрифты не найдены, использую системные")
            self.font_bold_large = ImageFont.load_default()
            self.font_bold_medium = ImageFont.load_default()
            self.font_medium = ImageFont.load_default()
            self.font_regular = ImageFont.load_default()
            self.font_small = ImageFont.load_default()
            self.fonts_loaded = False
    
    def _draw_header(self, draw: ImageDraw.ImageDraw, y_start: int) -> int:
        """Рисует хедер карточки"""
        header_height = 80
        
        # Фон хедера
        draw.rectangle(
            [(0, 0), (CARD_WIDTH, header_height)],
            fill=CARD_ACCENT_COLOR
        )
        
        # Текст "🍽️ ЧЁПОЕСТЬ"
        text = "🍽️ ЧЁПОЕСТЬ"
        text_bbox = draw.textbbox((0, 0), text, font=self.font_bold_medium)
        text_width = text_bbox[2] - text_bbox[0]
        text_x = (CARD_WIDTH - text_width) // 2
        text_y = (header_height - 44) // 2
        
        draw.text(
            (text_x, text_y),
            text,
            font=self.font_bold_medium,
            fill="#FFFFFF"
        )
        
        return header_height
    
    def _draw_dish_image(
        self, 
        image: Image.Image, 
        draw: ImageDraw.ImageDraw, 
        y_start: int,
        dish_image_data: Optional[bytes] = None
    ) -> int:
        """Рисует изображение блюда или placeholder"""
        image_height = 600
        image_y = y_start + 40
        
        # Если есть изображение - загружаем
        if dish_image_data:
            try:
                dish_img = Image.open(BytesIO(dish_image_data))
                
                # Ресайз с сохранением пропорций
                target_width = CARD_WIDTH - 80  # Отступы по 40px с каждой стороны
                target_height = image_height - 40
                
                # Вычисляем новые размеры
                original_width, original_height = dish_img.size
                ratio = min(target_width / original_width, target_height / original_height)
                new_width = int(original_width * ratio)
                new_height = int(original_height * ratio)
                
                # Ресайзим
                dish_img = dish_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # Координаты для центрирования
                img_x = (CARD_WIDTH - new_width) // 2
                img_y = image_y + (target_height - new_height) // 2
                
                # Создаём маску для скругления углов
                mask = Image.new('L', (new_width, new_height), 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.rounded_rectangle(
                    [(0, 0), (new_width, new_height)],
                    radius=20,
                    fill=255
                )
                
                # Применяем маску и вставляем
                dish_img.putalpha(mask)
                image.paste(dish_img, (img_x, img_y), dish_img)
                
                # Рамка вокруг изображения
                draw.rounded_rectangle(
                    [(img_x - 5, img_y - 5), 
                     (img_x + new_width + 5, img_y + new_height + 5)],
                    radius=25,
                    outline=CARD_ACCENT_COLOR,
                    width=3
                )
                
            except Exception as e:
                logger.error(f"Ошибка загрузки изображения блюда: {e}")
                # Если ошибка - рисуем placeholder
                return self._draw_placeholder(image, draw, y_start)
        else:
            # Нет изображения - рисуем placeholder
            return self._draw_placeholder(image, draw, y_start)
        
        return image_y + image_height
    
    def _draw_placeholder(
        self, 
        image: Image.Image, 
        draw: ImageDraw.ImageDraw, 
        y_start: int
    ) -> int:
        """Рисует placeholder если нет изображения блюда"""
        placeholder_height = 400
        placeholder_y = y_start + 40
        
        # Фон placeholder
        draw.rounded_rectangle(
            [(40, placeholder_y), 
             (CARD_WIDTH - 40, placeholder_y + placeholder_height)],
            radius=20,
            fill="#F5F5F5",
            outline=CARD_ACCENT_COLOR,
            width=2
        )
        
        # Иконка блюда
        icon = "🍽️"
        icon_bbox = draw.textbbox((0, 0), icon, font=self.font_bold_large)
        icon_width = icon_bbox[2] - icon_bbox[0]
        icon_x = (CARD_WIDTH - icon_width) // 2
        icon_y = placeholder_y + (placeholder_height - 64) // 2
        
        draw.text(
            (icon_x, icon_y),
            icon,
            font=self.font_bold_large,
            fill=CARD_SECONDARY_COLOR
        )
        
        # Текст под иконкой
        text = "Изображение блюда"
        text_bbox = draw.textbbox((0, 0), text, font=self.font_small)
        text_width = text_bbox[2] - text_bbox[0]
        text_x = (CARD_WIDTH - text_width) // 2
        text_y = icon_y + 80
        
        draw.text(
            (text_x, text_y),
            text,
            font=self.font_small,
            fill=CARD_SECONDARY_COLOR
        )
        
        return placeholder_y + placeholder_height
    
    def _draw_title(
        self, 
        draw: ImageDraw.ImageDraw, 
        y_start: int, 
        title: str
    ) -> int:
        """Рисует название блюда"""
        title_y = y_start + 40
        
        # Ограничиваем длину названия
        if len(title) > 40:
            title = title[:37] + "..."
        
        # Центрируем текст
        text_bbox = draw.textbbox((0, 0), title, font=self.font_bold_large)
        text_width = text_bbox[2] - text_bbox[0]
        text_x = (CARD_WIDTH - text_width) // 2
        
        draw.text(
            (text_x, title_y),
            title,
            font=self.font_bold_large,
            fill=CARD_TEXT_COLOR
        )
        
        return title_y + 80
    
    def _draw_divider(
        self, 
        draw: ImageDraw.ImageDraw, 
        y_start: int
    ) -> int:
        """Рисует разделительную линию"""
        divider_y = y_start + 20
        divider_width = 300
        divider_x = (CARD_WIDTH - divider_width) // 2
        
        draw.line(
            [(divider_x, divider_y), (divider_x + divider_width, divider_y)],
            fill=CARD_ACCENT_COLOR,
            width=3
        )
        
        return divider_y + 40
    
    def _draw_ingredients(
        self, 
        draw: ImageDraw.ImageDraw, 
        y_start: int, 
        ingredients: List[str]
    ) -> int:
        """Рисует список ингредиентов"""
        section_y = y_start
        
        # Заголовок
        draw.text(
            (40, section_y),
            "📦 Ингредиенты:",
            font=self.font_bold_medium,
            fill=CARD_ACCENT_COLOR
        )
        
        section_y += 50
        
        # Список ингредиентов (максимум 8)
        for i, ingredient in enumerate(ingredients[:8]):
            # Обрезаем длинные ингредиенты
            if len(ingredient) > 40:
                ingredient = ingredient[:37] + "..."
            
            draw.text(
                (60, section_y),
                f"• {ingredient}",
                font=self.font_regular,
                fill=CARD_TEXT_COLOR
            )
            section_y += 45
        
        return section_y + 20
    
    def _draw_meta(
        self, 
        draw: ImageDraw.ImageDraw, 
        y_start: int,
        time: str,
        portions: str,
        difficulty: str
    ) -> int:
        """Рисует мета-информацию (время, порции, сложность)"""
        meta_y = y_start
        
        # Фон для мета-блока
        draw.rounded_rectangle(
            [(40, meta_y), (CARD_WIDTH - 40, meta_y + 100)],
            radius=15,
            fill="#F8F9FA",
            outline=CARD_SECONDARY_COLOR,
            width=1
        )
        
        # Разделяем на 3 колонки
        col_width = (CARD_WIDTH - 80) // 3
        
        # Колонка 1: Время
        time_x = 40 + (col_width - 80) // 2
        draw.text(
            (time_x, meta_y + 20),
            "⏱",
            font=self.font_bold_medium,
            fill=CARD_ACCENT_COLOR
        )
        
        time_text = f"{time} мин"
        time_bbox = draw.textbbox((0, 0), time_text, font=self.font_small)
        time_width = time_bbox[2] - time_bbox[0]
        time_text_x = 40 + (col_width - time_width) // 2
        
        draw.text(
            (time_text_x, meta_y + 65),
            time_text,
            font=self.font_small,
            fill=CARD_TEXT_COLOR
        )
        
        # Колонка 2: Порции
        portions_x = 40 + col_width + (col_width - 80) // 2
        draw.text(
            (portions_x, meta_y + 20),
            "👥",
            font=self.font_bold_medium,
            fill=CARD_ACCENT_COLOR
        )
        
        portions_text = f"{portions} порц"
        portions_bbox = draw.textbbox((0, 0), portions_text, font=self.font_small)
        portions_width = portions_bbox[2] - portions_bbox[0]
        portions_text_x = 40 + col_width + (col_width - portions_width) // 2
        
        draw.text(
            (portions_text_x, meta_y + 65),
            portions_text,
            font=self.font_small,
            fill=CARD_TEXT_COLOR
        )
        
        # Колонка 3: Сложность
        difficulty_x = 40 + 2 * col_width + (col_width - 80) // 2
        draw.text(
            (difficulty_x, meta_y + 20),
            "🪦",
            font=self.font_bold_medium,
            fill=CARD_ACCENT_COLOR
        )
        
        difficulty_text = difficulty[:10]
        difficulty_bbox = draw.textbbox((0, 0), difficulty_text, font=self.font_small)
        difficulty_width = difficulty_bbox[2] - difficulty_bbox[0]
        difficulty_text_x = 40 + 2 * col_width + (col_width - difficulty_width) // 2
        
        draw.text(
            (difficulty_text_x, meta_y + 65),
            difficulty_text,
            font=self.font_small,
            fill=CARD_TEXT_COLOR
        )
        
        return meta_y + 120
    
    def _draw_chef_tip(
        self, 
        draw: ImageDraw.ImageDraw, 
        y_start: int, 
        tip: str
    ) -> int:
        """Рисует совет шеф-повара"""
        tip_y = y_start
        
        # Заголовок
        draw.text(
            (40, tip_y),
            "💡 Совет шеф-повара:",
            font=self.font_bold_medium,
            fill=CARD_ACCENT_COLOR
        )
        
        tip_y += 50
        
        # Текст совета с переносом
        max_chars_per_line = 35
        wrapped_tip = textwrap.fill(tip, width=max_chars_per_line)
        
        lines = wrapped_tip.split('\n')
        for line in lines:
            draw.text(
                (60, tip_y),
                line,
                font=self.font_regular,
                fill=CARD_TEXT_COLOR
            )
            tip_y += 40
        
        return tip_y + 20
    
    def _draw_footer(
        self, 
        draw: ImageDraw.ImageDraw, 
        y_start: int
    ) -> int:
        """Рисует футер карточки"""
        footer_y = y_start
        
        # Разделитель
        draw.line(
            [(40, footer_y), (CARD_WIDTH - 40, footer_y)],
            fill=CARD_SECONDARY_COLOR,
            width=1
        )
        
        footer_y += 30
        
        # Текст футера
        line1 = "Создано ботом @chto_poest_bot"
        line2 = "чёпоесть.рф"
        
        # Линия 1
        line1_bbox = draw.textbbox((0, 0), line1, font=self.font_small)
        line1_width = line1_bbox[2] - line1_bbox[0]
        line1_x = (CARD_WIDTH - line1_width) // 2
        
        draw.text(
            (line1_x, footer_y),
            line1,
            font=self.font_small,
            fill=CARD_SECONDARY_COLOR
        )
        
        # Линия 2
        line2_bbox = draw.textbbox((0, 0), line2, font=self.font_bold_medium)
        line2_width = line2_bbox[2] - line2_bbox[0]
        line2_x = (CARD_WIDTH - line2_width) // 2
        
        draw.text(
            (line2_x, footer_y + 45),
            line2,
            font=self.font_bold_medium,
            fill=CARD_ACCENT_COLOR
        )
        
        return footer_y + 100
    
    def generate_card(
        self,
        title: str,
        ingredients: List[str],
        time: str,
        portions: str,
        difficulty: str,
        chef_tip: str,
        dish_image_data: Optional[bytes] = None
    ) -> bytes:
        """
        Генерирует PNG карточку рецепта
        
        Args:
            title: Название блюда
            ingredients: Список ингредиентов
            time: Время приготовления (строка)
            portions: Количество порций (строка)
            difficulty: Уровень сложности (строка)
            chef_tip: Совет шеф-повара
            dish_image_data: Данные изображения блюда (опционально)
            
        Returns:
            bytes: PNG изображение карточки
        """
        # Создаём новое изображение
        image = Image.new('RGB', (CARD_WIDTH, CARD_HEIGHT), CARD_BG_COLOR)
        draw = ImageDraw.Draw(image)
        
        y_position = 0
        
        # 1. Хедер
        y_position = self._draw_header(draw, y_position)
        
        # 2. Изображение блюда
        y_position = self._draw_dish_image(image, draw, y_position, dish_image_data)
        
        # 3. Название блюда
        y_position = self._draw_title(draw, y_position, title)
        
        # 4. Разделитель
        y_position = self._draw_divider(draw, y_position)
        
        # 5. Ингредиенты
        y_position = self._draw_ingredients(draw, y_position, ingredients)
        
        # 6. Мета-информация
        y_position = self._draw_meta(draw, y_position, time, portions, difficulty)
        
        # 7. Совет шеф-повара
        y_position = self._draw_chef_tip(draw, y_position, chef_tip)
        
        # 8. Футер
        self._draw_footer(draw, y_position)
        
        # Сохраняем в буфер
        buffer = BytesIO()
        image.save(buffer, format='PNG', optimize=True)
        
        logger.info(f"Карточка сгенерирована: {len(buffer.getvalue())} bytes")
        return buffer.getvalue()

# Глобальный экземпляр
recipe_card_generator = RecipeCardGenerator()
