import time
import threading
import psutil
import requests
import json
import os
import functools
from pystray import Icon, Menu, MenuItem
from PIL import Image, ImageDraw, ImageFont

# --- ГЛОБАЛЬНЫЕ КОНСТАНТЫ И СОСТОЯНИЕ (без изменений) ---
CITY_FILE = "pinned_cities.json"

VIEWED_LOCATION = {
    'name': 'Загрузка...',
    'lat': None,
    'lon': None,
    'is_current': True
}

WEATHER_CODES = {
    0: '☀️', 1: '🌤️', 2: '🌥️', 3: '☁️', 45: '🌫️', 48: '🌫️', 51: '🌧️',
    61: '🌧️', 63: '🌧️', 65: '🌧️', 71: '❄️', 73: '❄️', 75: '❄️', 95: '🌩️', 99: '⛈️',
}


# --- 1. МЕНЕДЖЕР ГОРОДОВ (без изменений) ---
class CityManager:
    """Управление списком сохраненных городов."""

    def __init__(self):
        self.cities = self._load_cities()

    def _load_cities(self):
        if os.path.exists(CITY_FILE):
            try:
                with open(CITY_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return []
        return []

    def _save_cities(self):
        serializable_cities = [{k: c[k] for k in ['name', 'lat', 'lon']} for c in self.cities]
        with open(CITY_FILE, 'w', encoding='utf-8') as f:
            json.dump(serializable_cities, f, ensure_ascii=False, indent=4)

    def add_city(self, city_data):
        key = (city_data['lat'], city_data['lon'])
        if any((c['lat'] == key[0] and c['lon'] == key[1]) for c in self.cities):
            return
        saved_data = {k: city_data[k] for k in ['name', 'lat', 'lon']}
        self.cities.append(saved_data)
        self._save_cities()

    def remove_city(self, city_data):
        self.cities = [
            c for c in self.cities
            if not (c['lat'] == city_data['lat'] and c['lon'] == city_data['lon'])
        ]
        self._save_cities()


city_manager = CityManager()


# --- 2. ФУНКЦИИ ПОЛУЧЕНИЯ ДАННЫХ (без изменений) ---
def get_geolocation_from_ip():
    try:
        response = requests.get('http://ip-api.com/json', timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data['status'] == 'success':
                return {
                    'name': data['city'], 'lat': data['lat'], 'lon': data['lon'], 'is_current': True
                }
        return None
    except Exception:
        return None


def get_battery():
    try:
        battery = psutil.sensors_battery()
        if battery:
            percent = int(battery.percent)
            plugged = "🔌" if battery.power_plugged else ""
            return f"{plugged}{percent}%"
        return "Батарея N/A"
    except Exception:
        return "Батарея Err"


def get_weather_for_city(lat, lon):
    """Получает погоду и возвращает словарь с данными."""
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&"
            f"current=temperature_2m,weather_code&"
            f"timezone=Europe/Moscow"
        )
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            current = data.get('current', {})
            temp = int(current.get('temperature_2m', 'N/A'))
            weather_code = current.get('weather_code')
            icon = WEATHER_CODES.get(weather_code, '❓')

            return {
                'icon': icon,
                'temp': f"{'+' if temp > 0 else ''}{temp}°C",
                'full_str': f"{icon} {temp}°C"
            }
        return {'icon': '⚠️', 'temp': 'Err', 'full_str': f"Погода Err: {response.status_code}"}
    except Exception:
        return {'icon': '📡', 'temp': 'Err', 'full_str': "Погода: Нет сети"}


# !!! ИСПРАВЛЕНА: Упрощаем выбор шрифтов для лучшей совместимости с эмодзи !!!
def create_weather_icon_image(weather_icon, temp_str):
    """Создает изображение, показывающее погодный значок и температуру."""
    width, height = 64, 64
    # Используем темно-серый фон
    image = Image.new('RGB', (width, height), color='#252525')
    draw = ImageDraw.Draw(image)

    # Пытаемся использовать Segoe UI Emoji для эмодзи, иначе Arial
    try:
        icon_font = ImageFont.truetype("seguiemj.ttf", 32)
    except IOError:
        try:
            icon_font = ImageFont.truetype("arial.ttf", 32)
        except IOError:
            icon_font = ImageFont.load_default()

    # Пытаемся использовать Arial для цифр, иначе дефолтный
    try:
        temp_font = ImageFont.truetype("arial.ttf", 18)
    except IOError:
        temp_font = ImageFont.load_default()

    # 1. Рисуем погодный значок
    draw.text((10, 2), weather_icon, fill="#FFFF00", font=icon_font)

    # 2. Рисуем температуру
    temp_width = draw.textlength(temp_str, font=temp_font)
    temp_x = (width - temp_width) / 2  # Центрирование

    temp_color = "#FFA07A" if "+" in temp_str else "#ADD8E6"

    draw.text((temp_x, 38), temp_str, fill=temp_color, font=temp_font)

    return image


# --- 3. ОБРАБОТЧИКИ (Actions) ---
def run_in_thread(target, *args, **kwargs):
    threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True).start()


