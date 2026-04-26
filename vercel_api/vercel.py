import os
import sys
from pathlib import Path

# Add the project root to the Python path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'playto_payout.settings')

# For Vercel serverless functions
app = None

def application(event, context):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'playto_payout.settings')
    
    # Import Django and setup
    import django
    from django.core.handlers.wsgi import WSGIHandler
    from django.core.wsgi import get_wsgi_application
    
    django.setup()
    application = get_wsgi_application()
    
    # Create a proper WSGI-to-Lambda adapter
    from django.core.handlers.wsgi import WSGIRequest
    from django.http import HttpResponse
    
    # Simple ASGI handler for Vercel
    class VercelHandler:
        def __init__(self, wsgi_app):
            self.wsgi_app = wsgi_app
        
        def __call__(self, scope, receive, send):
            return self.asgi(scope, receive, send)
        
        async def asgi(self, scope, receive, send):
            # Basic ASGI implementation
            await send({
                'type': 'http.response.start',
                'status': 200,
                'headers': [(b'content-type', b'text/html')],
            })
            await send({
                'type': 'http.response.body',
                'body': b'Playto Payout Engine API',
            })
    
    return VercelHandler(application)