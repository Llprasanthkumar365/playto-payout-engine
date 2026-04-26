"""
Tests for the Playto Payout Engine.

Required tests:
1. Concurrency test - ensures only one payout succeeds when balance is insufficient for multiple
2. Idempotency test - ensures same response when called twice with same idempotency key
"""

from django.test import TestCase
from django.db import transaction
from django.utils import timezone
from unittest.mock import patch, MagicMock
import uuid
import threading
import time

from payouts.models import Merchant, BankAccount, LedgerEntry, Payout, IdempotencyKey


class ConcurrencyTestCase(TestCase):
    """Test concurrent payout requests."""
    
    def setUp(self):
        """Set up test data."""
        # Create merchant
        self.merchant = Merchant.objects.create(
            name='Test Merchant',
            email='test@example.com'
        )
        
        # Create bank account
        self.bank_account = BankAccount.objects.create(
            merchant=self.merchant,
            account_number='1234567890',
            ifsc_code='HDFC0001234',
            bank_name='HDFC Bank',
            account_holder_name='Test Merchant',
            is_verified=True
        )
        
        # Create credit ledger entry (₹100)
        LedgerEntry.objects.create(
            merchant=self.merchant,
            entry_type='credit',
            amount_paise=10000,
            status='completed',
            reference='TEST-PAY-001',
            description='Test credit'
        )
    
    def test_concurrent_payouts_only_one_succeeds(self):
        """
        Test that when a merchant with ₹100 balance submits two 
        simultaneous ₹60 payout requests, exactly one succeeds.
        
        This tests the database-level locking prevents race conditions.
        """
        from payouts.views import PayoutListCreateView
        from rest_framework.test import APIRequestFactory
        
        factory = APIRequestFactory()
        
        # Create two simultaneous payout requests
        results = []
        errors = []
        
        def create_payout(amount):
            try:
                request = factory.post('/api/v1/payouts', {
                    'merchant_id': str(self.merchant.id),
                    'amount_paise': amount,
                    'bank_account_id': str(self.bank_account.id),
                }, format='json')
                request.META['HTTP_IDEMPOTENCY_KEY'] = str(uuid.uuid4())
                
                view = PayoutListCreateView.as_view()
                response = view(request)
                results.append({
                    'status': response.status_code,
                    'data': response.data
                })
            except Exception as e:
                errors.append(str(e))
        
        # Run both requests concurrently using threads
        threads = []
        for amount in [6000, 6000]:  # Both ₹60
            t = threading.Thread(target=create_payout, args=(amount,))
            threads.append(t)
        
        # Start both threads at approximately the same time
        for t in threads:
            t.start()
        
        # Wait for both to complete
        for t in threads:
            t.join()
        
        # Analyze results
        success_count = sum(1 for r in results if r['status'] == 201)
        error_count = sum(1 for r in results if r['status'] == 400)
        
        # Exactly one should succeed, one should fail with insufficient balance
        self.assertEqual(success_count, 1, f"Expected exactly 1 success, got {success_count}")
        self.assertEqual(error_count, 1, f"Expected exactly 1 error, got {error_count}")
        
        # Verify the error is about insufficient balance
        error_result = next(r for r in results if r['status'] == 400)
        self.assertIn('Insufficient balance', str(error_result['data']))
    
    def test_concurrent_payouts_with_sufficient_balance(self):
        """
        Test that when merchant has sufficient balance, both payouts can succeed
        if there's enough for both.
        """
        from payouts.views import PayoutListCreateView
        from rest_framework.test import APIRequestFactory
        
        factory = APIRequestFactory()
        
        # Add more credit
        LedgerEntry.objects.create(
            merchant=self.merchant,
            entry_type='credit',
            amount_paise=10000,
            status='completed',
            reference='TEST-PAY-002',
            description='Test credit 2'
        )
        
        results = []
        
        def create_payout(amount, idempotency_key):
            try:
                request = factory.post('/api/v1/payouts', {
                    'merchant_id': str(self.merchant.id),
                    'amount_paise': amount,
                    'bank_account_id': str(self.bank_account.id),
                }, format='json')
                request.META['HTTP_IDEMPOTENCY_KEY'] = idempotency_key
                
                view = PayoutListCreateView.as_view()
                response = view(request)
                results.append({
                    'status': response.status_code,
                    'data': response.data
                })
            except Exception as e:
                results.append({'status': 500, 'error': str(e)})
        
        # Run both requests concurrently
        threads = []
        for amount, key in [(5000, str(uuid.uuid4())), (5000, str(uuid.uuid4()))]:
            t = threading.Thread(target=create_payout, args=(amount, key))
            threads.append(t)
        
        for t in threads:
            t.start()
        
        for t in threads:
            t.join()
        
        # Both should succeed since total (₹100) >= request (₹50 + ₹50)
        success_count = sum(1 for r in results if r['status'] == 201)
        self.assertEqual(success_count, 2)


