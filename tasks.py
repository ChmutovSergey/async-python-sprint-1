import json
import logging
from dataclasses import dataclass
from threading import RLock

import openpyxl
from openpyxl import Workbook
from openpyxl.styles import Border, Side

from external.client import YandexWeatherAPI
from models import CityModel, FinalOutputModel, CombinedWeatherConditionsModel, DayWeatherConditionsModel
from utils import START_TIME, END_TIME, CONDITIONS, RESULT_FILE_NAME, XLSX_FILE_NAME, COLUMNS_NAME

FORMAT = "%(asctime)s - %(name)s - %(funcName)s - %(levelname)s - %(message)s"
FORMAT_DATE = "%Y-%m-%dT%H:%M:%S"

logging.basicConfig(
    format=FORMAT,
    datefmt=FORMAT_DATE,
    level=logging.INFO,
)
formatter = logging.Formatter(
    FORMAT,
    datefmt=FORMAT_DATE
)
logger = logging.getLogger(__name__)


@dataclass
class DataFetchingTask:
    """
    Получение данных через API Яндекс.Погоды
    """
    yw_api: YandexWeatherAPI = YandexWeatherAPI()

    def make_request(self, city: tuple[str, ...]) -> CityModel:
        """
        Метод для получения данных по API
        """
        logger.info("Making request to Yandex Weather API for city: %s", city[0])
        city_data = self.yw_api.get_forecasting(city[-1])
        logger.debug("API response: %s", city_data)
        if city_data:
            return CityModel(
                city=city[0],
                forecasts=city_data
            )


class DataCalculationTask:
    """
    Вычисление погодных параметров
    """
    @staticmethod
    def additional_calculating(temp_data: list[int | float]) -> float:
        """
        Вычисление средних показателей с округлением
        """
        if not temp_data:
            return 0
        return round(sum(temp_data) / len(temp_data), 2)

    def _calculating_data(self, city_data: CityModel) -> CombinedWeatherConditionsModel:
        """
        Вычисление средних показателей
        """
        logger.info("Calculating statistics for city: %s", city_data.city)
        weather_data = []
        for day in city_data.forecasts.forecasts:
            result_temp_for_day = []
            count_clear_cond = 0

            for hour in day.hours:
                if START_TIME < hour.hour < END_TIME:
                    result_temp_for_day.append(hour.temp)
                    count_clear_cond += 1 if hour.condition in CONDITIONS else 0
            logger.debug(
                "Creating and adding a DayWeatherConditionsModel to a list for city: %s",
                city_data.city
            )
            weather_data.append(
                DayWeatherConditionsModel(
                    date=day.date,
                    daily_avg_temp=self.additional_calculating(result_temp_for_day),
                    clear_weather_cond=count_clear_cond
                )
            )
        return CombinedWeatherConditionsModel(
            city=city_data.city,
            data=weather_data,
        )

    def _calc_general_indicators_for_day(self, data: CombinedWeatherConditionsModel) -> FinalOutputModel:
        """
        Добавление финальных показателей
        """
        list_avg_temp = []
        total_avg_clear_weather_cond = 0
        for element in data.data:
            if element.daily_avg_temp != 0.0:
                list_avg_temp.append(element.daily_avg_temp)
                total_avg_clear_weather_cond += element.clear_weather_cond

        logger.debug("Calculation of averages for city: %s", data.city)
        total_avg_temperature = self.additional_calculating(list_avg_temp)

        logger.debug("Creating and returning a FinalOutputModel to for city: %s", data.city)
        return FinalOutputModel(
            city=data.city,
            data=data.data,
            total_avg_temp=total_avg_temperature,
            total_clear_weather_cond=total_avg_clear_weather_cond,
            rating=0,
        )

    @staticmethod
    def adding_rating(data: list[FinalOutputModel]) -> list[dict[str, any]]:
        """
        Добавление рейтинга города
        """
        total_rating = [
            (
                city_info.city,
                city_info.total_avg_temp,
                city_info.total_clear_weather_cond
            ) for city_info in data
        ]

        sorted_rating = sorted(total_rating, key=lambda x: (-x[1], -x[2]))
        dict_rating = {city_info[0]: enum + 1 for enum, city_info in enumerate(sorted_rating)}
        logger.debug("Adding a rating to each city: %s", dict_rating)

        for element in data:
            element.rating = dict_rating[element.city]

        result = [element.dict() for element in data]
        logger.debug("Converting models to a dictionary")

        return result

    def run(self, city_data: CityModel) -> FinalOutputModel:
        """
        Вычисление результатов для обработки вне класса
        """
        logger.info("Getting the FinalOutputModel for city: %s", city_data.city)
        calculating = self._calculating_data(city_data)
        result = self._calc_general_indicators_for_day(calculating)
        logger.debug("Returning the FinalOutputModel for city: %s", city_data.city)
        return result


