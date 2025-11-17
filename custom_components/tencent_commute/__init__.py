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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
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
    
    # 获取起点和终点（支持直接输入或从实体属性获取）
    def _get_coordinates(value):
        if isinstance(value, str) and "," in value:  # 直接输入格式
            return value
        elif isinstance(value, str):  # 实体模式
            # 处理可能包含 "entity:" 前缀的实体ID
            entity_id = value
            if value.startswith("entity:"):
                entity_id = value[7:]  # 移除 "entity:" 前缀
            
            entity = hass.states.get(entity_id)
            if entity is None:
                _LOGGER.error(f"实体 {value} 不存在，尝试查找的实体ID: {entity_id}")
                return None
            
            attrs = entity.attributes
            if "longitude" not in attrs or "latitude" not in attrs:
                _LOGGER.error(f"实体 {entity_id} 缺少经纬度属性")
                return None
            
            return f"{attrs['latitude']},{attrs['longitude']}"
        return None

    origin = _get_coordinates(entry.data[CONF_ORIGIN])
    destination = _get_coordinates(entry.data[CONF_DESTINATION])
    if origin is None or destination is None:
        return False
    
    # 检查API Key格式
    if not isinstance(api_key, str) or len(api_key) != 35:
        _LOGGER.error("API Key格式无效（必须为35位字符串）")
        return False
    elif not api_key.replace("-", "").isalnum():
        # 移除连字符后检查是否只包含字母数字
        _LOGGER.error("API Key格式无效（包含非法字符）")
        return False
        

        
    # 检查更新间隔（支持浮点数转换）
    try:
        update_interval = int(float(update_interval))  # 兼容浮点数输入
        if update_interval < 1 or update_interval > 60:
            raise ValueError
    except (ValueError, TypeError):
        _LOGGER.error(f"更新间隔无效：{update_interval}（必须为1-60的整数）")
        return False
        
    # 检查起点和终点格式
    if not isinstance(origin, str) or not origin:
        _LOGGER.error("起点格式无效")
        return False
        
    if not isinstance(destination, str) or not destination:
        _LOGGER.error("终点格式无效")
        return False

    session = async_get_clientsession(hass)

    coordinator = TencentDataUpdateCoordinator(
        hass,
        _LOGGER,
        api_key=api_key,
        origin=origin,
        destination=destination,
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
        origin,
        destination,
        update_interval,
        session,
    ):
        """Initialize."""
        self.hass = hass
        self.api_key = api_key
        self.origin = origin
        self.destination = destination
        self.session = session
        
        # 初始化日志记录器
        self.logger = logger
        
        # 记录初始化信息（隐藏敏感信息）
        logger.debug(f"初始化腾讯通勤追踪器：起点类型={'实体' if isinstance(origin, str) and origin.startswith('entity:') else '坐标'}, 终点类型={'实体' if isinstance(destination, str) and destination.startswith('entity:') else '坐标'}")
        logger.debug(f"更新间隔：{update_interval}分钟")
        
        # 检查是否使用实体作为位置
        if isinstance(origin, str) and origin.startswith("entity:"):
            self.origin_entity_id = origin.split(":", 1)[1]
            logger.debug(f"使用实体作为起点：{self.origin_entity_id}")
        
        if isinstance(destination, str) and destination.startswith("entity:"):
            self.destination_entity_id = destination.split(":", 1)[1]
            logger.debug(f"使用实体作为终点：{self.destination_entity_id}")

        super().__init__(hass, logger, name=DOMAIN, update_interval=update_interval)

    async def _async_update_data(self):
        """Update data via API."""
        try:
            async with async_timeout.timeout(10):
                # 记录更新开始
                self.logger.debug("开始更新腾讯通勤数据")
                
                # 更新实体位置（如果使用的是实体）
                if not await self._update_entity_locations():
                    self.logger.error("更新实体位置失败")
                    return {
                        "driving": {"duration": 0, "distance": 0},
                        "transit": {"duration": 0, "distance": 0},
                        "bicycling": {"duration": 0, "distance": 0},
                        "walking": {"duration": 0, "distance": 0},
                    }
                
                # 记录当前使用的坐标
                self.logger.debug(f"当前坐标：起点={self.origin}, 终点={self.destination}")
                
                # 获取驾车路线规划
                driving_data = await self._fetch_driving_route()
                # 获取公交路线规划
                transit_data = await self._fetch_transit_route()
                # 获取骑行路线规划
                bicycling_data = await self._fetch_bicycling_route()
                # 获取步行路线规划
                walking_data = await self._fetch_walking_route()
                
                # 记录获取到的数据
                self.logger.debug(f"更新完成：驾车={driving_data}, 公交={transit_data}, 骑行={bicycling_data}, 步行={walking_data}")

                return {
                    "driving": driving_data,
                    "transit": transit_data,
                    "bicycling": bicycling_data,
                    "walking": walking_data,
                }
        except asyncio.TimeoutError:
            self.logger.error("请求腾讯API超时")
            # 返回空数据而不是抛出异常，避免组件崩溃
            return {
                "driving": {"duration": 0, "distance": 0},
                "transit": {"duration": 0, "distance": 0},
                "bicycling": {"duration": 0, "distance": 0},
                "walking": {"duration": 0, "distance": 0},
            }
        except Exception as err:
            self.logger.error(f"请求腾讯API时出错：{err}")
            # 返回空数据而不是抛出异常，避免组件崩溃
            return {
                "driving": {"duration": 0, "distance": 0},
                "transit": {"duration": 0, "distance": 0},
                "bicycling": {"duration": 0, "distance": 0},
                "walking": {"duration": 0, "distance": 0},
            }
            
    async def _update_entity_locations(self):
        """Update entity locations if entities are used."""
        # 检查起点是否为实体
        if isinstance(self.origin, str) and self.origin.startswith("entity:"):
            entity_id = self.origin.split(":", 1)[1]
            entity_state = self.hass.states.get(entity_id)
            
            if entity_state is None:
                _LOGGER.error(f"无法找到实体：{entity_id}")
                return False
                
            if entity_state.attributes.get("longitude") is None or entity_state.attributes.get("latitude") is None:
                _LOGGER.error(f"实体 {entity_id} 缺少位置属性")
                return False
                
            self.origin = f"{entity_state.attributes.get('latitude')},{entity_state.attributes.get('longitude')}"
            self.logger.debug(f"更新起点坐标：{self.origin}")
        
        # 检查终点是否为实体
        if isinstance(self.destination, str) and self.destination.startswith("entity:"):
            entity_id = self.destination.split(":", 1)[1]
            entity_state = self.hass.states.get(entity_id)
            
            if entity_state is None:
                _LOGGER.error(f"无法找到实体：{entity_id}")
                return False
                
            if entity_state.attributes.get("longitude") is None or entity_state.attributes.get("latitude") is None:
                _LOGGER.error(f"实体 {entity_id} 缺少位置属性")
                return False
                
            self.destination = f"{entity_state.attributes.get('latitude')},{entity_state.attributes.get('longitude')}"
            self.logger.debug(f"更新终点坐标：{self.destination}")
            
        return True

    async def _fetch_driving_route(self):
        """Fetch driving route data from Tencent API."""
        url = "https://apis.map.qq.com/ws/direction/v1/driving/"
        
        # 确保我们有有效的坐标
        if not self.origin or not self.destination:
            self.logger.error("缺少有效的起点或终点坐标")
            return {"duration": 0, "distance": 0}
            
        # 如果是实体ID格式，需要先更新位置
        if isinstance(self.origin, str) and self.origin.startswith("entity:") or \
           isinstance(self.destination, str) and self.destination.startswith("entity:"):
            await self._update_entity_locations()
            
        # 记录请求信息
        self.logger.debug(f"请求驾车路线：起点={self.origin}, 终点={self.destination}")
        
        params = {
            "key": self.api_key,
            "from": self.origin,
            "to": self.destination,
            "output": "json"
        }

        try:
            async with self.session.get(url, params=params) as response:
                data = await response.json()
                # self.logger.debug(f"腾讯API响应：{data}")
                
                if data.get("status") == 0:
                    result = data.get("result", {})
                    routes = result.get("routes", [])
                    if routes:
                        route = routes[0]
                        duration = int(route.get("duration", 0))  # 分钟
                        distance = int(route.get("distance", 0))  # 米
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
        
        # 确保我们有有效的坐标
        if not self.origin or not self.destination:
            self.logger.error("缺少有效的起点或终点坐标")
            return {"duration": 0, "distance": 0}
            
        # 如果是实体ID格式，需要先更新位置
        if isinstance(self.origin, str) and self.origin.startswith("entity:") or \
           isinstance(self.destination, str) and self.destination.startswith("entity:"):
            await self._update_entity_locations()
            
        # 记录请求信息
        self.logger.debug(f"请求骑行路线：起点={self.origin}, 终点={self.destination}")
        
        params = {
            "key": self.api_key,
            "from": self.origin,
            "to": self.destination,
            "output": "json"
        }

        try:
            async with self.session.get(url, params=params) as response:
                data = await response.json()
                # self.logger.debug(f"腾讯API响应：{data}")
                
                if data.get("status") == 0:
                    result = data.get("result", {})
                    routes = result.get("routes", [])
                    if routes:
                        route = routes[0]
                        duration = int(route.get("duration", 0))  # 分钟
                        distance = int(route.get("distance", 0))  # 米
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
        
        # 确保我们有有效的坐标
        if not self.origin or not self.destination:
            self.logger.error("缺少有效的起点或终点坐标")
            return {"duration": 0, "distance": 0}
            
        # 如果是实体ID格式，需要先更新位置
        if isinstance(self.origin, str) and self.origin.startswith("entity:") or \
           isinstance(self.destination, str) and self.destination.startswith("entity:"):
            await self._update_entity_locations()
            
        # 记录请求信息
        self.logger.debug(f"请求步行路线：起点={self.origin}, 终点={self.destination}")
        
        params = {
            "key": self.api_key,
            "from": self.origin,
            "to": self.destination,
            "output": "json"
        }

        try:
            async with self.session.get(url, params=params) as response:
                data = await response.json()
                # self.logger.debug(f"腾讯API响应：{data}")
                
                if data.get("status") == 0:
                    result = data.get("result", {})
                    routes = result.get("routes", [])
                    if routes:
                        route = routes[0]
                        duration = int(route.get("duration", 0))  # 分钟
                        distance = int(route.get("distance", 0))  # 米
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
        
        # 确保我们有有效的坐标
        if not self.origin or not self.destination:
            self.logger.error("缺少有效的起点或终点坐标")
            return {"duration": 0, "distance": 0}
            
        # 如果是实体ID格式，需要先更新位置
        if isinstance(self.origin, str) and self.origin.startswith("entity:") or \
           isinstance(self.destination, str) and self.destination.startswith("entity:"):
            await self._update_entity_locations()
            
        # 记录请求信息
        self.logger.debug(f"请求公交路线：起点={self.origin}, 终点={self.destination}")
        
        params = {
            "key": self.api_key,
            "from": self.origin,
            "to": self.destination,
            "output": "json"
        }

        try:
            async with self.session.get(url, params=params) as response:
                data = await response.json()
                # self.logger.debug(f"腾讯API响应：{data}")
                
                if data.get("status") == 0:
                    result = data.get("result", {})
                    routes = result.get("routes", [])
                    if routes:
                        route = routes[0]
                        duration = int(route.get("duration", 0))  # 分钟
                        distance = int(route.get("distance", 0))  # 米
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
        
        # 确保我们有有效的坐标
        if not self.origin or not self.destination:
            self.logger.error("缺少有效的起点或终点坐标")
            return {"duration": 0, "distance": 0}
            
        # 如果是实体ID格式，需要先更新位置
        if isinstance(self.origin, str) and self.origin.startswith("entity:") or \
           isinstance(self.destination, str) and self.destination.startswith("entity:"):
            await self._update_entity_locations()
            
        # 记录请求信息
        self.logger.debug(f"请求骑行路线：起点={self.origin}, 终点={self.destination}")
        
        params = {
            "key": self.api_key,
            "from": self.origin,
            "to": self.destination,
            "output": "json"
        }

        try:
            async with self.session.get(url, params=params) as response:
                data = await response.json()
                # self.logger.debug(f"腾讯API响应：{data}")
                
                if data.get("status") == 0:
                    result = data.get("result", {})
                    routes = result.get("routes", [])
                    if routes:
                        route = routes[0]
                        duration = int(route.get("duration", 0))  # 分钟
                        distance = int(route.get("distance", 0))  # 米
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
        
        # 确保我们有有效的坐标
        if not self.origin or not self.destination:
            self.logger.error("缺少有效的起点或终点坐标")
            return {"duration": 0, "distance": 0}
            
        # 如果是实体ID格式，需要先更新位置
        if isinstance(self.origin, str) and self.origin.startswith("entity:") or \
           isinstance(self.destination, str) and self.destination.startswith("entity:"):
            await self._update_entity_locations()
            
        # 记录请求信息
        self.logger.debug(f"请求步行路线：起点={self.origin}, 终点={self.destination}")
        
        params = {
            "key": self.api_key,
            "from": self.origin,
            "to": self.destination,
            "output": "json"
        }

        try:
            async with self.session.get(url, params=params) as response:
                data = await response.json()
                # self.logger.debug(f"腾讯API响应：{data}")
                
                if data.get("status") == 0:
                    result = data.get("result", {})
                    routes = result.get("routes", [])
                    if routes:
                        route = routes[0]
                        duration = int(route.get("duration", 0))  # 分钟
                        distance = int(route.get("distance", 0))  # 米
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
