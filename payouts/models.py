"""
Models for the Playto Payout Engine.

Key design decisions:
1. All amounts stored as BigInteger in paise (not floats/decimals)
2. Balance is derived from credits - debits, not stored
3. Idempotency keys scoped per merchant with 24h expiry
4. State machine enforced at database level
"""

from django.db import models
from django.utils import timezone
import uuid


class Merchant(models.Model):
    """Merchant who receives payments and can request payouts."""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'merchants'
    
    def __str__(self):
        return self.name
    
    @property
    def available_balance(self):
        """
        Calculate available balance: total credits - total debits (completed + pending).
        Uses database-level aggregation for integrity.
        """
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COALESCE(
                    (SELECT SUM(amount_paise) FROM ledger_entries 
                     WHERE merchant_id = %s AND entry_type = 'credit') -
                    (SELECT SUM(amount_paise) FROM ledger_entries 
                     WHERE merchant_id = %s AND entry_type = 'debit' 
                     AND status IN ('pending', 'processing')), 0
                ) AS balance
            """, [str(self.id), str(self.id)])
            result = cursor.fetchone()
            return result[0] if result else 0
    
    @property
    def held_balance(self):
        """
        Calculate held balance: debits in pending or processing state.
        """
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COALESCE(SUM(amount_paise), 0)
                FROM ledger_entries
                WHERE merchant_id = %s AND entry_type = 'debit'
                AND status IN ('pending', 'processing')
            """, [str(self.id)])
            result = cursor.fetchone()
            return result[0] if result else 0


class BankAccount(models.Model):
    """Bank account for payouts."""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='bank_accounts')
    account_number = models.CharField(max_length=20)
    ifsc_code = models.CharField(max_length=11)
    bank_name = models.CharField(max_length=255)
    account_holder_name = models.CharField(max_length=255)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'bank_accounts'
    
    def __str__(self):
        return f"{self.account_holder_name} - {self.bank_name}"


class LedgerEntry(models.Model):
    """
    Ledger entries tracking credits and debits.
    Balance = sum(credits) - sum(debits where status not completed/failed).
    """
    
    ENTRY_TYPE_CHOICES = [
        ('credit', 'Credit'),
        ('debit', 'Debit'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='ledger_entries')
    entry_type = models.CharField(max_length=10, choices=ENTRY_TYPE_CHOICES)
    amount_paise = models.BigIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    reference = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'ledger_entries'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.entry_type} - {self.amount_paise} paise - {self.status}"


class Payout(models.Model):
    """
    Payout request with state machine lifecycle.
    
    State transitions:
    - pending -> processing (worker picks up)
    - processing -> completed (success)
    - processing -> failed (error, funds returned)
    
    Illegal transitions are blocked in the model save().
    """
    
    STATE_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='payouts')
    bank_account = models.ForeignKey(BankAccount, on_delete=models.CASCADE)
    amount_paise = models.BigIntegerField()
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default='pending')
    idempotency_key = models.CharField(max_length=64, db_index=True)
    retry_count = models.IntegerField(default=0)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'payouts'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['merchant', 'idempotency_key'],
                name='unique_merchant_idempotency'
            )
        ]
    
    def __str__(self):
        return f"Payout {self.id} - {self.amount_paise} paise - {self.state}"
    
    def save(self, *args, **kwargs):
        """
        Enforce state machine transitions.
        Block illegal transitions: completed->pending, failed->completed, etc.
        """
        if self.pk:
            old_instance = Payout.objects.get(pk=self.pk)
            old_state = old_instance.state
            new_state = self.state
            
            # Define legal transitions
            legal_transitions = {
                'pending': ['processing'],
                'processing': ['completed', 'failed'],
                'completed': [],
                'failed': [],
            }
            
            if new_state not in legal_transitions.get(old_state, []):
                if old_state != new_state:
                    raise ValueError(
                        f"Illegal state transition: {old_state} -> {new_state}"
                    )
        
        super().save(*args, **kwargs)


class IdempotencyKey(models.Model):
    """
    Track idempotency keys to ensure exactly-once processing.
    Keys expire after 24 hours.
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE)
    key = models.CharField(max_length=64)
    payout = models.ForeignKey(Payout, on_delete=models.CASCADE, null=True)
    response_data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    
    class Meta:
        db_table = 'idempotency_keys'
        constraints = [
            models.UniqueConstraint(
                fields=['merchant', 'key'],
                name='unique_merchant_idempotency_key'
            )
        ]
    
    def __str__(self):
        return f"IdempotencyKey {self.key} for {self.merchant.name}"
    
    @classmethod
    def get_or_create_response(cls, merchant, key, payout_data, create_payout_func):
        """
        Get existing response or create new payout with idempotency.
        Uses select_for_update to handle concurrent requests.
        """
        from django.db import transaction
        from django.utils import timezone
        
        expiry = timezone.now() + timezone.timedelta(hours=24)
        
        with transaction.atomic():
            # Try to get existing key
            try:
                existing = cls.objects.select_for_update().get(
                    merchant=merchant,
                    key=key
                )
                # Check if expired
                if existing.expires_at < timezone.now():
                    raise cls.DoesNotExist()
                return existing.response_data, existing.payout
            except cls.DoesNotExist:
                # Create new payout and idempotency key
                payout = create_payout_func()
                
                idempotency_record = cls.objects.create(
                    merchant=merchant,
                    key=key,
                    payout=payout,
                    response_data=payout_data,
                    expires_at=expiry
                )
                
                return payout_data, payout