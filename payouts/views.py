"""
API Views for the Playto Payout Engine.

Key features:
1. Idempotency handling with Idempotency-Key header
2. Database-level locking for concurrency control
3. State machine enforcement
"""

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db import transaction
from django.db.models import F
from django.utils import timezone
import uuid
import random

from .models import Merchant, BankAccount, LedgerEntry, Payout, IdempotencyKey
from .serializers import (
    MerchantSerializer, BankAccountSerializer, LedgerEntrySerializer,
    PayoutSerializer, PayoutResponseSerializer, MerchantBalanceSerializer
)


class MerchantListCreateView(APIView):
    """List all merchants or create a new merchant."""
    
    def get(self, request):
        merchants = Merchant.objects.all()
        serializer = MerchantSerializer(merchants, many=True)
        return Response(serializer.data)
    
    def post(self, request):
        serializer = MerchantSerializer(data=request.data)
        if serializer.is_valid():
            merchant = serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MerchantDetailView(APIView):
    """Get, update, or delete a merchant."""
    
    def get(self, request, merchant_id):
        try:
            merchant = Merchant.objects.get(id=merchant_id)
        except Merchant.DoesNotExist:
            return Response({'error': 'Merchant not found'}, status=status.HTTP_404_NOT_FOUND)
        
        serializer = MerchantSerializer(merchant)
        return Response(serializer.data)