class IdempotencyTestCase(TestCase):
    """Test idempotency of payout requests."""
    
    def setUp(self):
        """Set up test data."""
        self.merchant = Merchant.objects.create(
            name='Test Merchant',
            email='idempotency@example.com'
        )
        
        self.bank_account = BankAccount.objects.create(
            merchant=self.merchant,
            account_number='9876543210',
            ifsc_code='SBIN0001234',
            bank_name='State Bank of India',
            account_holder_name='Test Merchant',
            is_verified=True
        )
        
        # Add credit
        LedgerEntry.objects.create(
            merchant=self.merchant,
            entry_type='credit',
            amount_paise=50000,
            status='completed',
            reference='IDEM-PAY-001',
            description='Test credit'
        )
    
    def test_idempotent_request_returns_same_response(self):
        """
        Test that calling the same payout request twice with the same
        idempotency key returns the exact same response both times.
        """
        from payouts.views import PayoutListCreateView
        from rest_framework.test import APIRequestFactory
        
        factory = APIRequestFactory()
        idempotency_key = str(uuid.uuid4())
        
        # First request
        request1 = factory.post('/api/v1/payouts', {
            'merchant_id': str(self.merchant.id),
            'amount_paise': 5000,
            'bank_account_id': str(self.bank_account.id),
        }, format='json')
        request1.META['HTTP_IDEMPOTENCY_KEY'] = idempotency_key
        
        view = PayoutListCreateView.as_view()
        response1 = view(request1)
        
        # Second request with same idempotency key
        request2 = factory.post('/api/v1/payouts', {
            'merchant_id': str(self.merchant.id),
            'amount_paise': 5000,
            'bank_account_id': str(self.bank_account.id),
        }, format='json')
        request2.META['HTTP_IDEMPOTENCY_KEY'] = idempotency_key
        
        response2 = view(request2)
        
        # Both should return 201
        self.assertEqual(response1.status_code, 201)
        self.assertEqual(response2.status_code, 201)
        
        # Both should have the same payout ID
        self.assertEqual(response1.data['id'], response2.data['id'])
        
        # Verify only one payout was created
        payout_count = Payout.objects.filter(
            merchant=self.merchant,
            idempotency_key=idempotency_key
        ).count()
        
        self.assertEqual(payout_count, 1, "Expected exactly 1 payout to be created")
    
    def test_different_idempotency_keys_create_different_payouts(self):
        """
        Test that different idempotency keys create different payouts.
        """
        from payouts.views import PayoutListCreateView
        from rest_framework.test import APIRequestFactory
        
        factory = APIRequestFactory()
        
        # First request with key 1
        request1 = factory.post('/api/v1/payouts', {
            'merchant_id': str(self.merchant.id),
            'amount_paise': 5000,
            'bank_account_id': str(self.bank_account.id),
        }, format='json')
        request1.META['HTTP_IDEMPOTENCY_KEY'] = str(uuid.uuid4())
        
        view = PayoutListCreateView.as_view()
        response1 = view(request1)
        
        # Second request with different key
        request2 = factory.post('/api/v1/payouts', {
            'merchant_id': str(self.merchant.id),
            'amount_paise': 5000,
            'bank_account_id': str(self.bank_account.id),
        }, format='json')
        request2.META['HTTP_IDEMPOTENCY_KEY'] = str(uuid.uuid4())
        
        response2 = view(request2)
        
        # Both should succeed
        self.assertEqual(response1.status_code, 201)
        self.assertEqual(response2.status_code, 201)
        
        # Should have different IDs
        self.assertNotEqual(response1.data['id'], response2.data['id'])
        
        # Should have 2 payouts
        payout_count = Payout.objects.filter(merchant=self.merchant).count()
        self.assertEqual(payout_count, 2)
    
    def test_idempotency_key_scoped_per_merchant(self):
        """
        Test that idempotency keys are scoped per merchant.
        Same key for different merchants should create separate payouts.
        """
        # Create second merchant
        merchant2 = Merchant.objects.create(
            name='Test Merchant 2',
            email='idempotency2@example.com'
        )
        
        bank_account2 = BankAccount.objects.create(
            merchant=merchant2,
            account_number='1111111111',
            ifsc_code='ICICI0001234',
            bank_name='ICICI Bank',
            account_holder_name='Test Merchant 2',
            is_verified=True
        )
        
        # Add credit to merchant2
        LedgerEntry.objects.create(
            merchant=merchant2,
            entry_type='credit',
            amount_paise=50000,
            status='completed',
            reference='IDEM-PAY-002',
            description='Test credit'
        )
        
        from payouts.views import PayoutListCreateView
        from rest_framework.test import APIRequestFactory
        
        factory = APIRequestFactory()
        same_key = str(uuid.uuid4())  # Same key for both merchants
        
        # Request from merchant 1
        request1 = factory.post('/api/v1/payouts', {
            'merchant_id': str(self.merchant.id),
            'amount_paise': 5000,
            'bank_account_id': str(self.bank_account.id),
        }, format='json')
        request1.META['HTTP_IDEMPOTENCY_KEY'] = same_key
        
        view = PayoutListCreateView.as_view()
        response1 = view(request1)
        
        # Request from merchant 2 with same key
        request2 = factory.post('/api/v1/payouts', {
            'merchant_id': str(merchant2.id),
            'amount_paise': 5000,
            'bank_account_id': str(bank_account2.id),
        }, format='json')
        request2.META['HTTP_IDEMPOTENCY_KEY'] = same_key
        
        response2 = view(request2)
        
        # Both should succeed (different merchants can use same key)
        self.assertEqual(response1.status_code, 201)
        self.assertEqual(response2.status_code, 201)
        
        # Should have 2 different payouts
        self.assertNotEqual(response1.data['id'], response2.data['id'])


