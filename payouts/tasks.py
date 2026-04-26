"""
Background tasks for payout processing.

Uses Django-Q for async job processing.
Simulates bank settlement: 70% success, 20% fail, 10% hang.
"""

import random
import time
from django_q import Task
from django.utils import timezone
from django.db import transaction
from django.conf import settings

from .models import Payout, LedgerEntry


def process_payout(payout_id):
    """
    Process a payout: pending -> processing -> completed/failed.
    
    Simulates bank settlement:
    - 70% succeed
    - 20% fail
    - 10% hang (stuck in processing)
    """
    try:
        payout = Payout.objects.get(id=payout_id)
    except Payout.DoesNotExist:
        return {'error': 'Payout not found'}
    
    # Move to processing state
    payout.state = 'processing'
    payout.save()
    
    # Simulate processing time
    time.sleep(1)
    
    # Determine outcome based on configured rates
    rand = random.random()
    
    if rand < settings.PAYOUT_SUCCESS_RATE:
        # Success case
        return complete_payout(payout)
    elif rand < settings.PAYOUT_SUCCESS_RATE + settings.PAYOUT_FAIL_RATE:
        # Failure case
        return fail_payout(payout)
    else:
        # Hang case - will be retried by retry logic
        payout.error_message = 'Bank settlement pending'
        payout.save()
        return {'status': 'pending_retry', 'message': 'Payout stuck in processing'}


def complete_payout(payout):
    """
    Mark payout as completed.
    """
    with transaction.atomic():
        # Update payout state
        payout.state = 'completed'
        payout.processed_at = timezone.now()
        payout.save()
        
        # Update ledger entry
        LedgerEntry.objects.filter(
            reference=str(payout.id),
            entry_type='debit'
        ).update(status='completed')
    
    return {
        'status': 'completed',
        'payout_id': str(payout.id),
        'amount_paise': payout.amount_paise
    }


def fail_payout(payout):
    """
    Mark payout as failed and return funds to merchant.
    """
    with transaction.atomic():
        # Update payout state
        payout.state = 'failed'
        payout.error_message = 'Bank settlement failed'
        payout.processed_at = timezone.now()
        payout.save()
        
        # Update ledger entry to failed
        LedgerEntry.objects.filter(
            reference=str(payout.id),
            entry_type='debit'
        ).update(status='failed')
        
        # Create reversal credit to return funds
        LedgerEntry.objects.create(
            merchant=payout.merchant,
            entry_type='credit',
            amount_paise=payout.amount_paise,
            status='completed',
            reference=f'reversal-{payout.id}',
            description=f'Funds returned from failed payout {payout.id}'
        )
    
    return {
        'status': 'failed',
        'payout_id': str(payout.id),
        'amount_paise': payout.amount_paise,
        'funds_returned': True
    }


def retry_stuck_payouts():
    """
    Retry payouts stuck in processing for more than 30 seconds.
    Uses exponential backoff with max 3 attempts.
    """
    from django.conf import settings
    
    timeout = settings.PAYOUT_PROCESSING_TIMEOUT
    max_retries = settings.PAYOUT_MAX_RETRIES
    
    stuck_payouts = Payout.objects.filter(
        state='processing',
        updated_at__lt=timezone.now() - timezone.timedelta(seconds=timeout)
    )
    
    results = []
    
    for payout in stuck_payouts:
        if payout.retry_count >= max_retries:
            # Max retries exceeded, mark as failed
            payout.state = 'failed'
            payout.error_message = 'Max retries exceeded'
            payout.save()
            
            # Return funds
            LedgerEntry.objects.filter(
                reference=str(payout.id),
                entry_type='debit'
            ).update(status='failed')
            
            LedgerEntry.objects.create(
                merchant=payout.merchant,
                entry_type='credit',
                amount_paise=payout.amount_paise,
                status='completed',
                reference=f'reversal-{payout.id}',
                description=f'Funds returned after max retries for payout {payout.id}'
            )
            
            results.append({
                'payout_id': str(payout.id),
                'action': 'failed_max_retries'
            })
        else:
            # Increment retry count and reprocess
            payout.retry_count += 1
            payout.save()
            
            # Re-queue for processing
            from django_q import async_task
            async_task('payouts.tasks.process_payout', payout.id)
            
            results.append({
                'payout_id': str(payout.id),
                'action': 'retry',
                'retry_count': payout.retry_count
            })
    
    return {
        'processed': len(results),
        'results': results
    }


def schedule_pending_payouts():
    """
    Schedule pending payouts for processing.
    Called periodically to pick up new payouts.
    """
    pending_payouts = Payout.objects.filter(state='pending')
    
    from django_q import async_task
    
    for payout in pending_payouts:
        async_task('payouts.tasks.process_payout', payout.id)
    
    return {
        'scheduled': len(pending_payouts)
    }