# ... (set_viewed_city, pin_city - без изменений)
def set_viewed_city(icon, item, city_data):
    global VIEWED_LOCATION
    VIEWED_LOCATION = city_data.copy()
    run_in_thread(update_tray_icon_thread, icon, is_initial=False)


def pin_city(icon, item, city_data):
    if any((c['name'] == city_data['name']) for c in city_manager.cities):
        city_manager.remove_city(city_data)
    else:
        city_manager.add_city(city_data)
    run_in_thread(update_tray_icon_thread, icon, is_initial=False)


# --- 4. ГЕНЕРАЦИЯ МЕНЮ (без изменений) ---
def create_main_menu(icon, current_data):
    current_time = current_data['time']
    weather = current_data['weather_data']['full_str']
    battery = current_data['battery']

    info_items = [
        MenuItem(f"📍 Город: {VIEWED_LOCATION['name']}", None),
        MenuItem(f"⌚ Время: {current_time}", None),
        MenuItem(f"🌍 {weather}", None),
        MenuItem(f"🔋 Батарея: {battery}", None),
        Menu.SEPARATOR
    ]

    city_items = []
    city_items.append(MenuItem("--- Сохраненные города ---", None))

    for city in city_manager.cities:
        is_selected = city['name'] == VIEWED_LOCATION['name']
        select_action = functools.partial(set_viewed_city, city_data=city)
        pin_action = functools.partial(pin_city, city_data=city)

        city_items.append(
            MenuItem(
                f"{'✔️' if is_selected else ''} {city['name']}",
                Menu(
                    MenuItem(f"Показать погоду", select_action),
                    MenuItem(f"Удалить из списка", pin_action)
                )
            )
        )

    if current_data['ip_location'] and VIEWED_LOCATION.get('name') != current_data['ip_location']['name']:
        city_items.append(Menu.SEPARATOR)
        ip_action = functools.partial(set_viewed_city, city_data=current_data['ip_location'])
        city_items.append(
            MenuItem(f"➡️ Показать моё (IP) место", ip_action)
        )

    if VIEWED_LOCATION['name'] not in [c['name'] for c in city_manager.cities] and VIEWED_LOCATION['lat'] is not None:
        current_pin_action = functools.partial(pin_city, city_data=VIEWED_LOCATION)
        city_items.append(
            MenuItem(f"📌 Закрепить {VIEWED_LOCATION['name']}", current_pin_action)
        )

    exit_item = MenuItem('Выход', lambda icon: icon.stop())

    return Menu(*(info_items + city_items + [Menu.SEPARATOR, exit_item]))


# --- 5. ТРЕД И ЗАПУСК ---

def update_tray_icon_thread(icon, is_initial=False):
    """Поток, который обновляет данные и меню."""
    global VIEWED_LOCATION

    ip_location = get_geolocation_from_ip()

    if is_initial and ip_location:
        VIEWED_LOCATION.update(ip_location)

    if VIEWED_LOCATION['lat'] is None:
        icon.icon = create_weather_icon_image('📡', '?°C')
        threading.Timer(5, update_tray_icon_thread, args=(icon, is_initial)).start()
        return

    weather_data = get_weather_for_city(VIEWED_LOCATION['lat'], VIEWED_LOCATION['lon'])
    current_time = time.strftime("%H:%M:%S")
    battery = get_battery()

    # !!! КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: Обновление иконки !!!
    icon.icon = create_weather_icon_image(weather_data['icon'], weather_data['temp'])

    current_data = {
        'time': current_time,
        'weather_data': weather_data,
        'battery': battery,
        'ip_location': ip_location
    }

    icon.tooltip = f"[{VIEWED_LOCATION['name']}] | {current_time} | {weather_data['full_str']} | Батарея: {battery}"

    icon.menu = create_main_menu(icon, current_data)

    if is_initial or icon._running:
        threading.Timer(30, update_tray_icon_thread, args=(icon,)).start()


def setup_tray_icon():
    image = create_weather_icon_image('⏱️', '---')
    initial_menu = Menu(MenuItem('Идет загрузка данных...', None), Menu.SEPARATOR,
                        MenuItem('Выход', lambda icon: icon.stop()))

    tray_icon = Icon(
        name='custom_info_widget',
        icon=image,
        title='Системная Информация',
        menu=initial_menu
    )

    def on_single_click(icon, _):
        run_in_thread(update_tray_icon_thread, icon, is_initial=False)

    tray_icon.on_click = on_single_click

    run_in_thread(update_tray_icon_thread, tray_icon, is_initial=True)

    tray_icon.run()


if __name__ == '__main__':
    print("Запуск системного виджета. ЛКМ - обновить данные, ПКМ - меню городов.")
    setup_tray_icon()