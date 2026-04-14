import time
from .models import ActivityLog

class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. Start the timer
        start_time = time.time()

        # 2. Process the actual request and get the response
        response = self.get_response(request)

        # 3. Stop the timer and calculate load time
        execution_time = time.time() - start_time

        # 4. Skip logging for static, media, and the admin panel
        if (
            request.path.startswith('/static/') or 
            request.path.startswith('/media/') or 
            request.path.startswith('/admin/') or  # <--- CHANGED THIS LINE
            request.path == '/favicon.ico'
        ):
            return response

        # 5. Extract User and IP Address
        user = request.user if request.user.is_authenticated else None
        
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')

        # 6. Determine the log level based on the HTTP Status Code
        level = 'INFO'
        if 400 <= response.status_code < 500:
            level = 'WARNING'
        elif response.status_code >= 500:
            level = 'ERROR'

        # 7. Save to the database
        ActivityLog.objects.create(
            user=user,
            level=level,
            ip_address=ip,
            path=request.path,
            method=request.method,
            status_code=response.status_code,
            message=f"Page loaded in {execution_time:.3f}s"
        )

        return response