class MerchantBalanceView(APIView):
    """Get merchant balance with ledger breakdown."""
    
    def get(self, request, merchant_id):
        try:
            merchant = Merchant.objects.get(id=merchant_id)
        except Merchant.DoesNotExist:
            return Response({'error': 'Merchant not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Calculate totals using database aggregation
        from django.db.models import Sum, Q
        
        total_credits = LedgerEntry.objects.filter(
            merchant=merchant,
            entry_type='credit'
        ).aggregate(total=Sum('amount_paise'))['total'] or 0
        
        total_debits = LedgerEntry.objects.filter(
            merchant=merchant,
            entry_type='debit'
        ).aggregate(total=Sum('amount_paise'))['total'] or 0
        
        data = {
            'merchant_id': merchant.id,
            'merchant_name': merchant.name,
            'available_balance': merchant.available_balance,
            'held_balance': merchant.held_balance,
            'total_credits': total_credits,
            'total_debits': total_debits,
        }
        
        serializer = MerchantBalanceSerializer(data)
        return Response(serializer.data)


class MerchantLedgerView(APIView):
    """Get ledger entries for a merchant."""
    
    def get(self, request, merchant_id):
        try:
            merchant = Merchant.objects.get(id=merchant_id)
        except Merchant.DoesNotExist:
            return Response({'error': 'Merchant not found'}, status=status.HTTP_404_NOT_FOUND)
        
        entry_type = request.query_params.get('entry_type')
        status_filter = request.query_params.get('status')
        
        ledger_entries = LedgerEntry.objects.filter(merchant=merchant)
        
        if entry_type:
            ledger_entries = ledger_entries.filter(entry_type=entry_type)
        if status_filter:
            ledger_entries = ledger_entries.filter(status=status_filter)
        
        serializer = LedgerEntrySerializer(ledger_entries, many=True)
        return Response(serializer.data)


class PayoutListCreateView(APIView):
    """
    Create or list payout requests.
    
    POST with Idempotency-Key header for idempotent requests.
    Uses database-level locking to prevent concurrent overdraws.
    """
    
    def get(self, request):
        """List payouts for a merchant."""
        merchant_id = request.query_params.get('merchant_id')
        
        if not merchant_id:
            return Response(
                {'error': 'merchant_id query parameter required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            merchant = Merchant.objects.get(id=merchant_id)
        except Merchant.DoesNotExist:
            return Response({'error': 'Merchant not found'}, status=status.HTTP_404_NOT_FOUND)
        
        payouts = Payout.objects.filter(merchant=merchant)
        serializer = PayoutResponseSerializer(payouts, many=True)
        return Response(serializer.data)
    
    def post(self, request):
        """
        Create a payout request with idempotency support.
        
        Idempotency-Key header is required.
        Uses select_for_update to prevent concurrent overdraws.
        """
        idempotency_key = request.headers.get('Idempotency-Key')
        
        if not idempotency_key:
            return Response(
                {'error': 'Idempotency-Key header required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        merchant_id = request.data.get('merchant_id')
        amount_paise = request.data.get('amount_paise')
        bank_account_id = request.data.get('bank_account_id')
        
        if not all([merchant_id, amount_paise, bank_account_id]):
            return Response(
                {'error': 'merchant_id, amount_paise, and bank_account_id required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            amount_paise = int(amount_paise)
        except (ValueError, TypeError):
            return Response(
                {'error': 'amount_paise must be an integer'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if amount_paise <= 0:
            return Response(
                {'error': 'amount_paise must be greater than 0'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            merchant = Merchant.objects.get(id=merchant_id)
        except Merchant.DoesNotExist:
            return Response({'error': 'Merchant not found'}, status=status.HTTP_404_NOT_FOUND)
        
        try:
            bank_account = BankAccount.objects.get(id=bank_account_id, merchant=merchant)
        except BankAccount.DoesNotExist:
            return Response({'error': 'Bank account not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Check for existing idempotency key
        existing_key = IdempotencyKey.objects.filter(
            merchant=merchant,
            key=idempotency_key
        ).first()
        
        if existing_key:
            # Check if not expired
            if existing_key.expires_at > timezone.now():
                # Return cached response
                return Response(existing_key.response_data)
            else:
                # Expired, allow retry
                existing_key.delete()
        
        # Create payout with database-level locking
        try:
            with transaction.atomic():
                # Lock merchant row to prevent concurrent modifications
                merchant = Merchant.objects.select_for_update().get(id=merchant_id)
                
                # Check available balance
                available = merchant.available_balance
                
                if available < amount_paise:
                    return Response(
                        {
                            'error': 'Insufficient balance',
                            'available': available,
                            'requested': amount_paise
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                # Create payout record
                payout = Payout.objects.create(
                    merchant=merchant,
                    bank_account=bank_account,
                    amount_paise=amount_paise,
                    state='pending',
                    idempotency_key=idempotency_key
                )
                
                # Create ledger entry (debit)
                ledger_entry = LedgerEntry.objects.create(
                    merchant=merchant,
                    entry_type='debit',
                    amount_paise=amount_paise,
                    status='pending',
                    reference=str(payout.id),
                    description=f'Payout request {payout.id}'
                )
                
                # Create idempotency key record
                expiry = timezone.now() + timezone.timedelta(hours=24)
                response_data = {
                    'id': str(payout.id),
                    'amount_paise': payout.amount_paise,
                    'state': payout.state,
                    'created_at': payout.created_at.isoformat(),
                    'bank_account': {
                        'id': str(bank_account.id),
                        'bank_name': bank_account.bank_name,
                        'account_holder_name': bank_account.account_holder_name,
                    }
                }
                
                IdempotencyKey.objects.create(
                    merchant=merchant,
                    key=idempotency_key,
                    payout=payout,
                    response_data=response_data,
                    expires_at=expiry
                )
                
                return Response(response_data, status=status.HTTP_201_CREATED)
                
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_BAD_REQUEST
            )


class PayoutDetailView(APIView):
    """Get payout details."""
    
    def get(self, request, payout_id):
        try:
            payout = Payout.objects.get(id=payout_id)
        except Payout.DoesNotExist:
            return Response({'error': 'Payout not found'}, status=status.HTTP_404_NOT_FOUND)
        
        serializer = PayoutResponseSerializer(payout)
        return Response(serializer.data)


class BankAccountListCreateView(APIView):
    """List or create bank accounts for a merchant."""
    
    def get(self, request):
        merchant_id = request.query_params.get('merchant_id')
        
        if not merchant_id:
            return Response(
                {'error': 'merchant_id query parameter required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            merchant = Merchant.objects.get(id=merchant_id)
        except Merchant.DoesNotExist:
            return Response({'error': 'Merchant not found'}, status=status.HTTP_404_NOT_FOUND)
        
        accounts = BankAccount.objects.filter(merchant=merchant)
        serializer = BankAccountSerializer(accounts, many=True)
        return Response(serializer.data)
    
    def post(self, request):
        merchant_id = request.data.get('merchant_id')
        
        if not merchant_id:
            return Response(
                {'error': 'merchant_id required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            merchant = Merchant.objects.get(id=merchant_id)
        except Merchant.DoesNotExist:
            return Response({'error': 'Merchant not found'}, status=status.HTTP_404_NOT_FOUND)
        
        serializer = BankAccountSerializer(data=request.data)
        if serializer.is_valid():
            account = serializer.save(merchant=merchant)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)