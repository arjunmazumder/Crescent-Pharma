import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)

class LocationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()

        if self.channel_layer:
            try:
                await self.channel_layer.group_add(
                    "admin_room",
                    self.channel_name
                )
            except Exception as e:
                logger.warning(f"Failed to join admin_room group: {e}")

    async def disconnect(self, close_code):
        if self.channel_layer:
            try:
                await self.channel_layer.group_discard(
                    "admin_room",
                    self.channel_name
                )
            except Exception as e:
                logger.warning(f"Failed to discard admin_room group: {e}")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)

            # Auto-resolve locationName on backend if mobile didn't send it
            if not data.get('locationName') and not data.get('location_name'):
                lat = data.get('latitude') or data.get('lat')
                lon = data.get('longitude') or data.get('lon') or data.get('lng')
                if lat is not None and lon is not None:
                    from hr.services import reverse_geocode_coordinates
                    loc_name = reverse_geocode_coordinates(lat, lon)
                    if loc_name:
                        data['locationName'] = loc_name

            # Broadcast location to the admin room
            if self.channel_layer:
                await self.channel_layer.group_send(
                    "admin_room",
                    {
                        'type': 'location_message',
                        'message': data
                    }
                )
            else:
                # Echo directly if no channel layer
                await self.send(text_data=json.dumps({
                    'message': data
                }))
        except Exception as e:
            logger.warning(f"LocationConsumer receive error: {e}")

    async def location_message(self, event):
        message = event.get('message', {})
        try:
            await self.send(text_data=json.dumps({
                'message': message
            }))
        except Exception as e:
            logger.warning(f"LocationConsumer send error: {e}")

