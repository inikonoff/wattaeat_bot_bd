import random
import logging

logger = logging.getLogger(__name__)

class ImagePromptGenerator:
    """Генератор промптов для создания изображений блюд"""
    
    # Стили по категориям блюд
    CATEGORY_STYLES = {
        "soup": [
            "steam rising from ceramic bowl, rustic wooden table, natural light, 50mm lens, depth of field, cozy atmosphere",
            "hot soup in elegant bowl, steam, professional lighting, 35mm lens, restaurant quality, appetizing",
            "traditional soup presentation, homemade style, warm tones, natural daylight, 50mm lens"
        ],
        "main": [
            "fine dining plating, professional food photography, studio lighting, 35mm lens, sharp details, gourmet",
            "home cooked meal, rustic wooden table, natural window light, 50mm lens, warm colors, inviting",
            "restaurant style dish, dramatic side lighting, 85mm lens, shallow depth of field, elegant"
        ],
        "salad": [
            "top view flat lay, fresh colorful ingredients, bright natural light, 35mm lens, vibrant colors",
            "fresh salad close-up, natural daylight, 50mm lens, crisp details, healthy and appetizing",
            "garden fresh salad, rustic bowl, natural light, 85mm lens, shallow depth of field"
        ],
        "breakfast": [
            "morning light, cozy breakfast setting, natural window light, 50mm lens, warm tones, inviting",
            "breakfast flat lay, top view, natural daylight, 35mm lens, fresh and appetizing",
            "rustic breakfast table, homemade style, golden hour light, 85mm lens, comfortable atmosphere"
        ],
        "dessert": [
            "macro shot, elegant plating, soft natural light, 85mm lens, shallow depth of field, luxurious",
            "dessert close-up, professional photography, studio lighting, 100mm macro, beautiful details",
            "artistic dessert presentation, dramatic lighting, 85mm lens, bokeh background, Instagram worthy"
        ],
        "drink": [
            "glass with condensation drops, backlight, 85mm macro lens, bokeh background, refreshing",
            "beverage photography, ice cubes, natural light, 50mm lens, crystal clear, appetizing",
            "drink in elegant glass, professional lighting, 35mm lens, commercial photography style"
        ],
        "snack": [
            "casual food photography, natural light, 50mm lens, relaxed atmosphere, inviting",
            "snack close-up, rustic presentation, natural daylight, 85mm lens, appetizing details",
            "top view flat lay, variety of snacks, bright light, 35mm lens, colorful and fun"
        ]
    }
    
    # Универсальные стили (для блюд без категории или "mix")
    UNIVERSAL_STYLES = [
        "professional food photography, restaurant quality, studio lighting, 35mm lens, commercial style",
        "homemade food, cozy atmosphere, natural window light, 50mm lens, warm inviting tones",
        "rustic style, wooden table, linen napkin, natural daylight, 85mm lens, cottage core aesthetic",
        "fine dining presentation, elegant plating, soft professional lighting, 50mm lens, gourmet",
        "minimalist food photography, clean background, soft shadows, 35mm lens, modern aesthetic"
    ]
    
    # Дополнительные детали (добавляются рандомно)
    DETAIL_ENHANCERS = [
        "sharp focus, high resolution, professional quality",
        "appetizing, delicious looking, mouth-watering",
        "beautifully plated, artistic composition",
        "Instagram worthy, award winning photography",
        "warm color palette, inviting atmosphere"
    ]
    
    @staticmethod
    def detect_category(dish_name: str) -> str:
        """Определяет категорию блюда по названию"""
        dish_lower = dish_name.lower()
        
        # Проверяем ключевые слова
        if any(word in dish_lower for word in ['суп', 'борщ', 'щи', 'бульон', 'soup']):
            return 'soup'
        elif any(word in dish_lower for word in ['салат', 'салатик', 'salad']):
            return 'salad'
        elif any(word in dish_lower for word in ['десерт', 'торт', 'пирог', 'мороженое', 'dessert', 'cake']):
            return 'dessert'
        elif any(word in dish_lower for word in ['напиток', 'сок', 'коктейль', 'смузи', 'drink', 'juice']):
            return 'drink'
        elif any(word in dish_lower for word in ['завтрак', 'омлет', 'каша', 'блин', 'breakfast']):
            return 'breakfast'
        elif any(word in dish_lower for word in ['закуска', 'закуск', 'snack']):
            return 'snack'
        else:
            return 'main'
    
    @classmethod
    def generate_prompt(cls, dish_name: str, add_details: bool = True) -> str:
        """
        Генерирует промпт для создания изображения блюда
        
        Args:
            dish_name: Название блюда
            add_details: Добавлять ли дополнительные детали
            
        Returns:
            Строка с промптом для генерации изображения
        """
        # Определяем категорию
        category = cls.detect_category(dish_name)
        
        # Выбираем рандомный стиль для категории
        if category in cls.CATEGORY_STYLES:
            base_style = random.choice(cls.CATEGORY_STYLES[category])
        else:
            base_style = random.choice(cls.UNIVERSAL_STYLES)
        
        # Формируем промпт
        prompt_parts = [
            f"Professional food photography of {dish_name}",
            base_style
        ]
        
        # Добавляем дополнительные детали (50% шанс)
        if add_details and random.random() > 0.5:
            detail = random.choice(cls.DETAIL_ENHANCERS)
            prompt_parts.append(detail)
        
        # Собираем финальный промпт
        final_prompt = ", ".join(prompt_parts)
        
        logger.info(f"Generated prompt for '{dish_name}': {final_prompt}")
        
        return final_prompt
    
    @classmethod
    def generate_multiple_variants(cls, dish_name: str, count: int = 3) -> list[str]:
        """
        Генерирует несколько вариантов промптов
        
        Args:
            dish_name: Название блюда
            count: Количество вариантов
            
        Returns:
            Список промптов
        """
        variants = []
        category = cls.detect_category(dish_name)
        
        # Если есть стили для категории, берём из них
        if category in cls.CATEGORY_STYLES:
            styles = cls.CATEGORY_STYLES[category]
            # Берём столько стилей, сколько есть (но не больше count)
            selected_styles = random.sample(styles, min(count, len(styles)))
            
            for style in selected_styles:
                prompt = f"Professional food photography of {dish_name}, {style}"
                variants.append(prompt)
        
        # Если нужно больше вариантов, добавляем из универсальных
        while len(variants) < count:
            style = random.choice(cls.UNIVERSAL_STYLES)
            prompt = f"Professional food photography of {dish_name}, {style}"
            variants.append(prompt)
        
        return variants[:count]

# Глобальный экземпляр
image_prompt_generator = ImagePromptGenerator()
