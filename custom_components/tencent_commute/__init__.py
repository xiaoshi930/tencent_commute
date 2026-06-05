"""The Tencent Commute Tracker integration."""
import asyncio
from datetime import timedelta
import logging

import aiohttp
import async_timeout
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_NAME,
    Platform,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    CONF_API_KEY,
    CONF_UPDATE_INTERVAL,
    CONF_ORIGIN,
    CONF_DESTINATION,
    COORDINATOR,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

COORDINATE_UPDATE_INTERVAL = timedelta(minutes=1)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tencent Commute Tracker from a config entry."""
    # 验证配置
    required_keys = [CONF_API_KEY, CONF_ORIGIN, CONF_DESTINATION]
    for key in required_keys:
        if key not in entry.data:
            _LOGGER.error(f"缺少必要的配置项：{key}")
            return False

    api_key = entry.data[CONF_API_KEY]
    update_interval = entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    origin_raw = entry.data[CONF_ORIGIN]
    destination_raw = entry.data[CONF_DESTINATION]

    # 验证起点和终点（如果是实体，验证实体存在且有位置属性）
    def _validate_location(value):
        if isinstance(value, str) and "," in value:  # 直接坐标格式
            return True
        elif isinstance(value, str):  # 实体模式
            entity_id = value
            if value.startswith("entity:"):
                entity_id = value[7:]
            entity = hass.states.get(entity_id)
            if entity is None:
                _LOGGER.error(f"实体 {value} 不存在，尝试查找的实体ID: {entity_id}")
                return False
            attrs = entity.attributes
            if "longitude" not in attrs or "latitude" not in attrs:
                _LOGGER.error(f"实体 {entity_id} 缺少经纬度属性")
                return False
            return True
        return False

    if not _validate_location(origin_raw):
        _LOGGER.error("起点格式无效或实体不存在")
        return False
    if not _validate_location(destination_raw):
        _LOGGER.error("终点格式无效或实体不存在")
        return False

    # 检查API Key格式
    if not isinstance(api_key, str) or len(api_key) != 35:
        _LOGGER.error("API Key格式无效（必须为35位字符串）")
        return False
    elif not api_key.replace("-", "").isalnum():
        _LOGGER.error("API Key格式无效（包含非法字符）")
        return False

    # 检查更新间隔
    try:
        update_interval = int(float(update_interval))
        if update_interval < 1 or update_interval > 60:
            raise ValueError
    except (ValueError, TypeError):
        _LOGGER.error(f"更新间隔无效：{update_interval}（必须为1-60的整数）")
        return False

    session = async_get_clientsession(hass)

    coordinator = TencentDataUpdateCoordinator(
        hass,
        _LOGGER,
        api_key=api_key,
        origin_raw=origin_raw,
        destination_raw=destination_raw,
        update_interval=timedelta(minutes=update_interval),
        session=session,
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as e:
        _LOGGER.error(f"初始化协调器失败：{e}")
        return False

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        COORDINATOR: coordinator,
    }

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception as e:
        _LOGGER.error(f"设置平台失败：{e}")
        return False

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    try:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        if unload_ok:
            coordinator = hass.data[DOMAIN].get(entry.entry_id, {}).get(COORDINATOR)
            if coordinator:
                coordinator.async_shutdown()
            hass.data[DOMAIN].pop(entry.entry_id, None)
            _LOGGER.debug(f"成功卸载配置项：{entry.entry_id}")
        else:
            _LOGGER.error(f"卸载平台失败：{entry.entry_id}")
        return unload_ok
    except Exception as e:
        _LOGGER.error(f"卸载配置项时出错：{e}")
        return False


class TencentDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger,
        api_key,
        origin_raw,
        destination_raw,
        update_interval,
        session,
    ):
        """Initialize."""
        self.hass = hass
        self.api_key = api_key
        self.session = session
        self.logger = logger

        # 保存原始配置值，不覆盖
        self._origin_raw = origin_raw
        self._destination_raw = destination_raw

        # 解析后的坐标
        self._resolved_origin = None
        self._resolved_destination = None

        # 判断是否为实体模式并解析实体ID
        self._origin_is_entity = False
        self._destination_is_entity = False
        self._origin_entity_id = None
        self._destination_entity_id = None

        if isinstance(origin_raw, str) and origin_raw.startswith("entity:"):
            self._origin_entity_id = origin_raw.split(":", 1)[1]
            self._origin_is_entity = True
        elif isinstance(origin_raw, str) and "," not in origin_raw:
            self._origin_entity_id = origin_raw
            self._origin_is_entity = True

        if isinstance(destination_raw, str) and destination_raw.startswith("entity:"):
            self._destination_entity_id = destination_raw.split(":", 1)[1]
            self._destination_is_entity = True
        elif isinstance(destination_raw, str) and "," not in destination_raw:
            self._destination_entity_id = destination_raw
            self._destination_is_entity = True

        # 记录初始化信息
        logger.debug(f"初始化腾讯通勤追踪器：起点类型={'实体' if self._origin_is_entity else '坐标'}, 终点类型={'实体' if self._destination_is_entity else '坐标'}")
        logger.debug(f"更新间隔：{update_interval}分钟，坐标刷新间隔：1分钟")

        # 初始解析坐标
        self._resolve_coordinates()

        # 设置每分钟更新坐标的定时器
        self._remove_coordinate_listener = async_track_time_interval(
            hass, self._async_update_coordinates_callback, COORDINATE_UPDATE_INTERVAL
        )

        super().__init__(hass, logger, name=DOMAIN, update_interval=update_interval)

    def _resolve_coordinates(self):
        """从HA实体状态解析坐标（同步方法）。"""
        if self._origin_is_entity and self._origin_entity_id:
            entity_state = self.hass.states.get(self._origin_entity_id)
            if entity_state and "latitude" in entity_state.attributes and "longitude" in entity_state.attributes:
                new_origin = f"{entity_state.attributes['latitude']},{entity_state.attributes['longitude']}"
                if new_origin != self._resolved_origin:
                    self.logger.info(f"起点坐标更新：{self._resolved_origin} -> {new_origin}")
                self._resolved_origin = new_origin
                self.logger.info(f"获取起点坐标：实体={self._origin_entity_id}, 坐标={self._resolved_origin}")
            else:
                self.logger.warning(f"无法从实体 {self._origin_entity_id} 获取坐标，保留上次坐标")
        else:
            self._resolved_origin = self._origin_raw
            self.logger.info(f"获取起点坐标（固定）：{self._resolved_origin}")

        if self._destination_is_entity and self._destination_entity_id:
            entity_state = self.hass.states.get(self._destination_entity_id)
            if entity_state and "latitude" in entity_state.attributes and "longitude" in entity_state.attributes:
                new_destination = f"{entity_state.attributes['latitude']},{entity_state.attributes['longitude']}"
                if new_destination != self._resolved_destination:
                    self.logger.info(f"终点坐标更新：{self._resolved_destination} -> {new_destination}")
                self._resolved_destination = new_destination
                self.logger.info(f"获取终点坐标：实体={self._destination_entity_id}, 坐标={self._resolved_destination}")
            else:
                self.logger.warning(f"无法从实体 {self._destination_entity_id} 获取坐标，保留上次坐标")
        else:
            self._resolved_destination = self._destination_raw
            self.logger.info(f"获取终点坐标（固定）：{self._resolved_destination}")

    @callback
    def _async_update_coordinates_callback(self, now):
        """每分钟回调，刷新实体坐标。"""
        self._resolve_coordinates()

    def async_shutdown(self):
        """关闭协调器，取消坐标定时器。"""
        if hasattr(self, '_remove_coordinate_listener') and self._remove_coordinate_listener:
            self._remove_coordinate_listener()
            self._remove_coordinate_listener = None

    async def _async_update_data(self):
        """Update data via API."""
        try:
            async with async_timeout.timeout(10):
                self.logger.debug("开始更新腾讯通勤数据")

                # 确保坐标已解析
                if not self._resolved_origin or not self._resolved_destination:
                    self.logger.error("缺少有效的起点或终点坐标")
                    return {
                        "driving": {"duration": 0, "distance": 0},
                        "transit": {"duration": 0, "distance": 0},
                        "bicycling": {"duration": 0, "distance": 0},
                        "walking": {"duration": 0, "distance": 0},
                    }

                # 记录当前使用的坐标
                self.logger.debug(f"当前坐标：起点={self._resolved_origin}, 终点={self._resolved_destination}")

                # 获取各种路线规划
                driving_data = await self._fetch_driving_route()
                transit_data = await self._fetch_transit_route()
                bicycling_data = await self._fetch_bicycling_route()
                walking_data = await self._fetch_walking_route()

                self.logger.debug(f"更新完成：驾车={driving_data}, 公交={transit_data}, 骑行={bicycling_data}, 步行={walking_data}")

                return {
                    "driving": driving_data,
                    "transit": transit_data,
                    "bicycling": bicycling_data,
                    "walking": walking_data,
                }
        except asyncio.TimeoutError:
            self.logger.error("请求腾讯API超时")
            return {
                "driving": {"duration": 0, "distance": 0},
                "transit": {"duration": 0, "distance": 0},
                "bicycling": {"duration": 0, "distance": 0},
                "walking": {"duration": 0, "distance": 0},
            }
        except Exception as err:
            self.logger.error(f"请求腾讯API时出错：{err}")
            return {
                "driving": {"duration": 0, "distance": 0},
                "transit": {"duration": 0, "distance": 0},
                "bicycling": {"duration": 0, "distance": 0},
                "walking": {"duration": 0, "distance": 0},
            }

    async def _fetch_driving_route(self):
        """Fetch driving route data from Tencent API."""
        url = "https://apis.map.qq.com/ws/direction/v1/driving/"

        if not self._resolved_origin or not self._resolved_destination:
            self.logger.error("缺少有效的起点或终点坐标")
            return {"duration": 0, "distance": 0}

        self.logger.debug(f"请求驾车路线：起点={self._resolved_origin}, 终点={self._resolved_destination}")

        params = {
            "key": self.api_key,
            "from": self._resolved_origin,
            "to": self._resolved_destination,
            "output": "json"
        }

        try:
            async with self.session.get(url, params=params) as response:
                data = await response.json()

                if data.get("status") == 0:
                    result = data.get("result", {})
                    routes = result.get("routes", [])
                    if routes:
                        route = routes[0]
                        duration = int(route.get("duration", 0))
                        distance = int(route.get("distance", 0))
                        return {
                            "duration": duration,
                            "distance": distance,
                        }
                else:
                    self.logger.error(f"腾讯API返回错误：{data.get('message')}")
                return {"duration": 0, "distance": 0}
        except Exception as e:
            self.logger.error(f"请求腾讯API时出错：{e}")
            return {"duration": 0, "distance": 0}

    async def _fetch_transit_route(self):
        """Fetch transit route data from Tencent API."""
        url = "https://apis.map.qq.com/ws/direction/v1/transit/"

        if not self._resolved_origin or not self._resolved_destination:
            self.logger.error("缺少有效的起点或终点坐标")
            return {"duration": 0, "distance": 0}

        self.logger.debug(f"请求公交路线：起点={self._resolved_origin}, 终点={self._resolved_destination}")

        params = {
            "key": self.api_key,
            "from": self._resolved_origin,
            "to": self._resolved_destination,
            "output": "json"
        }

        try:
            async with self.session.get(url, params=params) as response:
                data = await response.json()

                if data.get("status") == 0:
                    result = data.get("result", {})
                    routes = result.get("routes", [])
                    if routes:
                        route = routes[0]
                        duration = int(route.get("duration", 0))
                        distance = int(route.get("distance", 0))
                        return {
                            "duration": duration,
                            "distance": distance,
                        }
                else:
                    self.logger.error(f"腾讯API返回错误：{data.get('message')}")
                return {"duration": 0, "distance": 0}
        except Exception as e:
            self.logger.error(f"请求腾讯API时出错：{e}")
            return {"duration": 0, "distance": 0}

    async def _fetch_bicycling_route(self):
        """Fetch bicycling route data from Tencent API."""
        url = "https://apis.map.qq.com/ws/direction/v1/bicycling/"

        if not self._resolved_origin or not self._resolved_destination:
            self.logger.error("缺少有效的起点或终点坐标")
            return {"duration": 0, "distance": 0}

        self.logger.debug(f"请求骑行路线：起点={self._resolved_origin}, 终点={self._resolved_destination}")

        params = {
            "key": self.api_key,
            "from": self._resolved_origin,
            "to": self._resolved_destination,
            "output": "json"
        }

        try:
            async with self.session.get(url, params=params) as response:
                data = await response.json()

                if data.get("status") == 0:
                    result = data.get("result", {})
                    routes = result.get("routes", [])
                    if routes:
                        route = routes[0]
                        duration = int(route.get("duration", 0))
                        distance = int(route.get("distance", 0))
                        return {
                            "duration": duration,
                            "distance": distance,
                        }
                else:
                    self.logger.error(f"腾讯API返回错误：{data.get('message')}")
                return {"duration": 0, "distance": 0}
        except Exception as e:
            self.logger.error(f"请求腾讯API时出错：{e}")
            return {"duration": 0, "distance": 0}

    async def _fetch_walking_route(self):
        """Fetch walking route data from Tencent API."""
        url = "https://apis.map.qq.com/ws/direction/v1/walking/"

        if not self._resolved_origin or not self._resolved_destination:
            self.logger.error("缺少有效的起点或终点坐标")
            return {"duration": 0, "distance": 0}

        self.logger.debug(f"请求步行路线：起点={self._resolved_origin}, 终点={self._resolved_destination}")

        params = {
            "key": self.api_key,
            "from": self._resolved_origin,
            "to": self._resolved_destination,
            "output": "json"
        }

        try:
            async with self.session.get(url, params=params) as response:
                data = await response.json()

                if data.get("status") == 0:
                    result = data.get("result", {})
                    routes = result.get("routes", [])
                    if routes:
                        route = routes[0]
                        duration = int(route.get("duration", 0))
                        distance = int(route.get("distance", 0))
                        return {
                            "duration": duration,
                            "distance": distance,
                        }
                else:
                    self.logger.error(f"腾讯API返回错误：{data.get('message')}")
                return {"duration": 0, "distance": 0}
        except Exception as e:
            self.logger.error(f"请求腾讯API时出错：{e}")
            return {"duration": 0, "distance": 0}
