"""
Serializers for the Playto Payout API.
"""

from rest_framework import serializers
from .models import Merchant, BankAccount, LedgerEntry, Payout, IdempotencyKey


class MerchantSerializer(serializers.ModelSerializer):
    """Serializer for Merchant model."""
    
    available_balance = serializers.IntegerField(read_only=True)
    held_balance = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = Merchant
        fields = ['id', 'name', 'email', 'available_balance', 'held_balance', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class BankAccountSerializer(serializers.ModelSerializer):
    """Serializer for BankAccount model."""
    
    class Meta:
        model = BankAccount
        fields = ['id', 'account_number', 'ifsc_code', 'bank_name', 'account_holder_name', 'is_verified', 'created_at']
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {
            'account_number': {'write_only': True}
        }


class LedgerEntrySerializer(serializers.ModelSerializer):
    """Serializer for LedgerEntry model."""
    
    class Meta:
        model = LedgerEntry
        fields = ['id', 'entry_type', 'amount_paise', 'status', 'reference', 'description', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class PayoutCreateSerializer(serializers.Serializer):
    """Serializer for creating payout requests."""
    
    amount_paise = serializers.IntegerField(min_value=1)
    bank_account_id = serializers.UUIDField()
    
    def validate_amount_paise(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than 0")
        return value


class PayoutSerializer(serializers.ModelSerializer):
    """Serializer for Payout model."""
    
    class Meta:
        model = Payout
        fields = [
            'id', 'merchant', 'bank_account', 'amount_paise', 'state',
            'idempotency_key', 'retry_count', 'error_message',
            'created_at', 'updated_at', 'processed_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class PayoutResponseSerializer(serializers.ModelSerializer):
    """Serializer for payout API responses."""
    
    bank_account = BankAccountSerializer(read_only=True)
    
    class Meta:
        model = Payout
        fields = [
            'id', 'amount_paise', 'state', 'retry_count', 'error_message',
            'created_at', 'processed_at', 'bank_account'
        ]


class MerchantBalanceSerializer(serializers.Serializer):
    """Serializer for merchant balance response."""
    
    merchant_id = serializers.UUIDField()
    merchant_name = serializers.CharField()
    available_balance = serializers.IntegerField()
    held_balance = serializers.IntegerField()
    total_credits = serializers.IntegerField()
    total_debits = serializers.IntegerField()