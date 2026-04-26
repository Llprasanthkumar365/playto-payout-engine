"""
Management command to seed test data.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
import uuid

from payouts.models import Merchant, BankAccount, LedgerEntry, Payout


class Command(BaseCommand):
    help = 'Seed test data for the payout engine'
    
    def handle(self, *args, **options):
        self.stdout.write('Seeding test data...')
        
        # Create merchants
        merchants_data = [
            {
                'name': 'Tech Solutions Pvt Ltd',
                'email': 'tech@playto-test.in',
            },
            {
                'name': 'Digital Agency Co',
                'email': 'agency@playto-test.in',
            },
            {
                'name': 'Freelance Developer',
                'email': 'freelancer@playto-test.in',
            },
        ]
        
        merchants = []
        for data in merchants_data:
            merchant, created = Merchant.objects.get_or_create(
                email=data['email'],
                defaults={'name': data['name']}
            )
            merchants.append(merchant)
            if created:
                self.stdout.write(f'Created merchant: {merchant.name}')
            else:
                self.stdout.write(f'Merchant already exists: {merchant.name}')
        
        # Create bank accounts and credit ledger entries for each merchant
        for i, merchant in enumerate(merchants):
            # Create bank account
            bank_account, created = BankAccount.objects.get_or_create(
                merchant=merchant,
                account_number=f'123456789{i}',
                defaults={
                    'ifsc_code': 'HDFC0001234',
                    'bank_name': 'HDFC Bank',
                    'account_holder_name': merchant.name,
                    'is_verified': True,
                }
            )
            
            # Create credit entries (simulated customer payments)
            credit_amounts = [50000, 75000, 100000]  # In paise
            
            for j, amount in enumerate(credit_amounts):
                LedgerEntry.objects.get_or_create(
                    merchant=merchant,
                    entry_type='credit',
                    amount_paise=amount,
                    status='completed',
                    reference=f'PAY-{uuid.uuid4().hex[:8].upper()}',
                    defaults={
                        'description': f'Simulated payment from customer {j+1}'
                    }
                )
            
            self.stdout.write(
                f'Created credits for {merchant.name}: '
                f'{sum(credit_amounts)} paise total'
            )
        
        # Create some sample payouts
        if merchants:
            # Create a pending payout for the first merchant
            if BankAccount.objects.filter(merchant=merchants[0]).exists():
                bank_account = BankAccount.objects.filter(merchant=merchants[0]).first()
                
                # Check if payout already exists
                if not Payout.objects.filter(merchant=merchants[0]).exists():
                    payout = Payout.objects.create(
                        merchant=merchants[0],
                        bank_account=bank_account,
                        amount_paise=10000,
                        state='pending',
                        idempotency_key=f'test-payout-{uuid.uuid4()}'
                    )
                    
                    LedgerEntry.objects.create(
                        merchant=merchants[0],
                        entry_type='debit',
                        amount_paise=10000,
                        status='pending',
                        reference=str(payout.id),
                        description=f'Test payout request {payout.id}'
                    )
                    
                    self.stdout.write(f'Created pending payout for {merchants[0].name}')
        
        self.stdout.write(self.style.SUCCESS('Seed data created successfully!'))
        
        # Print summary
        self.stdout.write('\n--- Summary ---')
        for merchant in merchants:
            self.stdout.write(
                f'{merchant.name}: Balance = {merchant.available_balance} paise, '
                f'Held = {merchant.held_balance} paise'
            )