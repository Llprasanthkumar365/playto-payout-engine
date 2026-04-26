# EXPLAINER.md - Playto Payout Engine

This document explains the key architectural decisions in the Playto Payout Engine.

---

## 1. The Ledger

### Balance Calculation Query

```python
# From payouts/models.py - Merchant.available_balance property
def available_balance(self):
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
```

### Why Credits and Debits Are Modeled This Way

1. **Derived Balance**: The balance is NOT stored. It's always computed from the ledger entries. This prevents data drift.

2. **Paise as Integer**: All amounts are stored as BigInteger in paise (1 rupee = 100 paise). This eliminates floating-point precision errors.

3. **Status-Based Calculation**: Only debits in 'pending' or 'processing' status are subtracted from credits. Completed debits are already reflected, and failed debits are reversed by creating a new credit entry.

4. **Database-Level Aggregation**: The balance uses SQL SUM, not Python arithmetic. This ensures consistency even with concurrent operations.

---

## 2. The Lock

### Exact Code That Prevents Concurrent Overdraws

```python
# From payouts/views.py - PayoutListCreateView.post()
def post(self, request):
    # ...
    try:
        with transaction.atomic():
            # Lock merchant row to prevent concurrent modifications
            merchant = Merchant.objects.select_for_update().get(id=merchant_id)
            
            # Check available balance
            available = merchant.available_balance
            
            if available < amount_paise:
                return Response(
                    {'error': 'Insufficient balance', ...},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Create payout record
            payout = Payout.objects.create(...)
```

### Database Primitive Used

The `select_for_update()` method uses **SELECT ... FOR UPDATE** (row-level locking) at the database level.

- When one transaction holds the lock (e.g., processing a payout), other transactions must wait
- This prevents the race condition where two simultaneous requests both see sufficient balance
- The lock is released when the transaction commits or rolls back

---

## 3. The Idempotency

### How the System Knows It Has Seen a Key Before

```python
# From payouts/views.py
existing_key = IdempotencyKey.objects.filter(
    merchant=merchant,
    key=idempotency_key
).first()

if existing_key:
    if existing_key.expires_at > timezone.now():
        return Response(existing_key.response_data)
```

### What Happens If the First Request Is In Flight When the Second Arrives

The idempotency key lookup happens AFTER the database lock is acquired:

```python
# From payouts/models.py - IdempotencyKey.get_or_create_response()
@classmethod
def get_or_create_response(cls, merchant, key, payout_data, create_payout_func):
    with transaction.atomic():
        try:
            existing = cls.objects.select_for_update().get(
                merchant=merchant,
                key=key
            )
            # Return cached response
            return existing.response_data, existing.payout
        except cls.DoesNotExist:
            # Create new payout
            payout = create_payout_func()
            # ...
```

Using `select_for_update()` on the idempotency key itself ensures that:
1. If request 1 is processing, request 2 waits at the lock
2. By the time request 2 proceeds, request 1 has either committed or rolled back
3. If committed, request 2 gets the cached response
4. If rolled back, request 2 can proceed with creating a new payout

---

## 4. The State Machine

### Where Failed-to-Completed Is Blocked

```python
# From payouts/models.py - Payout.save()
def save(self, *args, **kwargs):
    if self.pk:
        old_instance = Payout.objects.get(pk=self.pk)
        old_state = old_instance.state
        new_state = self.state
        
        # Define legal transitions
        legal_transitions = {
            'pending': ['processing'],
            'processing': ['completed', 'failed'],
            'completed': [],  # No transitions allowed!
            'failed': [],     # No transitions allowed!
        }
        
        if new_state not in legal_transitions.get(old_state, []):
            if old_state != new_state:
                raise ValueError(
                    f"Illegal state transition: {old_state} -> {new_state}"
                )
    
    super().save(*args, **kwargs)
```

The check is in the model's `save()` method, which runs BEFORE any database write. This ensures:
- `completed` state cannot transition to anything (dead end)
- `failed` state cannot transition to anything (dead end)
- No backward transitions are possible

---

## 5. The AI Audit

### One Specific Example Where AI Wrote Subtly Wrong Code

**What AI Gave Me:**

```python
# AI's initial balance calculation (WRONG)
@property
def available_balance(self):
    credits = self.ledger_entries.filter(entry_type='credit').aggregate(Sum('amount_paise'))
    debits = self.ledger_entries.filter(entry_type='debit').aggregate(Sum('amount_paise'))
    return (credits['amount_paise__sum'] or 0) - (debits['amount_paise__sum'] or 0)
```

**What I Caught:**

The AI was subtracting ALL debits, including completed ones. This double-counts because:
1. When a payout completes, the debit is already subtracted from balance
2. The AI was subtracting it again in the aggregate

This would show the WRONG balance - lower than actual by the amount of completed payouts.

**What I Replaced It With:**

```python
# Corrected balance calculation
@property
def available_balance(self):
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
```

The fix: Only subtract debits that are still `pending` or `processing`. Completed debits have already reduced the balance; failed debits are reversed by creating a new credit entry.

---

## Additional Notes

### Why PostgreSQL?

- **ACID Compliance**: Critical for financial transactions
- **Row-Level Locking**: `SELECT FOR UPDATE` works reliably
- **JSON Support**: For idempotency response caching
- **Production Standard**: Matches the challenge requirements

### Why Django-Q?

- Simple setup (no external Redis required for development)
- Built-in retry logic with exponential backoff
- Works well with Django's ORM

### What Was NOT Implemented

- Webhook delivery (optional bonus)
- Event sourcing (optional bonus)
- Docker-compose (left as exercise for user)

### Testing Strategy

- **Concurrency Test**: Uses threading to simulate simultaneous requests
- **Idempotency Test**: Verifies same response for duplicate keys
- **State Machine Test**: Verifies illegal transitions are blocked
- **Balance Integrity Test**: Verifies the core invariant

---

*This implementation prioritizes correctness over features. The focus is on money integrity, concurrency handling, and idempotency - the parts that actually matter for a payment system.*