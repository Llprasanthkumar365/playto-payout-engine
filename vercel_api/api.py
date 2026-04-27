import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# Simple file-based database for Vercel deployment
DB_FILE = '/tmp/playto_db.json'

def load_db():
    """Load database from file"""
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            return json.load(f)
    return {
        'merchants': {},
        'payouts': {},
        'idempotency_keys': {},
        'ledger_entries': {}
    }

def save_db(data):
    """Save database to file"""
    with open(DB_FILE, 'w') as f:
        json.dump(data, f)

def handler(request):
    """Vercel serverless handler"""
    path = request.path
    method = request.method
    
    # CORS headers
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Idempotency-Key',
    }
    
    # Handle OPTIONS preflight
    if method == 'OPTIONS':
        return {'statusCode': 200, 'headers': headers, 'body': ''}
    
    db = load_db()
    
    # Health check
    if path in ['/api/health', '/health', '/']:
        return {
            'statusCode': 200,
            'headers': {**headers, 'Content-Type': 'application/json'},
            'body': json.dumps({
                'status': 'ok',
                'service': 'playto-payout-engine',
                'message': 'Playto Payout Engine API - Vercel Demo'
            })
        }
    
    # List merchants
    if path == '/api/v1/merchants' and method == 'GET':
        merchants = list(db['merchants'].values())
        return {
            'statusCode': 200,
            'headers': {**headers, 'Content-Type': 'application/json'},
            'body': json.dumps(merchants)
        }
    
    # Get merchant balance
    if path.startswith('/api/v1/merchants/') and path.endswith('/balance') and method == 'GET':
        merchant_id = path.split('/')[4]
        merchant = db['merchants'].get(merchant_id)
        
        if not merchant:
            return {
                'statusCode': 404,
                'headers': {**headers, 'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Merchant not found'})
            }
        
        # Calculate balance
        credits = sum(e['amount_paise'] for e in db['ledger_entries'].values() 
                     if e['merchant_id'] == merchant_id and e['entry_type'] == 'credit')
        debits = sum(e['amount_paise'] for e in db['ledger_entries'].values() 
                    if e['merchant_id'] == merchant_id and e['entry_type'] == 'debit' 
                    and e['status'] in ['pending', 'processing'])
        
        return {
            'statusCode': 200,
            'headers': {**headers, 'Content-Type': 'application/json'},
            'body': json.dumps({
                'merchant_id': merchant_id,
                'merchant_name': merchant['name'],
                'available_balance': credits - debits,
                'held_balance': debits,
                'total_credits': credits,
                'total_debits': credits - (credits - debits)
            })
        }
    
    # Create payout
    if path == '/api/v1/payouts' and method == 'POST':
        try:
            body = json.loads(request.body or '{}')
        except:
            body = {}
        
        idempotency_key = request.headers.get('Idempotency-Key', '')
        merchant_id = body.get('merchant_id')
        amount_paise = body.get('amount_paise')
        bank_account_id = body.get('bank_account_id')
        
        # Validation
        if not idempotency_key:
            return {
                'statusCode': 400,
                'headers': {**headers, 'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Idempotency-Key header required'})
            }
        
        if not all([merchant_id, amount_paise, bank_account_id]):
            return {
                'statusCode': 400,
                'headers': {**headers, 'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'merchant_id, amount_paise, and bank_account_id required'})
            }
        
        # Check idempotency
        key_id = f"{merchant_id}:{idempotency_key}"
        if key_id in db['idempotency_keys']:
            key_data = db['idempotency_keys'][key_id]
            if datetime.fromisoformat(key_data['expires_at']) > datetime.now():
                return {
                    'statusCode': 200,
                    'headers': {**headers, 'Content-Type': 'application/json'},
                    'body': json.dumps(key_data['response_data'])
                }
        
        # Check balance
        merchant = db['merchants'].get(merchant_id)
        if not merchant:
            return {
                'statusCode': 404,
                'headers': {**headers, 'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Merchant not found'})
            }
        
        credits = sum(e['amount_paise'] for e in db['ledger_entries'].values() 
                     if e['merchant_id'] == merchant_id and e['entry_type'] == 'credit')
        debits = sum(e['amount_paise'] for e in db['ledger_entries'].values() 
                    if e['merchant_id'] == merchant_id and e['entry_type'] == 'debit' 
                    and e['status'] in ['pending', 'processing'])
        available = credits - debits
        
        if available < amount_paise:
            return {
                'statusCode': 400,
                'headers': {**headers, 'Content-Type': 'application/json'},
                'body': json.dumps({
                    'error': 'Insufficient balance',
                    'available': available,
                    'requested': amount_paise
                })
            }
        
        # Create payout
        payout_id = str(uuid.uuid4())
        payout = {
            'id': payout_id,
            'merchant_id': merchant_id,
            'bank_account_id': bank_account_id,
            'amount_paise': amount_paise,
            'state': 'pending',
            'idempotency_key': idempotency_key,
            'created_at': datetime.now().isoformat()
        }
        db['payouts'][payout_id] = payout
        
        # Create ledger entry
        ledger_id = str(uuid.uuid4())
        db['ledger_entries'][ledger_id] = {
            'id': ledger_id,
            'merchant_id': merchant_id,
            'entry_type': 'debit',
            'amount_paise': amount_paise,
            'status': 'pending',
            'reference': payout_id
        }
        
        # Store idempotency key
        response_data = {
            'id': payout_id,
            'amount_paise': amount_paise,
            'state': 'pending',
            'created_at': payout['created_at']
        }
        db['idempotency_keys'][key_id] = {
            'payout_id': payout_id,
            'expires_at': (datetime.now() + timedelta(hours=24)).isoformat(),
            'response_data': response_data
        }
        
        save_db(db)
        
        return {
            'statusCode': 201,
            'headers': {**headers, 'Content-Type': 'application/json'},
            'body': json.dumps(response_data)
        }
    
    # List payouts
    if path == '/api/v1/payouts' and method == 'GET':
        merchant_id = request.query_params.get('merchant_id', '')
        payouts = [p for p in db['payouts'].values() if p['merchant_id'] == merchant_id]
        return {
            'statusCode': 200,
            'headers': {**headers, 'Content-Type': 'application/json'},
            'body': json.dumps(payouts)
        }
    
    # Seed data endpoint (for demo)
    if path == '/api/seed' and method == 'POST':
        # Create sample merchants
        merchants = [
            {'id': 'm1', 'name': 'Tech Solutions Pvt Ltd', 'email': 'tech@playto-test.in'},
            {'id': 'm2', 'name': 'Digital Agency Co', 'email': 'agency@playto-test.in'},
            {'id': 'm3', 'name': 'Freelance Developer', 'email': 'freelancer@playto-test.in'}
        ]
        for m in merchants:
            db['merchants'][m['id']] = m
            # Add credits
            for i, amount in enumerate([50000, 75000, 100000]):
                ledger_id = str(uuid.uuid4())
                db['ledger_entries'][ledger_id] = {
                    'id': ledger_id,
                    'merchant_id': m['id'],
                    'entry_type': 'credit',
                    'amount_paise': amount,
                    'status': 'completed',
                    'reference': f'PAY-{i+1}'
                }
        
        save_db(db)
        return {
            'statusCode': 200,
            'headers': {**headers, 'Content-Type': 'application/json'},
            'body': json.dumps({'message': 'Seed data created', 'merchants': len(db['merchants'])})
        }
    
    # Default response
    return {
        'statusCode': 404,
        'headers': {**headers, 'Content-Type': 'application/json'},
        'body': json.dumps({'error': 'Endpoint not found', 'path': path})
    }

# Vercel handler export
def main(request, context):
    return handler(request)