class StateMachineTestCase(TestCase):
    """Test state machine transitions."""
    
    def setUp(self):
        """Set up test data."""
        self.merchant = Merchant.objects.create(
            name='State Test Merchant',
            email='state@example.com'
        )
        
        self.bank_account = BankAccount.objects.create(
            merchant=self.merchant,
            account_number='1234567890',
            ifsc_code='HDFC0001234',
            bank_name='HDFC Bank',
            account_holder_name='State Test Merchant',
            is_verified=True
        )
        
        LedgerEntry.objects.create(
            merchant=self.merchant,
            entry_type='credit',
            amount_paise=50000,
            status='completed',
            reference='STATE-PAY-001',
            description='Test credit'
        )
    
    def test_illegal_state_transition_blocked(self):
        """
        Test that illegal state transitions are blocked.
        e.g., completed -> pending should fail.
        """
        from payouts.views import PayoutListCreateView
        from rest_framework.test import APIRequestFactory
        
        factory = APIRequestFactory()
        
        # Create a payout
        request = factory.post('/api/v1/payouts', {
            'merchant_id': str(self.merchant.id),
            'amount_paise': 5000,
            'bank_account_id': str(self.bank_account.id),
        }, format='json')
        request.META['HTTP_IDEMPOTENCY_KEY'] = str(uuid.uuid4())
        
        view = PayoutListCreateView.as_view()
        response = view(request)
        
        payout = Payout.objects.get(id=response.data['id'])
        
        # Try to directly set to completed (illegal from pending)
        payout.state = 'completed'
        
        # This should be blocked by the model's save() method
        with self.assertRaises(ValueError) as context:
            payout.save()
        
        self.assertIn('Illegal state transition', str(context.exception))
    
    def test_legal_state_transitions(self):
        """
        Test that legal state transitions are allowed.
        """
        from payouts.views import PayoutListCreateView
        from rest_framework.test import APIRequestFactory
        
        factory = APIRequestFactory()
        
        # Create a payout
        request = factory.post('/api/v1/payouts', {
            'merchant_id': str(self.merchant.id),
            'amount_paise': 5000,
            'bank_account_id': str(self.bank_account.id),
        }, format='json')
        request.META['HTTP_IDEMPOTENCY_KEY'] = str(uuid.uuid4())
        
        view = PayoutListCreateView.as_view()
        response = view(request)
        
        payout = Payout.objects.get(id=response.data['id'])
        
        # Legal: pending -> processing
        payout.state = 'processing'
        payout.save()
        
        self.assertEqual(payout.state, 'processing')
        
        # Legal: processing -> completed
        payout.state = 'completed'
        payout.save()
        
        self.assertEqual(payout.state, 'completed')


class BalanceIntegrityTestCase(TestCase):
    """Test balance calculation integrity."""
    
    def test_balance_equals_credits_minus_debits(self):
        """
        Test that balance = credits - debits (for non-failed debits).
        This is the core invariant we check.
        """
        merchant = Merchant.objects.create(
            name='Balance Test Merchant',
            email='balance@example.com'
        )
        
        # Create credits
        LedgerEntry.objects.create(
            merchant=merchant,
            entry_type='credit',
            amount_paise=100000,  # ₹1000
            status='completed',
            reference='BAL-CREDIT-001',
            description='Credit 1'
        )
        
        LedgerEntry.objects.create(
            merchant=merchant,
            entry_type='credit',
            amount_paise=50000,  # ₹500
            status='completed',
            reference='BAL-CREDIT-002',
            description='Credit 2'
        )
        
        # Create debits (pending)
        LedgerEntry.objects.create(
            merchant=merchant,
            entry_type='debit',
            amount_paise=30000,  # ₹300
            status='pending',
            reference='BAL-DEBIT-001',
            description='Debit 1'
        )
        
        # Calculate expected balance
        total_credits = 150000  # 1000 + 500
        total_debits = 30000    # pending only
        expected_balance = total_credits - total_debits
        
        # Get actual balance
        actual_balance = merchant.available_balance
        
        self.assertEqual(actual_balance, expected_balance)
        
        # Now complete the debit
        LedgerEntry.objects.filter(reference='BAL-DEBIT-001').update(status='completed')
        
        # Refresh merchant
        merchant.refresh_from_db()
        
        # New balance should be different
        new_balance = merchant.available_balance
        self.assertEqual(new_balance, 120000)  # 150000 - 30000