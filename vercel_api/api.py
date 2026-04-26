import json
import os
import sys
from pathlib import Path

# Add project to path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Set Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'playto_payout.settings')

def handler(request):
    """Vercel serverless handler"""
    from django.http import JsonResponse
    from django.core.management import execute_from_command_line
    
    # Setup Django
    import django
    django.setup()
    
    # Simple health check endpoint
    if request.path == '/api/health' or request.path == '/health':
        return JsonResponse({'status': 'ok', 'service': 'playto-payout-engine'})
    
    # For other endpoints, return a message
    return JsonResponse({
        'message': 'Playto Payout Engine API',
        'endpoints': {
            'health': '/api/health',
            'merchants': '/api/v1/merchants/',
            'payouts': '/api/v1/payouts/'
        }
    })

# For Vercel Python runtime - must be named 'handler'
handler = handler

# For Vercel Python runtime
def main(request, context):
    return handler(request)