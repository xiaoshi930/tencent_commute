"""Sensor platform for Tencent Commute Tracker integration."""
from datetime import datetime
import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_DRIVING_DISTANCE,
    ATTR_DRIVING_DURATION,
    ATTR_TRANSIT_DISTANCE,
    ATTR_TRANSIT_DURATION,
    ATTR_BICYCLING_DISTANCE,
    ATTR_BICYCLING_DURATION,
    ATTR_WALKING_DISTANCE,
    ATTR_WALKING_DURATION,
    COORDINATOR,
    DEFAULT_NAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Tencent Commute Tracker sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    
    # 检查配置是否有效
    if not coordinator.data:
        _LOGGER.error("无法初始化传感器：协调器数据为空")
        return
        
    async_add_entities([TencentCommuteSensor(coordinator, entry)])


class TencentCommuteSensor(CoordinatorEntity, SensorEntity):
    """Implementation of a Tencent Commute Tracker sensor."""

    def __init__(self, coordinator, entry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        
        # 使用自定义名称
        custom_name = entry.data.get("custom_name", "通勤")
        self._attr_name = f"{custom_name}通勤"
        
        # 使用拼音作为实体ID
        from pypinyin import lazy_pinyin
        pinyin = ''.join(lazy_pinyin(custom_name))
        self.entity_id = f"sensor.tencent_{pinyin}"
        
        # 设置设备信息
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"腾讯通勤 - {custom_name}",
            "manufacturer": "腾讯",
        }
        
        self._attr_unique_id = f"{entry.entry_id}"
        self._attr_available = False  # 初始状态设为不可用

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if not self.coordinator.data:
            self._attr_available = False
            return None
            
        # 返回驾车通勤时间（分钟）
        driving_data = self.coordinator.data.get("driving", {})
        driving_duration_minutes = driving_data.get("duration", 0)
        
        # 如果数据无效，标记为不可用
        if driving_duration_minutes <= 0:
            self._attr_available = False
            return None
            
        self._attr_available = True
        return driving_duration_minutes

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        if not self.coordinator.data:
            return {}
            
        driving_data = self.coordinator.data.get("driving", {})
        transit_data = self.coordinator.data.get("transit", {})
        bicycling_data = self.coordinator.data.get("bicycling", {})
        walking_data = self.coordinator.data.get("walking", {})
        
        # 驾车通勤时间（分钟）
        driving_duration_minutes = driving_data.get("duration", 0)
        
        # 公交通勤时间（分钟）
        transit_duration_minutes = transit_data.get("duration", 0)
        
        # 骑行通勤时间（分钟）
        bicycling_duration_minutes = bicycling_data.get("duration", 0)
        
        # 步行通勤时间（分钟）
        walking_duration_minutes = walking_data.get("duration", 0)
        
        # 驾车通勤距离（米转公里）
        driving_distance_meters = driving_data.get("distance", 0)
        driving_distance_km = driving_distance_meters / 1000
        
        # 公交通勤距离（米转公里）
        transit_distance_meters = transit_data.get("distance", 0)
        transit_distance_km = transit_distance_meters / 1000
        
        # 骑行通勤距离（米转公里）
        bicycling_distance_meters = bicycling_data.get("distance", 0)
        bicycling_distance_km = bicycling_distance_meters / 1000
        
        # 步行通勤距离（米转公里）
        walking_distance_meters = walking_data.get("distance", 0)
        walking_distance_km = walking_distance_meters / 1000
        
        # 格式化显示
        if driving_duration_minutes <= 0:
            driving_duration_display = "未知"
        elif driving_duration_minutes > 120:  # 大于2小时
            driving_duration_display = f"{driving_duration_minutes / 60:.2f}小时"
        else:
            driving_duration_display = f"{int(driving_duration_minutes)}分钟"
            
        if transit_duration_minutes <= 0:
            transit_duration_display = "未知"
        elif transit_duration_minutes > 120:  # 大于2小时
            transit_duration_display = f"{transit_duration_minutes / 60:.2f}小时"
        else:
            transit_duration_display = f"{int(transit_duration_minutes)}分钟"
            
        if bicycling_duration_minutes <= 0:
            bicycling_duration_display = "未知"
        elif bicycling_duration_minutes > 120:  # 大于2小时
            bicycling_duration_display = f"{bicycling_duration_minutes / 60:.2f}小时"
        else:
            bicycling_duration_display = f"{int(bicycling_duration_minutes)}分钟"
            
        if walking_duration_minutes <= 0:
            walking_duration_display = "未知"
        elif walking_duration_minutes > 120:  # 大于2小时
            walking_duration_display = f"{walking_duration_minutes / 60:.2f}小时"
        else:
            walking_duration_display = f"{int(walking_duration_minutes)}分钟"
        
        # 处理无效距离
        driving_distance_display = "未知" if driving_distance_meters <= 0 else f"{driving_distance_km:.1f}公里"
        transit_distance_display = "未知" if transit_distance_meters <= 0 else f"{transit_distance_km:.1f}公里"
        bicycling_distance_display = "未知" if bicycling_distance_meters <= 0 else f"{bicycling_distance_km:.1f}公里"
        walking_distance_display = "未知" if walking_distance_meters <= 0 else f"{walking_distance_km:.1f}公里"
        
        return {
            ATTR_DRIVING_DURATION: driving_duration_display,
            ATTR_DRIVING_DISTANCE: driving_distance_display,
            ATTR_TRANSIT_DURATION: transit_duration_display,
            ATTR_TRANSIT_DISTANCE: transit_distance_display,
            ATTR_BICYCLING_DURATION: bicycling_duration_display,
            ATTR_BICYCLING_DISTANCE: bicycling_distance_display,
            ATTR_WALKING_DURATION: walking_duration_display,
            ATTR_WALKING_DISTANCE: walking_distance_display,
        }

    @property
    def icon(self):
        """Return the icon of the sensor."""
        if not self._attr_available:
            return "mdi:car-off"
        return "mdi:car-clock"
