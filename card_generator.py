from PIL import Image, ImageDraw, ImageFont, ImageFilter
import textwrap
import os
from typing import Optional
import aiohttp
import io

class RecipeCardGenerator:
    """Генератор красивых карточек рецептов"""
    
    # Размеры
    CARD_WIDTH = 1080
    CARD_HEIGHT = 1920
    PADDING = 60
    
    # Цвета (светлая тема)
    COLOR_BG = (255, 255, 255)
    COLOR_PRIMARY = (255, 107, 107)  # Коралловый
    COLOR_TEXT = (45, 52, 54)
    COLOR_SECONDARY = (149, 165, 166)
    
    def __init__(self):
        # Загружаем шрифты (используем системные или скачиваем)
        self.font_title = self._load_font("fonts/Roboto-Bold.ttf", 64)
        self.font_heading = self._load_font("fonts/Roboto-Medium.ttf", 44)
        self.font_body = self._load_font("fonts/Roboto-Regular.ttf", 36)
        self.font_small = self._load_font("fonts/Roboto-Regular.ttf", 32)
    
    def _load_font(self, path: str, size: int):
        """Загрузка шрифта с fallback"""
        try:
            return ImageFont.truetype(path, size)
        except:
            # Fallback на дефолтный
            return ImageFont.load_default()
    
    async def generate_card(
        self,
        dish_name: str,
        ingredients: list[str],
        cooking_time: str,
        servings: str,
        difficulty: str,
        chef_tip: str,
        image_url: Optional[str] = None
    ) -> bytes:
        """
        Генерирует карточку рецепта
        
        Returns:
            bytes: PNG изображение
        """
        # Создаём холст
        img = Image.new('RGB', (self.CARD_WIDTH, self.CARD_HEIGHT), self.COLOR_BG)
        draw = ImageDraw.Draw(img)
        
        y_offset = self.PADDING
        
        # 1. Хедер с логотипом
        y_offset = self._draw_header(draw, y_offset)
        
        # 2. Изображение блюда (если есть)
        if image_url:
            y_offset = await self._draw_dish_image(img, image_url, y_offset)
        else:
            y_offset = self._draw_placeholder(draw, y_offset)
        
        y_offset += 40
        
        # 3. Название блюда
        y_offset = self._draw_title(draw, dish_name, y_offset)
        
        # 4. Разделитель
        y_offset = self._draw_separator(draw, y_offset)
        
        # 5. Ингредиенты
        y_offset = self._draw_ingredients(draw, ingredients, y_offset)
        
        # 6. Мета-информация
        y_offset = self._draw_meta(draw, cooking_time, servings, difficulty, y_offset)
        
        # 7. Совет шеф-повара
        if chef_tip:
            y_offset = self._draw_chef_tip(draw, chef_tip, y_offset)
        
        # 8. Футер с брендингом
        self._draw_footer(draw)
        
        # Сохраняем в байты
        output = io.BytesIO()
        img.save(output, format='PNG', optimize=True)
        return output.getvalue()
    
    def _draw_header(self, draw, y: int) -> int:
        """Рисуем хедер"""
        text = "🍽️  ЧЁПОЕСТЬ"
        draw.text(
            (self.PADDING, y),
            text,
            font=self.font_heading,
            fill=self.COLOR_PRIMARY
        )
        return y + 80
    
    async def _draw_dish_image(self, img: Image, url: str, y: int) -> int:
        """Загружаем и вставляем фото блюда"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        image_data = await resp.read()
                        dish_img = Image.open(io.BytesIO(image_data))
                        
                        # Ресайз с сохранением пропорций
                        img_width = self.CARD_WIDTH - 2 * self.PADDING
                        img_height = 600
                        
                        dish_img.thumbnail((img_width, img_height), Image.Resampling.LANCZOS)
                        
                        # Центрируем
                        x_offset = (self.CARD_WIDTH - dish_img.width) // 2
                        
                        # Скругленные углы
                        dish_img = self._round_corners(dish_img, 20)
                        
                        img.paste(dish_img, (x_offset, y), dish_img)
                        
                        return y + dish_img.height + 40
        except:
            pass
        
        return self._draw_placeholder(draw, y)
    
    def _draw_placeholder(self, draw, y: int) -> int:
        """Placeholder если нет изображения"""
        img_width = self.CARD_WIDTH - 2 * self.PADDING
        img_height = 400
        
        # Рисуем рамку
        draw.rectangle(
            [(self.PADDING, y), (self.PADDING + img_width, y + img_height)],
            outline=self.COLOR_SECONDARY,
            width=3
        )
        
        # Иконка в центре
        text = "🍽️"
        bbox = draw.textbbox((0, 0), text, font=self.font_title)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        draw.text(
            ((self.CARD_WIDTH - text_width) // 2, y + (img_height - text_height) // 2),
            text,
            font=self.font_title,
            fill=self.COLOR_SECONDARY
        )
        
        return y + img_height + 40
    
    def _draw_title(self, draw, title: str, y: int) -> int:
        """Название блюда"""
        # Переносим длинные названия
        wrapped = textwrap.fill(title, width=25)
        
        draw.text(
            (self.PADDING, y),
            wrapped,
            font=self.font_title,
            fill=self.COLOR_TEXT
        )
        
        bbox = draw.multiline_textbbox((self.PADDING, y), wrapped, font=self.font_title)
        return bbox[3] + 30
    
    def _draw_separator(self, draw, y: int) -> int:
        """Разделитель"""
        line_width = 300
        draw.line(
            [(self.PADDING, y), (self.PADDING + line_width, y)],
            fill=self.COLOR_PRIMARY,
            width=4
        )
        return y + 40
    
    def _draw_ingredients(self, draw, ingredients: list[str], y: int) -> int:
        """Список ингредиентов"""
        # Заголовок
        draw.text(
            (self.PADDING, y),
            "📦 Ингредиенты:",
            font=self.font_heading,
            fill=self.COLOR_TEXT
        )
        y += 60
        
        # Список (максимум 8 для карточки)
        for ingredient in ingredients[:8]:
            text = f"• {ingredient}"
            draw.text(
                (self.PADDING + 20, y),
                text,
                font=self.font_body,
                fill=self.COLOR_TEXT
            )
            y += 50
        
        if len(ingredients) > 8:
            draw.text(
                (self.PADDING + 20, y),
                f"... и ещё {len(ingredients) - 8}",
                font=self.font_small,
                fill=self.COLOR_SECONDARY
            )
            y += 50
        
        return y + 20
    
    def _draw_meta(self, draw, time: str, servings: str, difficulty: str, y: int) -> int:
        """Мета-информация"""
        meta_text = f"⏱ {time}  👥 {servings}  🪦 {difficulty}"
        
        draw.text(
            (self.PADDING, y),
            meta_text,
            font=self.font_body,
            fill=self.COLOR_SECONDARY
        )
        
        return y + 80
    
    def _draw_chef_tip(self, draw, tip: str, y: int) -> int:
        """Совет шеф-повара"""
        draw.text(
            (self.PADDING, y),
            "💡 Совет шеф-повара:",
            font=self.font_heading,
            fill=self.COLOR_PRIMARY
        )
        y += 60
        
        # Оборачиваем текст
        wrapped = textwrap.fill(tip, width=35)
        
        draw.text(
            (self.PADDING, y),
            wrapped,
            font=self.font_body,
            fill=self.COLOR_TEXT
        )
        
        bbox = draw.multiline_textbbox((self.PADDING, y), wrapped, font=self.font_body)
        return bbox[3] + 60
    
    def _draw_footer(self, draw):
        """Футер с брендингом"""
        y = self.CARD_HEIGHT - 150
        
        # Разделитель
        draw.line(
            [(self.PADDING, y), (self.CARD_WIDTH - self.PADDING, y)],
            fill=self.COLOR_SECONDARY,
            width=2
        )
        y += 40
        
        # Текст
        text1 = "Создано ботом @chto_poest_bot"
        text2 = "чёпоесть.рф"
        
        draw.text(
            (self.PADDING, y),
            text1,
            font=self.font_small,
            fill=self.COLOR_SECONDARY
        )
        
        draw.text(
            (self.PADDING, y + 50),
            text2,
            font=self.font_small,
            fill=self.COLOR_PRIMARY
        )
    
    def _round_corners(self, img: Image, radius: int) -> Image:
        """Скругление углов изображения"""
        circle = Image.new('L', (radius * 2, radius * 2), 0)
        draw = ImageDraw.Draw(circle)
        draw.ellipse((0, 0, radius * 2, radius * 2), fill=255)
        
        alpha = Image.new('L', img.size, 255)
        w, h = img.size
        
        alpha.paste(circle.crop((0, 0, radius, radius)), (0, 0))
        alpha.paste(circle.crop((0, radius, radius, radius * 2)), (0, h - radius))
        alpha.paste(circle.crop((radius, 0, radius * 2, radius)), (w - radius, 0))
        alpha.paste(circle.crop((radius, radius, radius * 2, radius * 2)), (w - radius, h - radius))
        
        img.putalpha(alpha)
        return img

# Синглтон
card_generator = RecipeCardGenerator()
