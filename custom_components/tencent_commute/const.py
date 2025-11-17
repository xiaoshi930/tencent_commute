"""Constants for the tencent_commute Tracker integration."""

DOMAIN = "tencent_commute"

CONF_API_KEY = "api_key"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_ORIGIN = "origin"
CONF_DESTINATION = "destination"
CONF_ORIGIN_ENTITY_ID = "origin_entity_id"
CONF_DESTINATION_ENTITY_ID = "destination_entity_id"
CONF_ORIGIN_LATITUDE = "origin_latitude"
CONF_ORIGIN_LONGITUDE = "origin_longitude"
CONF_DESTINATION_LATITUDE = "destination_latitude"
CONF_DESTINATION_LONGITUDE = "destination_longitude"
CONF_CUSTOM_NAME = "custom_name"

DEFAULT_NAME = "tencent_commute"
DEFAULT_UPDATE_INTERVAL = 30

ATTR_DRIVING_DURATION = "驾车通勤时间"
ATTR_DRIVING_DISTANCE = "驾车通勤距离"
ATTR_TRANSIT_DURATION = "公交通勤时间"
ATTR_TRANSIT_DISTANCE = "公交通勤距离"
ATTR_BICYCLING_DURATION = "骑行通勤时间"
ATTR_BICYCLING_DISTANCE = "骑行通勤距离"
ATTR_WALKING_DURATION = "步行通勤时间"
ATTR_WALKING_DISTANCE = "步行通勤距离"

COORDINATOR = "coordinator"
