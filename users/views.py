from rest_framework import viewsets, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from drf_spectacular.utils import extend_schema, OpenApiExample
from django.contrib.auth import get_user_model
from users.serializers import UserSerializer, CustomTokenObtainPairSerializer

User = get_user_model()


@extend_schema(
    tags=['Authentication'],
    summary='User Login (Obtain JWT Access Token & User Details)',
    description='Takes username and password credentials and returns an access token and complete user profile details.',
    examples=[
        OpenApiExample(
            'Admin Login Credentials',
            summary='Admin Login',
            description='Default admin credentials for quick testing',
            value={
                'username': 'admin',
                'password': '012345678'
            },
            request_only=True
        )
    ]
)
class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


@extend_schema(
    tags=['Authentication'],
    summary='Refresh JWT Token',
    description='Takes a valid refresh token and returns a new access token.'
)
class CustomTokenRefreshView(TokenRefreshView):
    pass


@extend_schema(tags=['Users / Employees'])
class UserViewSet(viewsets.ModelViewSet):
    # The serializer renders role_permissions, extra_permissions_details and
    # effective_permissions, each of which walks a m2m. Without these
    # prefetches a page of users cost several permission queries apiece.
    queryset = User.objects.all().select_related('role').prefetch_related(
        'user_permissions__content_type', 'role__permissions__content_type'
    ).order_by('-id')
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    search_fields = ['username', 'email', 'employee_id', 'contact', 'nid_number']
    filterset_fields = ['role', 'is_active', 'is_staff', 'is_superuser', 'location_bounded_attendance']
    ordering_fields = ['id', 'username', 'employee_id', 'joining_date', 'date_of_birth']
    ordering = ['-id']

    @extend_schema(
        tags=['Users / Employees'],
        summary='Get Current User Profile',
        description='Returns profile details of the currently authenticated user.'
    )
    @action(detail=False, methods=['get'])
    def profile(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)
