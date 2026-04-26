"""
URL configuration for payouts API.
"""

from django.urls import path
from . import views

urlpatterns = [
    # Merchant endpoints
    path('merchants', views.MerchantListCreateView.as_view(), name='merchant-list-create'),
    path('merchants/<uuid:merchant_id>', views.MerchantDetailView.as_view(), name='merchant-detail'),
    path('merchants/<uuid:merchant_id>/balance', views.MerchantBalanceView.as_view(), name='merchant-balance'),
    path('merchants/<uuid:merchant_id>/ledger', views.MerchantLedgerView.as_view(), name='merchant-ledger'),
    
    # Payout endpoints
    path('payouts', views.PayoutListCreateView.as_view(), name='payout-list-create'),
    path('payouts/<uuid:payout_id>', views.PayoutDetailView.as_view(), name='payout-detail'),
    
    # Bank account endpoints
    path('bank-accounts', views.BankAccountListCreateView.as_view(), name='bank-account-list-create'),
]