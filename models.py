from pydantic import BaseModel


class HourModel(BaseModel):
    hour: int
    temp: int
    condition: str


class DateModel(BaseModel):
    date: str
    hours: list[HourModel]


class ListDateModel(BaseModel):
    forecasts: list[DateModel]


class CityModel(BaseModel):
    city: str
    forecasts: ListDateModel


class DayWeatherConditionsModel(BaseModel):
    date: str
    daily_avg_temp: float
    clear_weather_cond: int


class CombinedWeatherConditionsModel(BaseModel):
    city: str
    data: list[DayWeatherConditionsModel]


class FinalOutputModel(BaseModel):
    city: str
    data: list[DayWeatherConditionsModel]
    total_avg_temp: float
    total_clear_weather_cond: int
    rating: int
