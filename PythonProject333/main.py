import time
import threading
import psutil
import requests
import json
import os
import functools
from pystray import Icon, Menu, MenuItem
from PIL import Image, ImageDraw, ImageFont

# --- ГЛОБАЛЬНЫЕ КОНСТАНТЫ И СОСТОЯНИЕ ---
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


# --- 1. МЕНЕДЖЕР ГОРОДОВ (CityManager) ---
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


def get_weather_for_city(lat, lon):
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
            return f"{icon} {temp}°C"
        return f"Погода Err: {response.status_code}"
    except Exception:
        return "Погода: Нет сети"


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


def create_icon_image():
    width, height = 64, 64
    image = Image.new('RGB', (width, height), color='#202020')
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 40)
    except IOError:
        font = ImageFont.load_default()
    draw.text((12, 8), "I", fill="#00BFFF", font=font)
    return image


# --- 3. ОБРАБОТЧИКИ (Actions) ---

def run_in_thread(target, *args, **kwargs):
    threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True).start()


def update_tray_icon_thread(icon, is_initial=False):
    # (Определен ниже)
    pass


# !!! ИСПРАВЛЕНИЕ: Изменяем сигнатуру функции !!!
def set_viewed_city(icon, item, city_data):
    """Устанавливает, чью погоду нужно отображать."""
    global VIEWED_LOCATION
    VIEWED_LOCATION = city_data.copy()
    run_in_thread(update_tray_icon_thread, icon, is_initial=False)


# !!! ИСПРАВЛЕНИЕ: Изменяем сигнатуру функции !!!
def pin_city(icon, item, city_data):
    """Добавляет или удаляет город из списка сохраненных."""
    if any((c['name'] == city_data['name']) for c in city_manager.cities):
        city_manager.remove_city(city_data)
    else:
        city_manager.add_city(city_data)
    run_in_thread(update_tray_icon_thread, icon, is_initial=False)


# --- 4. ГЕНЕРАЦИЯ МЕНЮ (Исправлено) ---

def create_main_menu(icon, current_data):
    """
    Генерирует главное меню (ПКМ) со всеми данными и селектором городов.
    """
    current_time = current_data['time']
    weather = current_data['weather']
    battery = current_data['battery']

    # 1. Секция информации
    info_items = [
        MenuItem(f"📍 Город: {VIEWED_LOCATION['name']}", None),
        MenuItem(f"⌚ Время: {current_time}", None),
        MenuItem(f"🌍 {weather}", None),
        MenuItem(f"🔋 Батарея: {battery}", None),
        Menu.SEPARATOR
    ]

    # 2. Секция управления городами
    city_items = []
    city_items.append(MenuItem("--- Сохраненные города ---", None))

    for city in city_manager.cities:
        is_selected = city['name'] == VIEWED_LOCATION['name']

        # Используем partial, передавая только аргумент city_data
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

    # Добавляем опцию "Показать моё (IP) место"
    if current_data['ip_location'] and VIEWED_LOCATION.get('name') != current_data['ip_location']['name']:
        city_items.append(Menu.SEPARATOR)
        ip_action = functools.partial(set_viewed_city, city_data=current_data['ip_location'])
        city_items.append(
            MenuItem(f"➡️ Показать моё (IP) место", ip_action)
        )

    # Пункт "Закрепить текущий город"
    if VIEWED_LOCATION['name'] not in [c['name'] for c in city_manager.cities] and VIEWED_LOCATION['lat'] is not None:
        current_pin_action = functools.partial(pin_city, city_data=VIEWED_LOCATION)
        city_items.append(
            MenuItem(f"📌 Закрепить {VIEWED_LOCATION['name']}", current_pin_action)
        )

    # 3. Общее меню
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
        threading.Timer(5, update_tray_icon_thread, args=(icon, is_initial)).start()
        return

    weather = get_weather_for_city(VIEWED_LOCATION['lat'], VIEWED_LOCATION['lon'])
    current_time = time.strftime("%H:%M:%S")
    battery = get_battery()

    current_data = {
        'time': current_time,
        'weather': weather,
        'battery': battery,
        'ip_location': ip_location
    }

    icon.tooltip = f"[{VIEWED_LOCATION['name']}] | {current_time} | {weather} | Батарея: {battery}"

    icon.menu = create_main_menu(icon, current_data)

    if is_initial or icon._running:
        threading.Timer(30, update_tray_icon_thread, args=(icon,)).start()


def setup_tray_icon():
    """Настройка и запуск иконки в трее."""
    image = create_icon_image()

    initial_menu = Menu(MenuItem('Идет загрузка данных...', None), Menu.SEPARATOR,
                        MenuItem('Выход', lambda icon: icon.stop()))

    tray_icon = Icon(
        name='custom_info_widget',
        icon=image,
        title='Системная Информация',
        menu=initial_menu
    )

    # Обработчик ОДИНАРНОГО ЛКМ
    def on_single_click(icon, _):
        run_in_thread(update_tray_icon_thread, icon, is_initial=False)

    tray_icon.on_click = on_single_click

    run_in_thread(update_tray_icon_thread, tray_icon, is_initial=True)

    tray_icon.run()


if __name__ == '__main__':
    print("Запуск системного виджета. ЛКМ - обновить данные, ПКМ - меню городов.")
    setup_tray_icon()