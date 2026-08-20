from django.urls import path, include

urlpatterns = [
    path('', include('users.urls')),
    path('', include('core.urls')),
    path('', include('hr.urls')),
    path('', include('inventory.urls')),
    path('', include('sales.urls')),
    path('', include('marketing.urls')),
    path('', include('accounting.urls')),
]
