"""Config flow for Tencent Commute Tracker integration."""
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_NAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
)

from .const import (
    CONF_API_KEY,
    CONF_UPDATE_INTERVAL,
    CONF_ORIGIN,
    CONF_DESTINATION,
    CONF_ORIGIN_ENTITY_ID,
    CONF_DESTINATION_ENTITY_ID,
    CONF_ORIGIN_LATITUDE,
    CONF_ORIGIN_LONGITUDE,
    CONF_DESTINATION_LATITUDE,
    CONF_DESTINATION_LONGITUDE,
    CONF_CUSTOM_NAME,
    DEFAULT_NAME,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class LocationFlowHandler:
    """Handle a location config flow."""

    def __init__(self, location_type):
        """Initialize location flow."""
        self.location_type = location_type

    async def async_step_init(self, user_input=None):
        """Handle a flow initialized by the user."""
        errors = {}
        location_key = f"{self.location_type}_location_type"

        if user_input is not None:
            location_type = user_input.get(location_key)
            
            if location_type == "entity_id":
                return await self.async_step_entity_id()
            else:
                return await self.async_step_coordinates()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        location_key, default="coordinates"
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"label": "Entity", "value": "entity_id"},
                                {"label": "Coordinates", "value": "coordinates"},
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_entity_id(self, user_input=None):
        """Handle the entity_id step."""
        errors = {}
        entity_id_key = f"{self.location_type}_entity_id"

        if user_input is not None:
            entity_id = user_input.get(entity_id_key)
            return self.async_create_entry(
                title=f"{self.location_type.capitalize()} Entity",
                data={entity_id_key: entity_id},
            )

        return self.async_show_form(
            step_id="entity_id",
            data_schema=vol.Schema(
                {
                    vol.Required(entity_id_key): EntitySelector(
                        EntitySelectorConfig(
                            domain=["device_tracker", "person", "zone"]
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_coordinates(self, user_input=None):
        """Handle the coordinates step."""
        errors = {}
        lat_key = f"{self.location_type}_latitude"
        lon_key = f"{self.location_type}_longitude"

        if user_input is not None:
            latitude = user_input.get(lat_key)
            longitude = user_input.get(lon_key)
            
            # 验证坐标格式
            try:
                lat = float(latitude)
                lon = float(longitude)
                if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                    errors["base"] = "invalid_coordinates"
            except ValueError:
                errors["base"] = "invalid_coordinates"
                
            if not errors:
                coordinates = f"{longitude},{latitude}"
                return self.async_create_entry(
                    title=f"{self.location_type.capitalize()} Coordinates",
                    data={f"{self.location_type}": coordinates},
                )

        return self.async_show_form(
            step_id="coordinates",
            data_schema=vol.Schema(
                {
                    vol.Required(lat_key): TextSelector(TextSelectorConfig()),
                    vol.Required(lon_key): TextSelector(TextSelectorConfig()),
                }
            ),
            errors=errors,
        )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tencent Commute Tracker."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # 验证API Key格式
            api_key = user_input.get(CONF_API_KEY)
            # 腾讯API Key格式：35位字符串，可能包含连字符
            if not isinstance(api_key, str) or len(api_key) != 35:
                errors["base"] = "invalid_api_key"
            elif not api_key.replace("-", "").isalnum():
                # 移除连字符后检查是否只包含字母数字
                errors["base"] = "invalid_api_key"
                

                
            # 设置默认更新间隔并验证（支持浮点数转换）
            update_interval = user_input.get(CONF_UPDATE_INTERVAL, 30)
            try:
                update_interval = int(float(update_interval))  # 兼容浮点数输入
                if update_interval < 1 or update_interval > 60:
                    raise ValueError
            except (ValueError, TypeError):
                errors["base"] = "invalid_update_interval"
                _LOGGER.warning(f"无效的更新间隔：{user_input.get(CONF_UPDATE_INTERVAL)}（必须为1-60的整数）")
                
            # 记录验证结果
            if errors:
                _LOGGER.debug(f"用户输入验证失败：{errors}")
                
            if not errors:
                # 保存用户输入的数据
                self.origin_data = user_input
                return await self.async_step_origin()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CUSTOM_NAME, default="回家"): TextSelector(TextSelectorConfig()),
                    vol.Required(CONF_API_KEY): TextSelector(TextSelectorConfig()),
                    vol.Required(CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): NumberSelector(
                        NumberSelectorConfig(min=1, max=60, step=1)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_origin(self, user_input=None):
        """Handle origin location step."""
        if user_input is not None:
            # 处理位置类型选择
            if "origin_location_type" in user_input:
                location_type = user_input["origin_location_type"]
                if location_type == "entity_id":
                    return await self.async_step_origin_entity()
                else:
                    return await self.async_step_origin_coordinates()
            
            return await self.async_step_destination()

        return self.async_show_form(
            step_id="origin",
            data_schema=vol.Schema(
                {
                    vol.Required("origin_location_type", default="coordinates"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"label": "选择实体", "value": "entity_id"},
                                {"label": "输入坐标", "value": "coordinates"},
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_origin_entity(self, user_input=None):
        """Handle origin entity selection."""
        errors = {}

        if user_input is not None:
            self.origin_entity_id = user_input.get(CONF_ORIGIN_ENTITY_ID)
            return await self.async_step_destination()

        return self.async_show_form(
            step_id="origin_entity",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ORIGIN_ENTITY_ID): EntitySelector(
                        EntitySelectorConfig(
                            domain=["device_tracker", "person", "zone"]
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_origin_coordinates(self, user_input=None):
        """Handle origin coordinates input."""
        errors = {}

        if user_input is not None:
            longitude = user_input.get(CONF_ORIGIN_LONGITUDE)
            latitude = user_input.get(CONF_ORIGIN_LATITUDE)
            
            _LOGGER.debug(f"收到起点坐标：纬度={latitude}, 经度={longitude}")
            
            try:
                lon = float(longitude)
                lat = float(latitude)
                if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                    _LOGGER.error(f"坐标超出范围：纬度={lat}, 经度={lon}")
                    errors["base"] = "invalid_coordinates"
            except ValueError:
                _LOGGER.error(f"无效的坐标格式：纬度={latitude}, 经度={longitude}")
                errors["base"] = "invalid_coordinates"
                
            if not errors:
                # 腾讯地图API使用纬度,经度的格式
                self.origin_coordinates = f"{latitude},{longitude}"
                _LOGGER.debug(f"设置起点坐标：{self.origin_coordinates}")
                return await self.async_step_destination()

        return self.async_show_form(
            step_id="origin_coordinates",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ORIGIN_LONGITUDE): TextSelector(TextSelectorConfig()),
                    vol.Required(CONF_ORIGIN_LATITUDE): TextSelector(TextSelectorConfig()),
                }
            ),
            errors=errors,
        )

    async def async_step_destination(self, user_input=None):
        """Handle destination location step."""
        if user_input is not None:
            # 处理位置类型选择
            if "destination_location_type" in user_input:
                location_type = user_input["destination_location_type"]
                if location_type == "entity_id":
                    return await self.async_step_destination_entity()
                else:
                    return await self.async_step_destination_coordinates()
            
            return await self.async_step_finish()

        return self.async_show_form(
            step_id="destination",
            data_schema=vol.Schema(
                {
                    vol.Required("destination_location_type", default="coordinates"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"label": "选择实体", "value": "entity_id"},
                                {"label": "输入坐标", "value": "coordinates"},
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_destination_entity(self, user_input=None):
        """Handle destination entity selection."""
        errors = {}

        if user_input is not None:
            self.destination_entity_id = user_input.get(CONF_DESTINATION_ENTITY_ID)
            return await self.async_step_finish()

        return self.async_show_form(
            step_id="destination_entity",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DESTINATION_ENTITY_ID): EntitySelector(
                        EntitySelectorConfig(
                            domain=["device_tracker", "person", "zone"]
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_destination_coordinates(self, user_input=None):
        """Handle destination coordinates input."""
        errors = {}

        if user_input is not None:
            longitude = user_input.get(CONF_DESTINATION_LONGITUDE)
            latitude = user_input.get(CONF_DESTINATION_LATITUDE)
            
            _LOGGER.debug(f"收到终点坐标：纬度={latitude}, 经度={longitude}")
            
            try:
                lon = float(longitude)
                lat = float(latitude)
                if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                    _LOGGER.error(f"坐标超出范围：纬度={lat}, 经度={lon}")
                    errors["base"] = "invalid_coordinates"
            except ValueError:
                _LOGGER.error(f"无效的坐标格式：纬度={latitude}, 经度={longitude}")
                errors["base"] = "invalid_coordinates"
                
            if not errors:
                # 腾讯地图API使用纬度,经度的格式
                self.destination_coordinates = f"{latitude},{longitude}"
                _LOGGER.debug(f"设置终点坐标：{self.destination_coordinates}")
                return await self.async_step_finish()

        return self.async_show_form(
            step_id="destination_coordinates",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DESTINATION_LONGITUDE): TextSelector(TextSelectorConfig()),
                    vol.Required(CONF_DESTINATION_LATITUDE): TextSelector(TextSelectorConfig()),
                }
            ),
            errors=errors,
        )

    async def async_step_finish(self, user_input=None):
        """Create the config entry."""
        # 组合所有收集的数据
        data = {}
        
        # 确保我们有第一步的数据
        if hasattr(self, "origin_data"):
            custom_name = self.origin_data.get(CONF_CUSTOM_NAME, "通勤")
            data[CONF_NAME] = DEFAULT_NAME
            data[CONF_CUSTOM_NAME] = custom_name
            data[CONF_API_KEY] = self.origin_data.get(CONF_API_KEY)
            data[CONF_UPDATE_INTERVAL] = self.origin_data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        else:
            # 如果没有第一步的数据，返回到第一步
            _LOGGER.error("缺少第一步的数据")
            return await self.async_step_user()
        
        # 处理起点数据
        if hasattr(self, "origin_entity_id"):
            data[CONF_ORIGIN_ENTITY_ID] = self.origin_entity_id
            data[CONF_ORIGIN] = f"entity:{self.origin_entity_id}"
            _LOGGER.debug(f"使用实体作为起点：{self.origin_entity_id}")
        elif hasattr(self, "origin_coordinates"):
            data[CONF_ORIGIN] = self.origin_coordinates
            _LOGGER.debug(f"使用坐标作为起点：{self.origin_coordinates}")
        else:
            # 如果没有起点数据，返回到起点步骤
            _LOGGER.error("缺少起点数据")
            return await self.async_step_origin()
            
        # 处理终点数据
        if hasattr(self, "destination_entity_id"):
            data[CONF_DESTINATION_ENTITY_ID] = self.destination_entity_id
            data[CONF_DESTINATION] = f"entity:{self.destination_entity_id}"
            _LOGGER.debug(f"使用实体作为终点：{self.destination_entity_id}")
        elif hasattr(self, "destination_coordinates"):
            data[CONF_DESTINATION] = self.destination_coordinates
            _LOGGER.debug(f"使用坐标作为终点：{self.destination_coordinates}")
        else:
            # 如果没有终点数据，返回到终点步骤
            _LOGGER.error("缺少终点数据")
            return await self.async_step_destination()

        # 确保所有必要的数据都已收集
        if CONF_API_KEY in data and CONF_ORIGIN in data and CONF_DESTINATION in data:
            _LOGGER.debug(f"创建配置项：{data}")
            return self.async_create_entry(title=DEFAULT_NAME, data=data)
        else:
            # 如果缺少必要数据，返回到第一步
            _LOGGER.error(f"缺少必要数据：{data}")
            return await self.async_step_user()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_UPDATE_INTERVAL,
                            self.config_entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                        ),
                    ): NumberSelector(NumberSelectorConfig(min=1, max=60, step=1)),
                }
            ),
        )
