"""
Django admin configuration for payouts.
"""

from django.contrib import admin
from .models import Merchant, BankAccount, LedgerEntry, Payout, IdempotencyKey


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'created_at']
    search_fields = ['name', 'email']


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ['account_holder_name', 'bank_name', 'account_number', 'is_verified']
    list_filter = ['is_verified', 'bank_name']


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ['merchant', 'entry_type', 'amount_paise', 'status', 'created_at']
    list_filter = ['entry_type', 'status']
    search_fields = ['reference']


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = ['id', 'merchant', 'amount_paise', 'state', 'retry_count', 'created_at']
    list_filter = ['state']
    search_fields = ['id', 'merchant__name']


@admin.register(IdempotencyKey)
class IdempotencyKeyAdmin(admin.ModelAdmin):
    list_display = ['merchant', 'key', 'payout', 'expires_at']
    list_filter = ['merchant']
    search_fields = ['key']