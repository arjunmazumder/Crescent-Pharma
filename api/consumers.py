import json
from channels.generic.websocket import AsyncWebsocketConsumer

class LocationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Allow connection
        await self.accept()

        await self.channel_layer.group_add(
            "admin_room",
            self.channel_name
        )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            "admin_room",
            self.channel_name
        )

    async def receive(self, text_data):
        data = json.loads(text_data)
        
        # Broadcast location to the room
        await self.channel_layer.group_send(
            "admin_room",
            {
                'type': 'location_message',
                'message': data
            }
        )

    async def location_message(self, event):
        message = event['message']
        await self.send(text_data=json.dumps({
            'message': message
        }))