@dataclass
class DataAggregationTask:
    """
    Объединение вычисленных данных
    """
    lock: RLock
    data: list[dict[str, any]]

    def save_results_as_json(self):
        """
        Сохранение аналитических данных в формате Json
        """
        logger.debug("Saving results to a file")
        with open(RESULT_FILE_NAME, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def prepare_table_xlsx(self):
        """
        Создание таблицы и заполнение первой строки
        """
        logger.info("Creating an xlsx table and creating column names")
        wb = Workbook()
        sheet = wb.active
        data_first_string = [
            "Страна/день",
            "Показатель",
            "Среднее",
            "Рейтинг",
        ]
        elm_from_data = self.data[0].get("data")
        amount_city = len(self.data)
        list_of_days = [i.get("date") for i in elm_from_data]

        for idx in range(len(list_of_days)):
            data_first_string.insert(2 + idx, list_of_days[idx])

        for letter in COLUMNS_NAME:
            sheet.column_dimensions[letter].width = 15

        for row in range((amount_city + 1) * 2):
            sheet.row_dimensions[row].height = 20

        sheet.append(data_first_string)
        wb.save(XLSX_FILE_NAME)
        logger.debug("Saving xlsx table with column names")

    @staticmethod
    def preparing_data_for_insertion(element: dict) -> tuple[list, ...]:
        """
        Подготовка данных для вставки в таблицу
        """
        logger.debug("Create row 1 for the city: %s", element.get("city"))
        row_1 = [
            element.get("city"),
            "Температура, среднее",
            *(element.get("data")[i].get("daily_avg_temp") for i in range(len(element.get("data")))),
            element.get("total_avg_temp"),
            element.get("rating")
        ]
        logger.debug("Create row 2 for the city: %s", element.get("city"))
        row_2 = [
            "",
            "Без осадков, часов",
            *(element.get("data")[i].get("clear_weather_cond") for i in range(len(element.get("data")))),
            element.get("total_clear_weather_cond"),
            ""
        ]
        logger.info("Return prepared data")
        return row_1, row_2

    def filling_in_table(self, element: [list | tuple]):
        """Вставка данных в таблицу"""
        logger.debug("Blocking a thread anf inserting data for a city: %s", element[0][0])
        with self.lock:
            wb = openpyxl.load_workbook(XLSX_FILE_NAME)
            sheet = wb.active
            for row in (0, 1):
                sheet.append(element[row])
                logger.debug(
                    "Successfully written to the table: %s",
                    "; ".join(str(i) for i in element[row])
                )

            wb.save(XLSX_FILE_NAME)

    @staticmethod
    def adding_boarder():
        """
        Добавление разметки между столбцами и колонками
        """
        wb = openpyxl.load_workbook(XLSX_FILE_NAME)
        sheet = wb.active
        thins = Side(border_style="thin", color="000000")
        for row in range(1, 33):
            for col in range(1, 10):
                if row == 32:
                    sheet.cell(
                        row=row,
                        column=col
                    ).border = Border(top=thins)
                else:
                    sheet.cell(
                        row=row,
                        column=col
                    ).border = Border(
                        left=thins,
                        right=thins,
                        top=thins,
                        end=thins
                    )
        wb.save(XLSX_FILE_NAME)
        logger.debug("Added markup between columns and columns and saved the file")


@dataclass
class DataAnalyzingTask:
    """
    Финальный анализ и получение результата
    """
    data: list[dict[str, any]]

    def get_result(self) -> str:
        """
        Метод получения результата
        """
        logger.info("Finding the best temperature and number of sunny days")
        result = []
        max_temp = -9999
        sunniest_weather = 0
        for city_data in self.data:
            if city_data["rating"] == 1:
                max_temp = city_data["total_avg_temp"]
                sunniest_weather = city_data["total_clear_weather_cond"]
                break

        logger.info("Adding eligible cities to the final list")
        for city_data in self.data:
            if city_data["total_avg_temp"] == max_temp or city_data["total_clear_weather_cond"] == sunniest_weather:
                result.append(
                    {
                        "city": city_data["city"],
                        "total_avg_temp": city_data["total_avg_temp"],
                        "total_clear_weather_cond": city_data["total_clear_weather_cond"]
                    }
                )
        answer = "Лучший город"
        result_str = ""
        for city in result:
            result_str += f'{city["city"]}, средняя температура: ' \
                          f'{city["total_avg_temp"]}, а количество ' \
                          f'времени без осадков ' \
                          f'{city["total_clear_weather_cond"]} часов.\n'
        return f"{answer} {result_str}"
