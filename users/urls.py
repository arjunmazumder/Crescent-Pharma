from django.urls import path, include
from rest_framework.routers import DefaultRouter
from users.views import UserViewSet, CustomTokenObtainPairView, CustomTokenRefreshView

router = DefaultRouter()
router.register(r'employees', UserViewSet, basename='employees')

urlpatterns = [
    path('auth/login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    path('', include(router.urls)),
]
